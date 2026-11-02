"""Deterministic tests for versioned skill runs and approval-gated draft writes."""

import asyncio
import json
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from httpx import MockTransport
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from starlette.requests import Request

from app.core.config import Settings
from app.main import create_app
from app.models import (
    AgentRun,
    ApplicationPrepPack,
    ApprovalRequest,
    AuditEvent,
    Base,
    Company,
    JobPosting,
    ResumeVersion,
    User,
    utc_now,
)
from app.routes.skills import (
    approve_request,
    create_skill_run,
    execute_approved_action,
    request_prep_pack_approval,
    reject_request,
    run_skill_workflow,
)
from app.routes.resumes import delete_resume
from app.schemas import SkillRunCreate
from app.services.skills import (
    SKILLS,
    SkillDraftCandidate,
    SkillSectionCandidate,
    OpenAICompatibleSkillProvider,
    SkillServiceError,
    validate_skill_draft,
)
from app.routes.skills import run_skill_workflow


class FakeSkillProvider:
    def __init__(self, *, invalid_quote: bool = False, fail: bool = False) -> None:
        self.invalid_quote = invalid_quote
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def generate(self, skill, *, job, profile, questions, sources, settings):
        self.calls.append({"skill": skill.id, "job": job, "profile": profile, "questions": questions, "sources": sources})
        if self.fail:
            raise SkillServiceError("skill_provider_unavailable", "模型服务暂时不可用，请稍后重试。")
        quote = "Python 项目经历" if self.invalid_quote else "熟悉 Python，完成过数据分析项目"
        return (
            SkillDraftCandidate(
                summary="生成了待核对的申请准备草稿。",
                checklist=[{"title": "核对项目指标", "reason": "岗位希望看到可验证的项目结果。"}],
                sections=[
                    SkillSectionCandidate(
                        title="项目经历表达建议",
                        content="请补充真实项目中的个人职责和结果。",
                        citations=[{"source_id": "confirmed-resume", "quote": quote}],
                    )
                ],
                open_questions=["请确认是否拥有可公开展示的项目数据。"],
                warnings=[],
            ),
            "fake-chat-model",
        )


@pytest.fixture
def test_context(tmp_path: Path) -> Generator[dict[str, object], None, None]:
    database_url = f"sqlite:///{tmp_path / 'skills.sqlite3'}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        secret_key="skills-test-secret-that-is-long-enough",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
        llm_base_url="https://models.example/v1",
        llm_api_key="test-model-key",
        llm_model="test-chat-model",
    )
    with factory.begin() as session:
        owner = User(email="skills-owner@example.com", password_hash="unused")
        other = User(email="skills-other@example.com", password_hash="unused")
        session.add_all([owner, other])
        session.flush()
        company = Company(
            user_id=owner.id,
            name="星河科技",
            normalized_name="星河科技",
        )
        session.add(company)
        session.flush()
        job = JobPosting(
            user_id=owner.id,
            company_id=company.id,
            title="数据分析实习生",
            city="上海",
            description="岗位要求：熟悉 Python，能够完成数据分析项目。",
            required_skills=["Python", "SQL"],
            source_type="paste",
        )
        resume = ResumeVersion(
            user_id=owner.id,
            filename="resume.txt",
            source_type="paste",
            content_type="text/plain",
            extracted_text="熟悉 Python，完成过数据分析项目",
            confirmed_at=utc_now(),
        )
        session.add_all([job, resume])
        session.flush()
        ids = {"owner": owner.id, "other": other.id, "job": job.id, "resume": resume.id}

    provider = FakeSkillProvider()
    app = create_app(settings, factory, skill_provider=provider)
    with factory() as session:
        yield {
            "app": app,
            "factory": factory,
            "settings": settings,
            "provider": provider,
            "session": session,
            **ids,
        }
    engine.dispose()


def make_request(app: FastAPI, path: str = "/api/v1/skills/runs") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"origin", b"http://localhost:3000")],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
            "app": app,
        }
    )


def make_successful_prep_run(context: dict[str, object]) -> UUID:
    session = context["session"]
    owner_id = context["owner"]
    job_id = context["job"]
    assert isinstance(session, Session)
    run = AgentRun(
        user_id=owner_id,
        job_id=job_id,
        resume_version_id=context["resume"],
        task_type="skill_workflow",
        skill_id="application_prep_pack",
        skill_version="1.0.0",
        status="queued",
        input_text="{}",
        events=[],
    )
    session.add(run)
    session.commit()
    factory = context["factory"]
    provider = context["provider"]
    app = context["app"]
    assert isinstance(factory, sessionmaker) and isinstance(provider, FakeSkillProvider)
    workflow_result = asyncio.run(
        run_skill_workflow(
            run.id,
            factory,
            context["settings"],
            provider,
            app.state.skill_checkpoint_saver,
        )
    )
    assert workflow_result is not None and workflow_result.get("__interrupt__")
    session.refresh(run)
    assert run.status == "succeeded"
    return run.id


def test_skill_catalog_is_versioned_and_covers_prd_templates() -> None:
    assert {skill.id for skill in SKILLS} == {
        "job_analysis",
        "resume_targeting",
        "application_answers",
        "company_research",
        "interview_prep",
        "application_prep_pack",
    }
    assert all(skill.version and skill.catalog_item().boundaries for skill in SKILLS)
    with pytest.raises(ValueError, match="至少提供一个"):
        SkillRunCreate.model_validate(
            {"skill_id": "application_answers", "job_id": str(uuid4()), "idempotency_key": "a" * 32}
        )


def test_skill_run_creation_is_idempotent_and_owner_scoped(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    payload = SkillRunCreate.model_validate(
        {
            "skill_id": "job_analysis",
            "job_id": str(context["job"]),
            "idempotency_key": "skill-run-idempotency-0001",
        }
    )
    response = Response(status_code=202)
    first = create_skill_run(
        payload,
        BackgroundTasks(),
        make_request(context["app"]),
        response,
        owner,
        session,
        context["settings"],
    )
    assert first.status == "queued"
    duplicate_response = Response(status_code=202)
    duplicate = create_skill_run(
        payload,
        BackgroundTasks(),
        make_request(context["app"]),
        duplicate_response,
        owner,
        session,
        context["settings"],
    )
    assert duplicate.id == first.id
    assert duplicate_response.status_code == 200


def test_workflow_persists_steps_and_removes_invalid_citations(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    factory = context["factory"]
    provider = context["provider"]
    assert isinstance(session, Session) and isinstance(factory, sessionmaker)
    assert isinstance(provider, FakeSkillProvider)
    provider.invalid_quote = True
    run = AgentRun(
        user_id=context["owner"],
        job_id=context["job"],
        resume_version_id=context["resume"],
        task_type="skill_workflow",
        skill_id="application_prep_pack",
        skill_version="1.0.0",
        status="queued",
        input_text=json.dumps({"questions": []}),
        events=[{"id": 1, "event": "progress", "step": "queued", "message": "任务已排队。"}],
    )
    session.add(run)
    session.commit()
    result = asyncio.run(
        run_skill_workflow(
            run.id,
            factory,
            context["settings"],
            provider,
            context["app"].state.skill_checkpoint_saver,
        )
    )
    session.refresh(run)
    assert run.status == "succeeded"
    assert run.result is not None
    section = run.result["sections"][0]
    assert section["citations"] == []
    assert section["needs_user_input"] is True
    assert any("未能在原始资料中核验" in warning for warning in run.result["warnings"])
    assert [event["step"] for event in run.events] == [
        "queued",
        "validate_context",
        "generate_draft",
        "generate_draft",
        "validate_evidence",
        "completed",
    ]
    submitted_sources = provider.calls[0]["sources"]
    assert any(source["id"] == "confirmed-resume" for source in submitted_sources)
    assert result is not None and result.get("__interrupt__")


def test_missing_confirmed_resume_fails_before_model_request(test_context: dict[str, object]) -> None:
    context = test_context
    factory = context["factory"]
    provider = context["provider"]
    session = context["session"]
    assert isinstance(factory, sessionmaker) and isinstance(provider, FakeSkillProvider)
    run = AgentRun(
        user_id=context["owner"],
        job_id=context["job"],
        task_type="skill_workflow",
        skill_id="resume_targeting",
        skill_version="1.0.0",
        status="queued",
        input_text=json.dumps({"questions": [], "resume_id": None}),
        events=[],
    )
    session.add(run)
    session.commit()
    asyncio.run(
        run_skill_workflow(
            run.id,
            factory,
            context["settings"],
            provider,
            context["app"].state.skill_checkpoint_saver,
        )
    )
    session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "confirmed_resume_required"
    assert provider.calls == []


def test_provider_failure_is_persisted_for_visible_retry(test_context: dict[str, object]) -> None:
    context = test_context
    factory = context["factory"]
    provider = context["provider"]
    session = context["session"]
    assert isinstance(factory, sessionmaker) and isinstance(provider, FakeSkillProvider)
    provider.fail = True
    run = AgentRun(
        user_id=context["owner"],
        job_id=context["job"],
        task_type="skill_workflow",
        skill_id="job_analysis",
        skill_version="1.0.0",
        status="queued",
        input_text=json.dumps({"questions": [], "resume_id": None}),
        events=[],
    )
    session.add(run)
    session.commit()
    asyncio.run(
        run_skill_workflow(
            run.id,
            factory,
            context["settings"],
            provider,
            context["app"].state.skill_checkpoint_saver,
        )
    )
    session.refresh(run)
    assert run.status == "failed"
    assert run.attempt_count == 1
    assert run.error_code == "skill_provider_unavailable"
    assert run.error_message == "模型服务暂时不可用，请稍后重试。"


def test_approval_is_hash_bound_and_saves_only_after_explicit_approval(
    test_context: dict[str, object],
) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    run_id = make_successful_prep_run(context)
    approval = request_prep_pack_approval(
        run_id,
        make_request(context["app"], f"/api/v1/skills/runs/{run_id}/approval"),
        owner,
        session,
        context["settings"],
    )
    assert approval.status == "pending"
    with pytest.raises(HTTPException) as not_approved:
        asyncio.run(execute_approved_action(
            approval.id,
            make_request(context["app"], f"/api/v1/skills/approvals/{approval.id}/execute"),
            Response(),
            owner,
            session,
            context["settings"],
        ))
    assert not_approved.value.status_code == 409
    approved = approve_request(
        approval.id,
        make_request(context["app"], f"/api/v1/skills/approvals/{approval.id}/approve"),
        owner,
        session,
        context["settings"],
    )
    assert approved.status == "approved"
    response = Response()
    pack = asyncio.run(execute_approved_action(
        approval.id,
        make_request(context["app"], f"/api/v1/skills/approvals/{approval.id}/execute"),
        response,
        owner,
        session,
        context["settings"],
    ))
    assert pack.agent_run_id == run_id
    assert response.status_code == 201
    assert session.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval.id)).status == "executed"
    assert session.scalar(select(ApplicationPrepPack).where(ApplicationPrepPack.agent_run_id == run_id))
    assert session.scalar(select(AuditEvent).where(AuditEvent.user_id == owner.id))
    duplicate = asyncio.run(execute_approved_action(
        approval.id,
        make_request(context["app"], f"/api/v1/skills/approvals/{approval.id}/execute"),
        Response(),
        owner,
        session,
        context["settings"],
    ))
    assert duplicate.id == pack.id


def test_approval_invalidates_when_draft_changes(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    run_id = make_successful_prep_run(context)
    approval = request_prep_pack_approval(
        run_id,
        make_request(context["app"]),
        owner,
        session,
        context["settings"],
    )
    run = session.get(AgentRun, run_id)
    assert run is not None
    run.result = {**run.result, "summary": "内容被替换"}
    session.commit()
    with pytest.raises(HTTPException) as invalidated:
        approve_request(
            approval.id,
            make_request(context["app"]),
            owner,
            session,
            context["settings"],
        )
    assert invalidated.value.status_code == 409
    assert session.get(ApprovalRequest, approval.id).status == "invalidated"
    assert session.scalar(select(ApplicationPrepPack).where(ApplicationPrepPack.agent_run_id == run_id)) is None


def test_approval_expires_and_can_be_requested_again(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    run_id = make_successful_prep_run(context)
    first = request_prep_pack_approval(run_id, make_request(context["app"]), owner, session, context["settings"])
    record = session.get(ApprovalRequest, first.id)
    assert record is not None
    record.expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    with pytest.raises(HTTPException) as expired:
        approve_request(first.id, make_request(context["app"]), owner, session, context["settings"])
    assert expired.value.status_code == 409
    renewed = request_prep_pack_approval(run_id, make_request(context["app"]), owner, session, context["settings"])
    assert renewed.status == "pending"
    assert renewed.id != first.id


def test_rejected_approval_requires_a_new_skill_run(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    run_id = make_successful_prep_run(context)
    approval = request_prep_pack_approval(
        run_id, make_request(context["app"]), owner, session, context["settings"]
    )
    rejected = asyncio.run(
        reject_request(
            approval.id,
            make_request(context["app"]),
            owner,
            session,
            context["settings"],
        )
    )
    assert rejected.status == "rejected"
    duplicate_rejection = asyncio.run(
        reject_request(
            approval.id,
            make_request(context["app"]),
            owner,
            session,
            context["settings"],
        )
    )
    assert duplicate_rejection.status == "rejected"
    with pytest.raises(HTTPException) as duplicate:
        request_prep_pack_approval(
            run_id, make_request(context["app"]), owner, session, context["settings"]
        )
    assert duplicate.value.status_code == 409


def test_execute_rechecks_content_after_approval(test_context: dict[str, object]) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    run_id = make_successful_prep_run(context)
    approval = request_prep_pack_approval(run_id, make_request(context["app"]), owner, session, context["settings"])
    approve_request(approval.id, make_request(context["app"]), owner, session, context["settings"])
    run = session.get(AgentRun, run_id)
    assert run is not None
    run.result = {**run.result, "summary": "已变化的草稿"}
    session.commit()
    with pytest.raises(HTTPException) as invalidated:
        asyncio.run(execute_approved_action(
            approval.id,
            make_request(context["app"]),
            Response(),
            owner,
            session,
            context["settings"],
        ))
    assert invalidated.value.status_code == 409
    session.expire_all()
    stored_approval = session.get(ApprovalRequest, approval.id)
    assert stored_approval is not None and stored_approval.status == "invalidated"
    assert session.scalar(select(ApplicationPrepPack).where(ApplicationPrepPack.agent_run_id == run_id)) is None


def test_deleting_resume_removes_derived_skill_drafts_and_approvals(
    test_context: dict[str, object],
) -> None:
    context = test_context
    session = context["session"]
    assert isinstance(session, Session)
    owner = session.get(User, context["owner"])
    assert owner is not None
    resume_id = context["resume"]
    run_id = make_successful_prep_run(context)
    approval = request_prep_pack_approval(run_id, make_request(context["app"]), owner, session, context["settings"])
    approve_request(approval.id, make_request(context["app"]), owner, session, context["settings"])
    asyncio.run(execute_approved_action(
        approval.id,
        make_request(context["app"]),
        Response(),
        owner,
        session,
        context["settings"],
    ))
    assert session.get(ApplicationPrepPack, session.scalar(select(ApplicationPrepPack.id)))

    delete_resume(
        resume_id,
        make_request(context["app"], f"/api/v1/resumes/{resume_id}"),
        owner,
        session,
        context["settings"],
    )
    assert session.get(ResumeVersion, resume_id) is None
    assert session.get(AgentRun, run_id) is None
    assert session.scalar(select(ApplicationPrepPack).where(ApplicationPrepPack.agent_run_id == run_id)) is None
    assert session.get(ApprovalRequest, approval.id) is None
    audit = session.scalars(select(AuditEvent)).all()
    assert audit and all(event.approval_id is None for event in audit)


def test_skill_provider_uses_chat_api_and_validates_schema() -> None:
    expected = SkillDraftCandidate(
        summary="已生成草稿。",
        sections=[
            {
                "title": "岗位要求",
                "content": "岗位要求 Python。",
                "citations": [{"source_id": "job-description", "quote": "岗位要求 Python"}],
            }
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://models.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-model-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(expected.model_dump(), ensure_ascii=False)}}
                ]
            },
        )

    provider = OpenAICompatibleSkillProvider(transport=MockTransport(handler))
    settings = Settings(
        _env_file=None,
        llm_base_url="https://models.example/v1",
        llm_api_key="test-model-key",
        llm_model="test-chat-model",
    )
    candidate, model = asyncio.run(
        provider.generate(
            SKILLS[0],
            job={"title": "数据分析"},
            profile=None,
            questions=[],
            sources=[{"id": "job-description", "label": "岗位描述", "url": None, "text": "岗位要求 Python"}],
            settings=settings,
        )
    )
    assert model == "test-chat-model"
    validated = validate_skill_draft(
        candidate,
        [{"id": "job-description", "label": "岗位描述", "url": None, "text": "岗位要求 Python"}],
    )
    assert validated.sections[0].citations[0].quote == "岗位要求 Python"
