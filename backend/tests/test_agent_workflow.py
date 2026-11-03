"""Top-level LangGraph routing for persisted Agent runs."""

from collections.abc import Generator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings
from app.main import create_app
from app.models import (
    AgentRun,
    ApprovalRequest,
    Base,
    CandidateProfile,
    Company,
    DocumentChunk,
    JobPosting,
    KnowledgeNote,
    ResumeVersion,
    User,
    utc_now,
)
from app.routes.agent import read_agent_workspace
from app.routes.knowledge import ask_knowledge
from app.routes.matching import create_job_match_run
from app.services.agent_workflow import (
    AgentWorkflowState,
    SUPPORTED_AGENT_WORKFLOWS,
    WorkflowHandler,
    build_agent_workflow_graph,
)
from app.services.job_extraction import JobExtractionError
from app.services.company_research import (
    CompanyResearchDraft,
    CompanyResearchError,
    CompanyResearchFindingCandidate,
    PublicSearchSource,
)
from app.services.knowledge import (
    CitationCandidate,
    GroundedAnswerCandidate,
    KnowledgeServiceError,
)
from app.routes.research import research_company_for_job
from app.schemas import KnowledgeAsk


@pytest.fixture
def workflow_context() -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        owner = User(
            id=uuid4(),
            email="agent-router-owner@example.com",
            password_hash="unused",
            timezone="Asia/Shanghai",
        )
        other = User(
            id=uuid4(),
            email="agent-router-other@example.com",
            password_hash="unused",
            timezone="Asia/Tokyo",
        )
        job = JobPosting(
            id=uuid4(),
            user_id=owner.id,
            title="后端工程师",
            required_skills=[],
            source_type="manual",
            source_captured_at=utc_now(),
        )
        session.add_all([owner, other, job])
        session.commit()
        owner_id = owner.id
        other_id = other.id
        job_id = job.id
    yield {
        "factory": factory,
        "owner_id": owner_id,
        "other_id": other_id,
        "job_id": job_id,
    }
    engine.dispose()


def create_handlers(calls: list[tuple[str, str]]) -> dict[str, WorkflowHandler]:
    handlers: dict[str, WorkflowHandler] = {}

    def create_handler(selected_type: str) -> WorkflowHandler:
        async def handler(state: AgentWorkflowState) -> dict[str, object]:
            calls.append((selected_type, state.get("operation", "run")))
            return {}

        return handler

    for task_type in SUPPORTED_AGENT_WORKFLOWS:
        handlers[task_type] = create_handler(task_type)
    return handlers


def add_run(
    session: Session,
    user: User,
    task_type: str,
    *,
    status: str = "queued",
) -> AgentRun:
    run = AgentRun(
        id=uuid4(),
        user_id=user.id,
        task_type=task_type,
        status=status,
        input_text="private workflow input",
        events=[],
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


class FailingJobExtractionProvider:
    async def extract(self, source_text: str, settings: Settings):
        raise JobExtractionError("test_provider_failure", "Expected test failure.")


class FakeCompanySearchProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[str] = []

    async def search(self, query: str, count: int, settings: Settings):
        assert count == 8
        assert "测试公司" in query
        if self.fail:
            raise CompanyResearchError("research_rate_limited", "Expected test failure.")
        self.queries.append(query)
        return [
            PublicSearchSource(
                source_id="source-1",
                title="测试公司校园招聘",
                url="https://jobs.example.com/campus",
                excerpt="测试公司 2027 届校园招聘现已启动。",
            )
        ]


class FakeCompanyResearchSummarizer:
    async def summarize(self, company_name, job_title, query, sources, settings):
        assert company_name == "测试公司"
        assert job_title == "后端工程师"
        return (
            CompanyResearchDraft(
                findings=[
                    CompanyResearchFindingCandidate(
                        claim="测试公司已启动 2027 届校园招聘。",
                        source_id="source-1",
                        quote="测试公司 2027 届校园招聘现已启动。",
                    )
                ]
            ),
            "test-research-model",
        )


class FakeKnowledgeEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def embed(self, texts: list[str], settings: Settings):
        self.calls += 1
        if self.fail:
            raise KnowledgeServiceError("embedding_timeout", "Expected test failure.")
        return [[1.0, 0.0] for _ in texts], "test-embedding-model"


class FakeKnowledgeAnswerProvider:
    async def answer(self, question, chunks, settings):
        chunk = chunks[0]
        quote = chunk.content[: min(60, len(chunk.content))]
        return GroundedAnswerCandidate(
            answer="求职资料中记录了一个相关项目。",
            citations=[CitationCandidate(chunk_id=chunk.id, quote=quote)],
        )


@pytest.mark.anyio
async def test_dispatch_routes_each_registered_run_type(
    workflow_context: dict[str, object],
) -> None:
    calls: list[tuple[str, str]] = []
    graph = build_agent_workflow_graph(
        workflow_context["factory"], create_handlers(calls)
    )

    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        runs = {
            task_type: add_run(session, owner, task_type)
            for task_type in SUPPORTED_AGENT_WORKFLOWS
        }

    for task_type, run in runs.items():
        await graph.ainvoke(
            {"task_type": task_type, "run_id": run.id, "operation": "run"},
            version="v2",
        )

    assert set(calls) == {(task_type, "run") for task_type in SUPPORTED_AGENT_WORKFLOWS}
    with workflow_context["factory"]() as session:
        for task_type, run in runs.items():
            stored = session.get(AgentRun, run.id)
            assert stored is not None
            assert stored.events[-1]["step"] == "workflow_routed"
            assert stored.task_type == task_type


@pytest.mark.anyio
async def test_dispatch_skips_stale_or_mismatched_runs(
    workflow_context: dict[str, object],
) -> None:
    calls: list[tuple[str, str]] = []
    graph = build_agent_workflow_graph(
        workflow_context["factory"], create_handlers(calls)
    )
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        succeeded = add_run(session, owner, "task_plan", status="succeeded")
        queued = add_run(session, owner, "job_extraction")

    await graph.ainvoke(
        {"task_type": "task_plan", "run_id": succeeded.id, "operation": "run"},
        version="v2",
    )
    await graph.ainvoke(
        {"task_type": "task_plan", "run_id": queued.id, "operation": "run"},
        version="v2",
    )

    assert calls == []


@pytest.mark.anyio
async def test_resume_requires_approval_bound_to_the_same_skill_run(
    workflow_context: dict[str, object],
) -> None:
    calls: list[tuple[str, str]] = []
    graph = build_agent_workflow_graph(
        workflow_context["factory"], create_handlers(calls)
    )
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        other = session.get(User, workflow_context["other_id"])
        job = session.get(JobPosting, workflow_context["job_id"])
        assert owner is not None and other is not None and job is not None
        run = AgentRun(
            id=uuid4(),
            user_id=owner.id,
            job_id=job.id,
            task_type="skill_workflow",
            skill_id="application_prep_pack",
            status="succeeded",
            input_text="private skill input",
            events=[],
        )
        session.add(run)
        session.flush()
        approval = ApprovalRequest(
            id=uuid4(),
            user_id=owner.id,
            agent_run_id=run.id,
            job_id=job.id,
            action_type="save_prep_pack",
            summary="保存申请准备包",
            payload_hash="a" * 64,
            approval_hash="b" * 64,
            status="approved",
            expires_at=utc_now() + timedelta(minutes=10),
        )
        foreign_approval = ApprovalRequest(
            id=uuid4(),
            user_id=other.id,
            agent_run_id=run.id,
            job_id=job.id,
            action_type="save_prep_pack",
            summary="不属于该账户的审批",
            payload_hash="c" * 64,
            approval_hash="d" * 64,
            status="approved",
            expires_at=utc_now() + timedelta(minutes=10),
        )
        session.add_all([approval, foreign_approval])
        session.commit()

    await graph.ainvoke(
        {
            "task_type": "skill_workflow",
            "run_id": run.id,
            "operation": "resume",
            "approval_id": approval.id,
            "decision": "approved",
        },
        version="v2",
    )
    assert calls == [("skill_workflow", "resume")]

    with pytest.raises(HTTPException) as error:
        await graph.ainvoke(
            {
                "task_type": "skill_workflow",
                "run_id": run.id,
                "operation": "resume",
                "approval_id": foreign_approval.id,
                "decision": "approved",
            },
            version="v2",
        )
    assert error.value.status_code == 409
    assert calls == [("skill_workflow", "resume")]


@pytest.mark.anyio
async def test_app_router_runs_registered_job_extraction_handler(
    workflow_context: dict[str, object],
) -> None:
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        run = add_run(session, owner, "job_extraction")

    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="agent-workflow-test-secret-that-is-long-enough",
        ),
        workflow_context["factory"],
        job_extraction_provider=FailingJobExtractionProvider(),
    )
    await app.state.agent_workflow_graph.ainvoke(
        {"task_type": "job_extraction", "run_id": run.id, "operation": "run"},
        version="v2",
    )

    with workflow_context["factory"]() as session:
        stored = session.get(AgentRun, run.id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.attempt_count == 1
        assert stored.error_code == "test_provider_failure"
        assert stored.events[0]["step"] == "workflow_routed"


@pytest.mark.anyio
async def test_app_router_runs_company_research_with_verified_sources(
    workflow_context: dict[str, object],
) -> None:
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        job = session.get(JobPosting, workflow_context["job_id"])
        assert owner is not None and job is not None
        company = Company(
            id=uuid4(),
            user_id=owner.id,
            name="测试公司",
            normalized_name="测试公司",
        )
        session.add(company)
        session.flush()
        job.company_id = company.id
        session.commit()

    search_provider = FakeCompanySearchProvider()
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="company-workflow-test-secret-that-is-long-enough",
        ),
        workflow_context["factory"],
        company_research_search_provider=search_provider,
        company_research_summarizer=FakeCompanyResearchSummarizer(),
    )
    path = f"/api/v1/jobs/{workflow_context['job_id']}/research"
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"origin", b"http://localhost:3000")],
            "client": ("testclient", 123),
            "server": ("testserver", 80),
            "app": app,
        }
    )
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        response = await research_company_for_job(
            workflow_context["job_id"],
            request,
            owner,
            session,
            app.state.settings,
        )

    assert response.company_name == "测试公司"
    assert response.findings[0].source_id == "source-1"
    assert len(search_provider.queries) == 1
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        cached_response = await research_company_for_job(
            workflow_context["job_id"],
            request,
            owner,
            session,
            app.state.settings,
        )
    assert cached_response.run_id == response.run_id
    assert len(search_provider.queries) == 1

    with workflow_context["factory"]() as session:
        stored = session.get(AgentRun, response.run_id)
        assert stored is not None
        assert stored.status == "succeeded"
        assert stored.attempt_count == 1
        assert stored.model_name == "test-research-model"
        assert stored.result["findings"][0]["source_id"] == "source-1"
        assert [event["step"] for event in stored.events] == [
            "queued",
            "workflow_routed",
            "public_search",
            "summarize",
            "completed",
        ]


@pytest.mark.anyio
async def test_company_research_failure_is_saved_by_unified_router(
    workflow_context: dict[str, object],
) -> None:
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        job = session.get(JobPosting, workflow_context["job_id"])
        assert owner is not None and job is not None
        company = Company(
            id=uuid4(),
            user_id=owner.id,
            name="测试公司",
            normalized_name="测试公司",
        )
        session.add(company)
        session.flush()
        job.company_id = company.id
        run = add_run(session, owner, "company_research")
        run.job_id = job.id
        run.input_text = '"测试公司" 招聘 校招 官方'
        session.commit()

    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="company-workflow-failure-secret-is-long-enough",
        ),
        workflow_context["factory"],
        company_research_search_provider=FakeCompanySearchProvider(fail=True),
        company_research_summarizer=FakeCompanyResearchSummarizer(),
    )
    with pytest.raises(HTTPException) as error:
        await app.state.agent_workflow_graph.ainvoke(
            {"task_type": "company_research", "run_id": run.id, "operation": "run"},
            version="v2",
        )
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "research_rate_limited"

    with workflow_context["factory"]() as session:
        stored = session.get(AgentRun, run.id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.attempt_count == 1
        assert stored.error_code == "research_rate_limited"
        assert stored.events[-1]["event"] == "failed"


@pytest.mark.anyio
async def test_knowledge_qa_runs_through_router_and_keeps_owner_citations(
    workflow_context: dict[str, object],
) -> None:
    note_content = "我在星河科技实习期间使用 Python 和 PostgreSQL 开发订单服务。"
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        other = session.get(User, workflow_context["other_id"])
        assert owner is not None and other is not None
        note = KnowledgeNote(user_id=owner.id, title="实习项目", content=note_content)
        session.add(note)
        session.flush()
        session.add(
            DocumentChunk(
                user_id=owner.id,
                source_type="note",
                source_id=note.id,
                source_name=note.title,
                chunk_index=0,
                content=note_content,
                embedding=[1.0, 0.0],
                embedding_dimensions=2,
                embedding_model="test-embedding-model",
            )
        )
        session.commit()
        note_id = note.id

    embedding_provider = FakeKnowledgeEmbeddingProvider()
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="knowledge-workflow-test-secret-long-enough",
        ),
        workflow_context["factory"],
        embedding_provider=embedding_provider,
        knowledge_answer_provider=FakeKnowledgeAnswerProvider(),
    )
    path = "/api/v1/knowledge/ask"
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"origin", b"http://localhost:3000")],
            "client": ("testclient", 123),
            "server": ("testserver", 80),
            "app": app,
        }
    )
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        response = await ask_knowledge(
            KnowledgeAsk(question="我在实习项目中使用了什么技术？", top_k=3),
            request,
            owner,
            session,
            app.state.settings,
        )
    assert response.no_evidence is False
    assert response.citations[0].source_id == note_id
    assert response.citations[0].quote in note_content

    with workflow_context["factory"]() as session:
        other = session.get(User, workflow_context["other_id"])
        assert other is not None
        no_index = await ask_knowledge(
            KnowledgeAsk(question="我的简历中有哪些项目经历？"),
            request,
            other,
            session,
            app.state.settings,
        )
        workspace_owner = session.get(User, workflow_context["owner_id"])
        assert workspace_owner is not None
        workspace = read_agent_workspace(workspace_owner, session)
    assert no_index.no_evidence is True
    assert no_index.citations == []
    assert embedding_provider.calls == 1
    assert any(run.task_type == "knowledge_qa" for run in workspace.recent_runs)

    failing_app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="knowledge-workflow-failure-test-secret",
        ),
        workflow_context["factory"],
        embedding_provider=FakeKnowledgeEmbeddingProvider(fail=True),
        knowledge_answer_provider=FakeKnowledgeAnswerProvider(),
    )
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        with pytest.raises(HTTPException) as error:
            await ask_knowledge(
                KnowledgeAsk(question="模型不可用时任务应如何记录？"),
                Request({**request.scope, "app": failing_app}),
                owner,
                session,
                failing_app.state.settings,
            )
    assert error.value.status_code == 503

    with workflow_context["factory"]() as session:
        runs = session.scalars(
            select(AgentRun)
            .where(AgentRun.task_type == "knowledge_qa")
        ).all()
        assert len(runs) == 3
        runs_by_question = {run.input_text: run for run in runs}
        assert runs_by_question["我在实习项目中使用了什么技术？"].status == "succeeded"
        assert (
            runs_by_question["我在实习项目中使用了什么技术？"].result["citations"][0]["source_id"]
            == str(note_id)
        )
        assert runs_by_question["我的简历中有哪些项目经历？"].result["no_evidence"] is True
        failed = runs_by_question["模型不可用时任务应如何记录？"]
        assert failed.status == "failed"
        assert failed.attempt_count == 1
        assert failed.error_code == "embedding_timeout"
        assert failed.events[-1]["event"] == "failed"


@pytest.mark.anyio
async def test_job_match_runs_through_router_and_records_owner_scoped_result(
    workflow_context: dict[str, object],
) -> None:
    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        other = session.get(User, workflow_context["other_id"])
        job = session.get(JobPosting, workflow_context["job_id"])
        assert owner is not None and other is not None and job is not None
        job.city = "上海"
        job.education_requirement = "本科及以上"
        job.required_skills = ["Python", "Java"]
        session.add(
            CandidateProfile(
                user_id=owner.id,
                education="本科",
                target_roles=["后端工程师"],
                target_cities=["上海"],
                industries=[],
                skills=[],
            )
        )
        session.add(
            ResumeVersion(
                user_id=owner.id,
                filename="confirmed-resume.txt",
                source_type="paste",
                content_type="text/plain",
                extracted_text="项目中使用 Python 开发服务并编写接口测试。",
                confirmed_at=utc_now(),
            )
        )
        other_job = JobPosting(
            user_id=other.id,
            title="数据工程师",
            required_skills=[],
            source_type="manual",
            source_captured_at=utc_now(),
        )
        session.add(other_job)
        session.commit()
        other_job_id = other_job.id

    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite://",
            secret_key="job-match-workflow-test-secret-long-enough",
            allowed_origins=["http://localhost:3000"],
        ),
        workflow_context["factory"],
    )
    path = f"/api/v1/jobs/{workflow_context['job_id']}/match"
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"origin", b"http://localhost:3000")],
            "client": ("testclient", 123),
            "server": ("testserver", 80),
            "app": app,
        }
    )

    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        assert owner is not None
        response = await create_job_match_run(
            workflow_context["job_id"], request, owner, session, app.state.settings
        )
        assert next(item for item in response.criteria if item.key == "education").status == "meets"
        assert response.skills[0].status == "evidenced"
        assert response.skills[1].status == "not_found"

    with workflow_context["factory"]() as session:
        owner = session.get(User, workflow_context["owner_id"])
        other = session.get(User, workflow_context["other_id"])
        assert owner is not None and other is not None
        workspace = read_agent_workspace(owner, session)
        with pytest.raises(HTTPException) as not_owned:
            await create_job_match_run(
                workflow_context["job_id"], request, other, session, app.state.settings
            )
        assert not_owned.value.status_code == 404

        with pytest.raises(HTTPException) as no_resume:
            await create_job_match_run(
                other_job_id, request, other, session, app.state.settings
            )
        assert no_resume.value.status_code == 409

    assert any(run.task_type == "job_match" for run in workspace.recent_runs)
    with workflow_context["factory"]() as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.task_type == "job_match")).all()
        assert len(runs) == 2
        successful = next(run for run in runs if run.user_id == workflow_context["owner_id"])
        failed = next(run for run in runs if run.user_id == workflow_context["other_id"])
        assert successful.status == "succeeded"
        assert successful.attempt_count == 1
        assert successful.result["skills"][0]["status"] == "evidenced"
        assert [event["step"] for event in successful.events] == [
            "queued",
            "workflow_routed",
            "compare",
            "completed",
        ]
        assert failed.status == "failed"
        assert failed.error_code == "confirmed_resume_required"
