"""Approval-gated external email actions with deterministic fake SMTP execution."""

import asyncio
from collections.abc import Generator
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings
from app.main import create_app
from app.models import AuditEvent, Base, Company, ExternalActionApproval, JobPosting, User, utc_now
from app.routes.jobs import delete_job
from app.routes.external_actions import (
    approve_external_action,
    create_email_action,
    execute_external_action,
    read_capabilities,
    reject_external_action,
)
from app.schemas import ExternalEmailActionCreate
from app.services.external_actions import (
    EMAIL_SEND_ACTION,
    ExternalActionRegistry,
    SMTPEmailActionHandler,
)


class FakeEmailExecutor:
    action_type = EMAIL_SEND_ACTION

    def __init__(self, *, configured: bool = True, fail: bool = False) -> None:
        self.configured = configured
        self.fail = fail
        self.calls: list[dict[str, str | UUID]] = []

    def is_configured(self, settings: Settings) -> bool:
        return self.configured

    async def execute(
        self,
        settings: Settings,
        *,
        action_id: UUID,
        target: str,
        payload: dict[str, str],
    ) -> str:
        self.calls.append(
            {
                "action_id": action_id,
                "recipient": target,
                "subject": payload["subject"],
                "body": payload["body"],
            }
        )
        if self.fail:
            raise TimeoutError("SMTP response timed out")
        return f"<offerpilot-{action_id}@offerpilot.local>"


@pytest.fixture
def action_context(tmp_path: Path) -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'external-actions.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    session = factory()
    owner = User(
        email="external-owner@example.com",
        password_hash="unused",
        timezone="Asia/Shanghai",
    )
    other = User(
        email="external-other@example.com",
        password_hash="unused",
        timezone="Asia/Shanghai",
    )
    session.add_all([owner, other])
    session.commit()
    session.refresh(owner)
    session.refresh(other)
    settings = Settings(
        _env_file=None,
        allowed_origins=["http://localhost:3000"],
        smtp_host="smtp.example.com",
        smtp_username="offerpilot",
        smtp_password="secret-test-only",
        smtp_sender="jobs@example.com",
    )
    executor = FakeEmailExecutor()
    app = FastAPI()
    app.state.external_action_registry = ExternalActionRegistry([executor])
    yield {
        "app": app,
        "engine": engine,
        "factory": factory,
        "session": session,
        "owner": owner,
        "other": other,
        "settings": settings,
        "executor": executor,
    }
    session.close()
    engine.dispose()


def request_for(app: FastAPI, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"origin", b"http://localhost:3000")],
            "query_string": b"",
            "scheme": "http",
            "app": app,
        }
    )


def make_payload(**overrides: object) -> ExternalEmailActionCreate:
    values: dict[str, object] = {
        "recipient": "Recruiter@example.com",
        "subject": "应聘后端开发工程师",
        "body": "您好，我已核对这封邮件正文，附件为个人简历。",
        "idempotency_key": "email-action-request-0001",
    }
    values.update(overrides)
    return ExternalEmailActionCreate.model_validate(values)


def create_action(context: dict[str, object], payload: ExternalEmailActionCreate):
    return create_email_action(
        payload,
        request_for(context["app"], "/api/v1/external-actions"),
        context["owner"],
        context["session"],
        context["settings"],
    )


def approve_action(context: dict[str, object], action_id: UUID):
    return approve_external_action(
        action_id,
        request_for(context["app"], f"/api/v1/external-actions/{action_id}/approve"),
        context["owner"],
        context["session"],
        context["settings"],
    )


@pytest.mark.anyio
async def test_email_requires_approval_and_execute_is_idempotent(
    action_context: dict[str, object],
) -> None:
    context = action_context
    executor = context["executor"]
    session = context["session"]
    action = create_action(context, make_payload())

    assert action.status == "pending"
    assert executor.calls == []
    approved = approve_action(context, action.id)
    assert approved.status == "approved"

    executed = await execute_external_action(
        action.id,
        request_for(context["app"], f"/api/v1/external-actions/{action.id}/execute"),
        context["owner"],
        session,
        context["settings"],
    )
    replay = await execute_external_action(
        action.id,
        request_for(context["app"], f"/api/v1/external-actions/{action.id}/execute"),
        context["owner"],
        session,
        context["settings"],
    )
    assert executed.status == replay.status == "executed"
    assert executed.result == replay.result
    assert len(executor.calls) == 1
    assert executor.calls[0]["recipient"] == "recruiter@example.com"
    events = session.scalars(
        select(AuditEvent.action).where(AuditEvent.entity_id == str(action.id))
    ).all()
    assert set(events) == {
        "external_action_requested",
        "external_action_approved",
        "external_action_execution_started",
        "external_action_executed",
    }


def test_idempotency_conflict_and_unapproved_execution_are_rejected(
    action_context: dict[str, object],
) -> None:
    context = action_context
    action = create_action(context, make_payload())
    replay = create_action(context, make_payload())
    assert replay.id == action.id
    assert context["session"].query(ExternalActionApproval).count() == 1

    with pytest.raises(HTTPException) as unapproved:
        asyncio.run(
            execute_external_action(
                action.id,
                request_for(context["app"], f"/api/v1/external-actions/{action.id}/execute"),
                context["owner"],
                context["session"],
                context["settings"],
            )
        )
    assert unapproved.value.status_code == 409
    with pytest.raises(HTTPException) as conflict:
        create_action(context, make_payload(body="正文发生变化"))
    assert conflict.value.status_code == 409
    assert context["executor"].calls == []


def test_changed_content_invalidates_approval_and_reject_is_terminal(
    action_context: dict[str, object],
) -> None:
    context = action_context
    session = context["session"]
    action = create_action(context, make_payload())
    action_row = session.get(ExternalActionApproval, action.id)
    assert action_row is not None
    action_row.payload = {"subject": "被篡改的主题", "body": "不同内容"}
    session.commit()

    with pytest.raises(HTTPException) as invalidated:
        approve_action(context, action.id)
    assert invalidated.value.status_code == 409
    session.refresh(action_row)
    assert action_row.status == "invalidated"

    rejected_action = create_action(
        context,
        make_payload(idempotency_key="email-action-request-0002"),
    )
    rejected = reject_external_action(
        rejected_action.id,
        request_for(
            context["app"],
            f"/api/v1/external-actions/{rejected_action.id}/reject",
        ),
        context["owner"],
        session,
        context["settings"],
    )
    assert rejected.status == "rejected"
    assert context["executor"].calls == []


def test_expired_approval_cannot_be_approved_or_sent(
    action_context: dict[str, object],
) -> None:
    context = action_context
    session = context["session"]
    action = create_action(context, make_payload())
    action_row = session.get(ExternalActionApproval, action.id)
    assert action_row is not None
    action_row.expires_at = utc_now() - timedelta(seconds=1)
    session.commit()

    with pytest.raises(HTTPException) as expired:
        approve_action(context, action.id)
    assert expired.value.status_code == 409
    session.refresh(action_row)
    assert action_row.status == "expired"
    assert context["executor"].calls == []


@pytest.mark.anyio
async def test_uncertain_smtp_result_is_not_retried(
    action_context: dict[str, object],
) -> None:
    context = action_context
    action = create_action(context, make_payload())
    approve_action(context, action.id)
    context["executor"].fail = True
    path = f"/api/v1/external-actions/{action.id}/execute"

    with pytest.raises(HTTPException) as unknown:
        await execute_external_action(
            action.id,
            request_for(context["app"], path),
            context["owner"],
            context["session"],
            context["settings"],
        )
    assert unknown.value.status_code == 502
    assert context["session"].get(ExternalActionApproval, action.id).status == "outcome_unknown"
    with pytest.raises(HTTPException) as replay:
        await execute_external_action(
            action.id,
            request_for(context["app"], path),
            context["owner"],
            context["session"],
            context["settings"],
        )
    assert replay.value.status_code == 409
    assert len(context["executor"].calls) == 1


@pytest.mark.anyio
async def test_api_restart_converges_inflight_email_to_unknown_outcome(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'restart.sqlite3'}",
        secret_key="external-action-restart-test-secret",
        smtp_host="smtp.example.com",
        smtp_username="offerpilot",
        smtp_password="secret-test-only",
        smtp_sender="jobs@example.com",
    )
    registry = ExternalActionRegistry([FakeEmailExecutor()])
    app = create_app(settings=settings, external_action_registry=registry)
    factory = app.state.session_factory
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    with factory() as session:
        owner = User(email="restart@example.com", password_hash="unused")
        session.add(owner)
        session.flush()
        action = ExternalActionApproval(
            user_id=owner.id,
            action_type="email.send",
            target="recruiter@example.com",
            summary="发送求职邮件",
            payload={"subject": "应聘", "body": "已审批正文"},
            idempotency_key="restart-action-key-0001",
            request_hash="1" * 64,
            payload_hash="2" * 64,
            approval_hash="3" * 64,
            status="executing",
            expires_at=utc_now() + timedelta(minutes=5),
        )
        session.add(action)
        session.commit()
        action_id = action.id

    async with app.router.lifespan_context(app):
        pass

    with factory() as session:
        recovered = session.get(ExternalActionApproval, action_id)
        assert recovered is not None
        assert recovered.status == "outcome_unknown"
        assert "不要直接重试" in recovered.result["message"]
        assert session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_id == str(action_id),
                AuditEvent.action == "external_action_outcome_unknown",
            )
        ) is not None


def test_action_is_user_scoped_and_unconfigured_sender_cannot_create(
    action_context: dict[str, object],
) -> None:
    context = action_context
    capabilities = read_capabilities(
        request_for(context["app"], "/api/v1/external-actions/capabilities"),
        context["owner"],
        context["settings"],
    )
    assert capabilities.email_send_enabled is True
    assert capabilities.recruitment_submission_enabled is False
    action = create_action(context, make_payload())
    with pytest.raises(HTTPException) as hidden:
        from app.routes.external_actions import _owned_action

        _owned_action(context["session"], context["other"], action.id)
    assert hidden.value.status_code == 404

    context["executor"].configured = False
    unavailable_capabilities = read_capabilities(
        request_for(context["app"], "/api/v1/external-actions/capabilities"),
        context["owner"],
        context["settings"],
    )
    assert unavailable_capabilities.email_send_enabled is False
    with pytest.raises(HTTPException) as unavailable:
        create_action(
            context,
            make_payload(idempotency_key="email-action-request-0003"),
        )
    assert unavailable.value.status_code == 503


def test_deleting_a_linked_job_keeps_audit_action_without_stale_job_reference(
    action_context: dict[str, object],
) -> None:
    context = action_context
    session = context["session"]
    owner = context["owner"]
    company = Company(user_id=owner.id, name="示例公司", normalized_name="示例公司")
    session.add(company)
    session.flush()
    job = JobPosting(
        user_id=owner.id,
        company_id=company.id,
        title="后端工程师",
        required_skills=[],
        source_type="manual",
        source_captured_at=utc_now(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    action = create_action(
        context,
        make_payload(
            job_id=job.id,
            idempotency_key="email-action-linked-job-01",
        ),
    )

    delete_job(
        job.id,
        request_for(context["app"], f"/api/v1/jobs/{job.id}"),
        owner,
        session,
        context["settings"],
    )
    deleted_context_action = session.get(ExternalActionApproval, action.id)
    assert deleted_context_action is not None
    session.refresh(deleted_context_action)
    assert deleted_context_action.job_id is None
    assert deleted_context_action.status == "invalidated"


def test_smtp_adapter_requires_starttls_before_authentication(
    action_context: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 15

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ehlo(self):
            events.append("ehlo")

        def starttls(self, *, context):
            assert context is not None
            events.append("starttls")

        def login(self, username, password):
            assert username == "offerpilot"
            assert password == "secret-test-only"
            events.append("login")

        def send_message(self, message):
            assert message["To"] == "recruiter@example.com"
            assert message["Subject"] == "应聘"
            assert message.get_content().strip() == "邮件正文"
            events.append("send")

    monkeypatch.setattr(
        "app.services.external_actions.smtplib.SMTP",
        lambda *args, **kwargs: FakeSMTP(*args, **kwargs),
    )
    message = EmailMessage()
    message["To"] = "recruiter@example.com"
    message["Subject"] = "应聘"
    message.set_content("邮件正文")
    SMTPEmailActionHandler._send_message(action_context["settings"], message)
    assert events == ["ehlo", "starttls", "ehlo", "login", "send"]
