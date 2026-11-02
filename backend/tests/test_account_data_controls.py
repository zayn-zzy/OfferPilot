"""Account export and deletion tests using isolated SQLite and local files."""

import json
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings
from app.models import (
    AgentRun,
    Application,
    ApplicationStatusEvent,
    Base,
    CandidateProfile,
    Company,
    DocumentChunk,
    JobPosting,
    KnowledgeNote,
    Notification,
    Reminder,
    ResumeVersion,
    User,
    utc_now,
)
from app.routes import account as account_routes
from app.routes.account import (
    AccountDeleteRequest,
    _OWNED_MODELS,
    _create_export_archive,
    delete_account,
)


@pytest.fixture
def account_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        secret_key="account-test-secret",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
    )
    with factory() as session:
        owner = User(
            id=uuid4(),
            email="owner@example.com",
            password_hash="fixture-password-hash",
        )
        other = User(
            id=uuid4(),
            email="other@example.com",
            password_hash="other-fixture-password-hash",
        )
        session.add_all([owner, other])
        session.commit()
        session.refresh(owner)
        session.refresh(other)
        monkeypatch.setattr(
            account_routes,
            "verify_password",
            lambda password, stored_hash: (
                password == "correct-horse-battery" and stored_hash == "fixture-password-hash"
            ),
        )
        yield {"factory": factory, "settings": settings, "owner": owner, "other": other}
    engine.dispose()


def make_request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "headers": [(b"origin", b"http://localhost:3000")],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }
    )


def test_export_contains_owned_records_and_uploaded_original(account_context: dict) -> None:
    context = account_context
    owner = context["owner"]
    other = context["other"]
    settings = context["settings"]
    resume_id = uuid4()
    other_resume_id = uuid4()
    storage_key = f"{owner.id}/{resume_id}.pdf"
    file_path = settings.storage_dir / storage_key
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"%PDF-private-resume")
    with context["factory"]() as session:
        session.add_all(
            [
                ResumeVersion(
                    id=resume_id,
                    user_id=owner.id,
                    filename="my-resume.pdf",
                    source_type="upload",
                    content_type="application/pdf",
                    storage_key=storage_key,
                    extracted_text="简历正文",
                ),
                ResumeVersion(
                    id=other_resume_id,
                    user_id=other.id,
                    filename="other.pdf",
                    source_type="paste",
                    content_type="text/plain",
                    extracted_text="另一个用户的简历",
                ),
                KnowledgeNote(user_id=owner.id, title="项目笔记", content="负责检索系统"),
                KnowledgeNote(user_id=other.id, title="私有笔记", content="不应导出"),
                DocumentChunk(
                    user_id=owner.id,
                    source_type="note",
                    source_id=uuid4(),
                    source_name="项目笔记",
                    chunk_index=0,
                    content="负责检索系统",
                    embedding=[0.1, 0.2],
                    embedding_dimensions=2,
                    embedding_model="test-embedding",
                ),
            ]
        )
        session.commit()
        archive = _create_export_archive(owner, session, settings)
        archive_bytes = archive.read()
        archive.close()

    with zipfile.ZipFile(BytesIO(archive_bytes)) as bundle:
        manifest = json.loads(bundle.read("offerpilot-export.json"))
        assert bundle.read(f"resumes/{resume_id}_my-resume.pdf") == b"%PDF-private-resume"
        assert manifest["user"]["email"] == owner.email
        assert [row["filename"] for row in manifest["data"]["resume_versions"]] == ["my-resume.pdf"]
        assert [row["title"] for row in manifest["data"]["knowledge_notes"]] == ["项目笔记"]
        assert manifest["data"]["document_chunks"][0]["content"] == "负责检索系统"
        assert "embedding" not in manifest["data"]["document_chunks"][0]
        assert "password_hash" not in archive_bytes.decode("utf-8", errors="ignore")
        assert "不应导出" not in archive_bytes.decode("utf-8", errors="ignore")


def test_delete_requires_matching_email_and_password(account_context: dict) -> None:
    context = account_context
    owner = context["owner"]
    response = Response()
    with context["factory"]() as session:
        with pytest.raises(HTTPException) as wrong_email:
            delete_account(
                AccountDeleteRequest(
                    current_password=SecretStr("correct-horse-battery"),
                    confirmation_email="wrong@example.com",
                ),
                make_request("DELETE", "/api/v1/account/me"),
                response,
                owner,
                session,
                context["settings"],
            )
        assert wrong_email.value.status_code == 400
        with pytest.raises(HTTPException) as wrong_password:
            delete_account(
                AccountDeleteRequest(
                    current_password=SecretStr("incorrect-password"),
                    confirmation_email=owner.email,
                ),
                make_request("DELETE", "/api/v1/account/me"),
                response,
                owner,
                session,
                context["settings"],
            )
        assert wrong_password.value.status_code == 403
        assert session.get(User, owner.id) is not None


def test_delete_removes_account_records_indexes_files_and_cookie(account_context: dict) -> None:
    context = account_context
    owner = context["owner"]
    other = context["other"]
    settings = context["settings"]
    resume_id = uuid4()
    job_id = uuid4()
    application_id = uuid4()
    reminder_id = uuid4()
    storage_key = f"{owner.id}/{resume_id}.docx"
    resume_path = settings.storage_dir / storage_key
    resume_path.parent.mkdir(parents=True)
    resume_path.write_bytes(b"private-file")
    with context["factory"]() as session:
        company = Company(
            user_id=owner.id,
            name="示例公司",
            normalized_name="示例公司",
        )
        resume = ResumeVersion(
            id=resume_id,
            user_id=owner.id,
            filename="resume.docx",
            source_type="upload",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            storage_key=storage_key,
            extracted_text="私有简历文本",
        )
        session.add_all(
            [
                CandidateProfile(user_id=owner.id),
                company,
                resume,
                KnowledgeNote(user_id=owner.id, title="私有资料", content="待删除"),
                AgentRun(
                    user_id=owner.id,
                    task_type="job_extraction",
                    status="succeeded",
                    input_text="招聘原文",
                    events=[],
                ),
            ]
        )
        session.flush()
        job = JobPosting(
            id=job_id,
            user_id=owner.id,
            company_id=company.id,
            title="软件工程师",
            required_skills=[],
            source_type="manual",
            source_captured_at=utc_now(),
        )
        application = Application(
            id=application_id,
            user_id=owner.id,
            job_id=job.id,
            resume_version_id=resume.id,
            status="applied",
            applied_at=date.today(),
        )
        reminder = Reminder(
            id=reminder_id,
            user_id=owner.id,
            job_id=job.id,
            title="跟进",
            kind="follow_up",
            event_at=utc_now(),
            notify_at=utc_now(),
            timezone="Asia/Shanghai",
            idempotency_key="account-test-reminder",
            request_hash="test-hash",
        )
        session.add_all(
            [
                job,
                application,
                ApplicationStatusEvent(
                    user_id=owner.id,
                    application_id=application.id,
                    to_status="applied",
                ),
                reminder,
                Notification(
                    user_id=owner.id,
                    reminder_id=reminder.id,
                    title="跟进",
                    body="今天跟进",
                    idempotency_key="account-test-notification",
                ),
                DocumentChunk(
                    user_id=owner.id,
                    source_type="resume",
                    source_id=resume.id,
                    source_name="resume.docx",
                    chunk_index=0,
                    content="私有简历文本",
                    embedding=[0.1],
                    embedding_dimensions=1,
                    embedding_model="test-embedding",
                ),
            ]
        )
        session.commit()

    with context["factory"]() as session:
        response = Response()
        returned = delete_account(
            AccountDeleteRequest(
                current_password=SecretStr("correct-horse-battery"),
                confirmation_email=owner.email,
            ),
            make_request("DELETE", "/api/v1/account/me"),
            response,
            owner,
            session,
            settings,
        )
        assert returned.status_code == 204
        assert session.get(User, owner.id) is None
        assert session.get(User, other.id) is not None
        for model in _OWNED_MODELS:
            assert session.scalars(select(model).where(model.user_id == owner.id)).all() == []
        assert "offerpilot_session" in response.headers.get("set-cookie", "")
    assert not resume_path.parent.exists()
