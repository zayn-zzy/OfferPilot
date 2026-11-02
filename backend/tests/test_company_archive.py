"""Company archive aggregation and owner-isolation tests without external services."""

from collections.abc import Generator
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AgentRun, Application, Base, Company, JobPosting, User, utc_now
from app.routes.companies import get_company_archive, list_company_archives


@pytest.fixture
def archive_database(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker[Session], User, User, Company, Company], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    owner = User(
        id=uuid4(), email="archive-owner@example.com", password_hash="test-hash"
    )
    other = User(
        id=uuid4(), email="archive-other@example.com", password_hash="test-hash"
    )
    owner_company = Company(
        id=uuid4(),
        user_id=owner.id,
        name="星河科技",
        normalized_name="星河科技",
        industry="云服务",
        website_url="https://company.example",
        recruitment_url="https://company.example/careers",
        notes="我在宣讲会上了解到该公司重视基础架构。",
    )
    other_company = Company(
        id=uuid4(),
        user_id=other.id,
        name="星河科技",
        normalized_name="星河科技",
    )
    job = JobPosting(
        id=uuid4(),
        user_id=owner.id,
        company_id=owner_company.id,
        title="后端开发工程师",
        city="上海",
        job_type="校招",
        batch="2027 届秋招",
        deadline=date(2026, 12, 1),
        required_skills=["Python"],
        source_type="manual",
        source_captured_at=utc_now(),
    )
    other_job = JobPosting(
        id=uuid4(),
        user_id=other.id,
        company_id=other_company.id,
        title="算法工程师",
        required_skills=[],
        source_type="manual",
        source_captured_at=utc_now(),
    )
    application = Application(
        id=uuid4(), user_id=owner.id, job_id=job.id, status="assessment"
    )
    research = AgentRun(
        id=uuid4(),
        user_id=owner.id,
        job_id=job.id,
        task_type="company_research",
        status="succeeded",
        input_text='"星河科技" 招聘 校招 后端开发工程师',
        result={
            "company_name": "星河科技",
            "job_title": "后端开发工程师",
            "query": '"星河科技" 招聘 校招 后端开发工程师',
            "researched_at": (utc_now() - timedelta(days=8)).isoformat(),
            "summary": "搜索来源提到 2027 届校招已启动。",
            "findings": [
                {
                    "claim": "搜索来源提到 2027 届校招已启动。",
                    "source_id": "web-1",
                    "quote": "星河科技 2027 届校园招聘已启动。",
                }
            ],
            "sources": [
                {
                    "source_id": "web-1",
                    "title": "星河科技校园招聘",
                    "url": "https://company.example/campus",
                    "excerpt": "星河科技 2027 届校园招聘已启动。",
                    "age": "8 days ago",
                }
            ],
            "no_evidence": False,
            "warning": None,
        },
        events=[],
        created_at=utc_now() - timedelta(days=8),
        finished_at=utc_now() - timedelta(days=8),
    )
    previous_research = AgentRun(
        id=uuid4(),
        user_id=owner.id,
        job_id=job.id,
        task_type="company_research",
        status="succeeded",
        input_text='"星河科技" 招聘',
        result={
            "company_name": "星河科技",
            "job_title": "后端开发工程师",
            "researched_at": (utc_now() - timedelta(days=20)).isoformat(),
            "summary": "旧研究结果。",
            "findings": [],
            "sources": [],
            "no_evidence": True,
        },
        events=[],
        created_at=utc_now() - timedelta(days=20),
        finished_at=utc_now() - timedelta(days=20),
    )
    with factory() as session:
        session.add_all([owner, other, owner_company, other_company, job, other_job])
        session.flush()
        session.add_all([application, previous_research, research])
        session.commit()
    yield factory, owner, other, owner_company, other_company
    engine.dispose()


def test_company_archive_groups_jobs_notes_and_cited_research(
    archive_database: tuple[sessionmaker[Session], User, User, Company, Company],
) -> None:
    factory, owner, _, company, _ = archive_database
    with factory() as session:
        archives = list_company_archives(owner, session)
        assert len(archives) == 1
        archive = archives[0]
        assert archive.id == company.id
        assert archive.batches == ["2027 届秋招"]
        assert archive.notes == "我在宣讲会上了解到该公司重视基础架构。"
        assert archive.jobs[0].application_status == "assessment"
        assert archive.jobs[0].research_is_stale is True
        assert archive.stale_research_count == 1
        assert archive.research_count == 1
        assert archive.source_count == 1
        assert archive.no_evidence is False
        assert archive.findings[0].claim == "搜索来源提到 2027 届校招已启动。"
        assert archive.findings[0].quote in archive.sources[0].excerpt
        assert archive.sources[0].url == "https://company.example/campus"
        assert "1 条带来源引用" in archive.research_summary


def test_company_archive_is_owner_scoped_and_handles_no_research(
    archive_database: tuple[sessionmaker[Session], User, User, Company, Company],
) -> None:
    factory, owner, _, company, other_company = archive_database
    with factory() as session:
        with pytest.raises(HTTPException) as error:
            get_company_archive(other_company.id, owner, session)
        assert error.value.status_code == 404

    with factory() as session:
        owner_company_without_research = Company(
            id=uuid4(),
            user_id=owner.id,
            name="新公司",
            normalized_name="新公司",
        )
        session.add(owner_company_without_research)
        session.commit()
        archive = get_company_archive(owner_company_without_research.id, owner, session)
        assert archive.research_count == 0
        assert archive.no_evidence is True
        assert archive.sources == []
        assert "尚无已保存" in archive.research_summary
