"""Owner-scoped duplicate-source merge behavior."""

import csv
from collections.abc import Generator
from io import BytesIO, StringIO

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.core.config import Settings
from app.models import (
    AgentRun,
    Application,
    ApplicationStatusEvent,
    Base,
    JobSourceEvidence,
    User,
)
from app.routes.agent import confirm_job_extraction
from app.routes.jobs import create_job, merge_job_into_existing, preview_job_csv
from app.schemas import JobExtractionConfirm, JobPostingWrite
from app.services.job_csv import CSV_HEADERS


@pytest.fixture
def merge_context() -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite://",
        secret_key="duplicate-merge-test-secret-long-enough",
        allowed_origins=["http://localhost:3000"],
    )
    with factory() as session:
        owner = User(
            email="merge-owner@example.com",
            password_hash="unused",
            timezone="Asia/Shanghai",
        )
        other = User(
            email="merge-other@example.com",
            password_hash="unused",
            timezone="Asia/Tokyo",
        )
        session.add_all([owner, other])
        session.commit()
        session.refresh(owner)
        session.refresh(other)
        owner_id, other_id = owner.id, other.id
    yield {
        "factory": factory,
        "owner_id": owner_id,
        "other_id": other_id,
        "settings": settings,
        "app": FastAPI(),
    }
    engine.dispose()


def request_for(context: dict[str, object], path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"origin", b"http://localhost:3000")],
            "query_string": b"",
            "scheme": "http",
            "app": context["app"],
        }
    )


def payload(**overrides: object) -> JobPostingWrite:
    values: dict[str, object] = {
        "company_name": "星河科技",
        "title": "后端工程师",
        "city": None,
        "job_type": "校招",
        "batch": "2027 届",
        "deadline": None,
        "education_requirement": None,
        "required_skills": ["Python"],
        "description": "已有岗位描述",
        "source_url": "https://jobs.example/role",
        "source_type": "link",
        "tags": ["重点"],
    }
    values.update(overrides)
    return JobPostingWrite(**values)


def create_target(context: dict[str, object], session: Session, owner: User):
    return create_job(
        payload(company_notes="已有公司备注"),
        request_for(context, "/api/v1/jobs"),
        owner,
        session,
        context["settings"],
    )


def test_manual_duplicate_offers_owner_scoped_merge_and_keeps_application_history(
    merge_context: dict[str, object],
) -> None:
    factory = merge_context["factory"]
    with factory() as session:
        owner = session.get(User, merge_context["owner_id"])
        other = session.get(User, merge_context["other_id"])
        assert owner is not None and other is not None
        existing = create_target(merge_context, session, owner)
        job_id = existing.id
        application = Application(
            user_id=owner.id,
            job_id=job_id,
            status="interview",
            notes="一面已完成",
        )
        session.add(application)
        session.flush()
        history = ApplicationStatusEvent(
            user_id=owner.id,
            application_id=application.id,
            from_status="applied",
            to_status="interview",
        )
        session.add(history)
        session.commit()

        with pytest.raises(HTTPException) as conflict:
            create_job(
                payload(
                    source_url="https://JOBS.example/role/#details",
                    title="新的职位名称",
                    city="上海",
                    required_skills=["SQL"],
                    tags=["秋招"],
                ),
                request_for(merge_context, "/api/v1/jobs"),
                owner,
                session,
                merge_context["settings"],
            )
        assert conflict.value.status_code == 409
        assert conflict.value.detail["code"] == "duplicate_job_source"
        assert conflict.value.detail["existing_job_id"] == str(job_id)

        merged = merge_job_into_existing(
            job_id,
            payload(
                source_url="https://JOBS.example/role/#details",
                title="新的职位名称",
                city="上海",
                required_skills=["SQL", "python"],
                tags=["秋招", "重点"],
                company_notes="尝试覆盖备注",
            ),
            request_for(merge_context, f"/api/v1/jobs/{job_id}/merge"),
            owner,
            session,
            merge_context["settings"],
        )
        assert merged.id == job_id
        assert merged.title == "后端工程师"  # Existing non-empty values win.
        assert merged.city == "上海"  # Missing values are filled.
        assert merged.required_skills == ["Python", "SQL"]
        assert merged.tags == ["重点", "秋招"]
        assert merged.company_notes == "已有公司备注"
        assert merged.review_status == "verified"
        assert merged.application is not None
        assert merged.application.status == "interview"
        assert merged.application.notes == "一面已完成"
        events = session.scalars(
            select(ApplicationStatusEvent).where(
                ApplicationStatusEvent.application_id == application.id
            )
        ).all()
        assert len(events) == 1

        with pytest.raises(HTTPException) as foreign_owner:
            merge_job_into_existing(
                job_id,
                payload(),
                request_for(merge_context, f"/api/v1/jobs/{job_id}/merge"),
                other,
                session,
                merge_context["settings"],
            )
        assert foreign_owner.value.status_code == 404


def test_csv_preview_identifies_database_and_file_duplicates(
    merge_context: dict[str, object],
) -> None:
    factory = merge_context["factory"]
    with factory() as session:
        owner = session.get(User, merge_context["owner_id"])
        assert owner is not None
        existing = create_target(merge_context, session, owner)
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerow({"公司名称": "已存在公司", "职位名称": "已存在岗位", "岗位来源": existing.source_url})
        writer.writerow({"公司名称": "导入公司", "职位名称": "主岗位", "岗位来源": "https://jobs.example/new"})
        writer.writerow({"城市": "上海", "技能要求": "Python，SQL", "岗位来源": "https://jobs.example/new/"})
        upload = UploadFile(
            filename="jobs.csv",
            file=BytesIO(output.getvalue().encode("utf-8-sig")),
        )

        preview = preview_job_csv(
            request_for(merge_context, "/api/v1/jobs/import/preview"),
            upload,
            owner,
            session,
            merge_context["settings"],
        )
        assert preview.duplicate_count == 2
        assert preview.rows[0].duplicate_job_id == existing.id
        assert preview.rows[0].duplicate_job_company_name == "星河科技"
        assert preview.rows[0].duplicate_job_title == "后端工程师"
        assert preview.rows[2].duplicate_of_row_number == 3
        assert "重复" in preview.rows[2].duplicate_detail


def test_ai_confirmation_can_merge_citations_into_existing_job(
    merge_context: dict[str, object],
) -> None:
    factory = merge_context["factory"]
    with factory() as session:
        owner = session.get(User, merge_context["owner_id"])
        assert owner is not None
        existing = create_target(merge_context, session, owner)
        run = AgentRun(
            user_id=owner.id,
            task_type="job_extraction",
            status="succeeded",
            input_text="星河科技招聘后端工程师，工作地点上海，要求 Python 与 SQL。",
            source_url="https://JOBS.example/role/#requirements",
            result={
                "fields": {
                    "company_name": {"value": "星河科技", "confidence": 0.9, "evidence": "星河科技"},
                    "title": {"value": "后端工程师", "confidence": 0.9, "evidence": "后端工程师"},
                    "city": {"value": "上海", "confidence": 0.9, "evidence": "工作地点上海"},
                    "job_type": {"value": "校招", "confidence": 0.9, "evidence": "校招"},
                    "batch": {"value": None, "confidence": 0, "evidence": None},
                    "deadline": {"value": None, "confidence": 0, "evidence": None},
                    "education_requirement": {"value": None, "confidence": 0, "evidence": None},
                    "required_skills": {"value": ["Python", "SQL"], "confidence": 0.9, "evidence": "Python 与 SQL"},
                }
            },
            events=[],
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        merged = confirm_job_extraction(
            run.id,
            JobExtractionConfirm(
                city="上海",
                required_skills=["Python", "SQL"],
                merge_into_job_id=existing.id,
            ),
            request_for(merge_context, f"/api/v1/agent/tasks/{run.id}/confirm"),
            owner,
            session,
            merge_context["settings"],
        )
        stored_run = session.get(AgentRun, run.id)
        evidence = session.scalar(
            select(JobSourceEvidence).where(JobSourceEvidence.agent_run_id == run.id)
        )
        assert merged.id == existing.id
        assert merged.city == "上海"
        assert stored_run is not None and stored_run.status == "confirmed"
        assert stored_run.job_id == existing.id
        assert stored_run.input_text == ""
        assert evidence is not None and evidence.job_id == existing.id


def test_merge_rejects_nonmatching_source_url(merge_context: dict[str, object]) -> None:
    factory = merge_context["factory"]
    with factory() as session:
        owner = session.get(User, merge_context["owner_id"])
        assert owner is not None
        existing = create_target(merge_context, session, owner)
        with pytest.raises(HTTPException) as conflict:
            merge_job_into_existing(
                existing.id,
                payload(source_url="https://jobs.example/another-role"),
                request_for(merge_context, f"/api/v1/jobs/{existing.id}/merge"),
                owner,
                session,
                merge_context["settings"],
            )
        assert conflict.value.status_code == 409
