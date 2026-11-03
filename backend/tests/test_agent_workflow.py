"""Top-level LangGraph routing for persisted Agent runs."""

from collections.abc import Generator
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings
from app.main import create_app
from app.models import AgentRun, ApprovalRequest, Base, Company, JobPosting, User, utc_now
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
from app.routes.research import research_company_for_job


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
