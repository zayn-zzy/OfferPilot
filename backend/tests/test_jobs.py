"""Job posting and application-board API tests using isolated SQLite storage."""

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture
def test_app(tmp_path: Path) -> Generator[FastAPI, None, None]:
    """Create an API with fresh tables and private file storage for each test."""

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
        secret_key="test-secret-key-that-is-long-enough-for-testing",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
    )
    yield create_app(settings, factory)
    engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Run API tests with the asyncio backend."""

    return "asyncio"


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create a cookie-preserving in-process client."""

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as test_client:
        yield test_client


async def register(client: AsyncClient, email: str) -> str:
    """Register and authenticate a user, returning its identifier."""

    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def job_payload(**overrides: object) -> dict[str, object]:
    """Return a valid, representative manually entered job."""

    payload: dict[str, object] = {
        "company_name": "星河科技",
        "company_website_url": "https://xinghe.example",
        "recruitment_url": "https://xinghe.example/careers",
        "industry": "互联网",
        "company_notes": "关注基础架构团队",
        "title": "后端开发工程师",
        "city": "上海",
        "job_type": "校招",
        "batch": "2027 届秋招",
        "deadline": "2026-11-30",
        "education_requirement": "本科及以上",
        "required_skills": [" Python ", "python", "SQL"],
        "description": "负责服务端系统开发与维护。",
        "source_url": "https://jobs.example/xinghe/backend/",
        "source_type": "link",
        "tags": ["重点关注", " 上海 ", "重点关注"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_jobs_require_authentication(client: AsyncClient) -> None:
    """Job records are only available to authenticated users."""

    response = await client.get("/api/v1/jobs")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_create_partial_job_records_source_and_normalizes_lists(client: AsyncClient) -> None:
    """Incomplete source-backed jobs can be saved for later verification."""

    await register(client, "jobs@example.com")
    response = await client.post(
        "/api/v1/jobs",
        json={
            "source_url": "https://jobs.example/unknown",
            "description": "某公司招聘后端工程师，地点待确认。",
            "source_type": "paste",
            "required_skills": [" Python ", "python", "SQL"],
            "tags": [" 待确认 ", "待确认"],
        },
    )

    assert response.status_code == 201
    job = response.json()
    assert job["company_name"] is None
    assert job["title"] is None
    assert job["review_status"] == "needs_review"
    assert job["source_type"] == "paste"
    assert job["source_captured_at"]
    assert job["required_skills"] == ["Python", "SQL"]
    assert job["tags"] == ["待确认"]


@pytest.mark.anyio
async def test_duplicate_source_url_is_rejected_with_actionable_hint(client: AsyncClient) -> None:
    """Fragments and host casing do not permit duplicate source records."""

    await register(client, "duplicate@example.com")
    first = await client.post(
        "/api/v1/jobs",
        json=job_payload(source_url="https://jobs.example/xinghe/backend/#requirements"),
    )
    duplicate = await client.post(
        "/api/v1/jobs",
        json=job_payload(source_url="https://JOBS.example/xinghe/backend/"),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert "编辑已有岗位" in duplicate.json()["detail"]


@pytest.mark.anyio
async def test_company_details_are_reused_when_adding_another_job(client: AsyncClient) -> None:
    """A second job with blank company fields does not erase saved company data."""

    await register(client, "company@example.com")
    await client.post("/api/v1/jobs", json=job_payload())
    second = await client.post(
        "/api/v1/jobs",
        json=job_payload(
            title="平台研发工程师",
            source_url="https://jobs.example/xinghe/platform",
            company_website_url=None,
            recruitment_url=None,
            industry=None,
            company_notes=None,
        ),
    )

    assert second.status_code == 201
    assert second.json()["company_website_url"] == "https://xinghe.example"
    assert second.json()["recruitment_url"] == "https://xinghe.example/careers"
    assert second.json()["industry"] == "互联网"
    assert second.json()["company_notes"] == "关注基础架构团队"


@pytest.mark.anyio
async def test_job_and_company_data_are_isolated_between_users(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    """Another user cannot list or read a saved job by its identifier."""

    await register(client, "owner@example.com")
    created = await client.post("/api/v1/jobs", json=job_payload())
    other_client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver")
    await register(other_client, "other@example.com")

    other_list = await other_client.get("/api/v1/jobs")
    other_detail = await other_client.get(f"/api/v1/jobs/{created.json()['id']}")
    await other_client.aclose()

    assert created.status_code == 201
    assert other_list.status_code == 200
    assert other_list.json() == []
    assert other_detail.status_code == 404


@pytest.mark.anyio
async def test_board_tracks_stage_changes_details_and_history(client: AsyncClient) -> None:
    """Tracking records start in the first stage and append each actual change."""

    await register(client, "board@example.com")
    created = await client.post("/api/v1/jobs", json=job_payload())
    job_id = created.json()["id"]
    tracked = await client.post(f"/api/v1/jobs/{job_id}/application")
    repeated = await client.post(f"/api/v1/jobs/{job_id}/application")

    assert tracked.status_code == 201
    assert tracked.json()["application"]["status"] == "to_research"
    assert repeated.status_code == 409

    updated = await client.put(
        f"/api/v1/jobs/{job_id}/application",
        json={
            "status": "applied",
            "applied_at": "2026-10-31",
            "notes": "内推，已提交简历",
            "next_action": "关注测评通知",
            "next_action_due": "2026-11-02",
        },
    )
    history = await client.get(f"/api/v1/jobs/{job_id}/application/history")
    board = await client.get("/api/v1/jobs?tracked=true&status=applied")

    assert updated.status_code == 200
    assert updated.json()["application"]["notes"] == "内推，已提交简历"
    assert updated.json()["application"]["next_action_due"] == "2026-11-02"
    assert [event["to_status"] for event in history.json()] == ["to_research", "applied"]
    assert history.json()[1]["from_status"] == "to_research"
    assert len(board.json()) == 1


@pytest.mark.anyio
async def test_job_filters_cover_city_tag_deadline_and_untracked(client: AsyncClient) -> None:
    """Structured filters work without any model or external search service."""

    await register(client, "filters@example.com")
    await client.post("/api/v1/jobs", json=job_payload())
    await client.post(
        "/api/v1/jobs",
        json=job_payload(
            company_name="海风实验室",
            title="算法工程师",
            city="杭州",
            industry="人工智能",
            deadline="2026-12-15",
            source_url="https://jobs.example/haifeng/algorithm",
            tags=["备选"],
        ),
    )

    city = await client.get("/api/v1/jobs?city=上海")
    tag = await client.get("/api/v1/jobs?tag=%E9%87%8D%E7%82%B9%E5%85%B3%E6%B3%A8")
    before_deadline = await client.get("/api/v1/jobs?deadline_before=2026-12-01")
    untracked = await client.get("/api/v1/jobs?status=untracked")

    assert len(city.json()) == 1
    assert city.json()[0]["company_name"] == "星河科技"
    assert len(tag.json()) == 1
    assert len(before_deadline.json()) == 1
    assert len(untracked.json()) == 2


@pytest.mark.anyio
async def test_incomplete_job_needs_company_and_title_before_verification(
    client: AsyncClient,
) -> None:
    """The owner can complete a partial record and explicitly verify it."""

    await register(client, "review@example.com")
    partial = await client.post(
        "/api/v1/jobs",
        json={"description": "待核验的招聘描述"},
    )
    job_id = partial.json()["id"]
    early_verify = await client.post(f"/api/v1/jobs/{job_id}/verify")
    completed = await client.put(
        f"/api/v1/jobs/{job_id}",
        json=job_payload(source_url=None),
    )
    verified = await client.post(f"/api/v1/jobs/{job_id}/verify")

    assert early_verify.status_code == 409
    assert completed.status_code == 200
    assert verified.status_code == 200
    assert verified.json()["review_status"] == "verified"


@pytest.mark.anyio
async def test_resume_for_another_user_cannot_be_attached_to_application(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    """Application records cannot reference private resume data owned by others."""

    await register(client, "resume-owner@example.com")
    job = await client.post("/api/v1/jobs", json=job_payload())
    await client.post(f"/api/v1/jobs/{job.json()['id']}/application")

    other_client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver")
    await register(other_client, "resume-other@example.com")
    resume = await other_client.post("/api/v1/resumes/text", json={"text": "他人的简历内容"})
    await other_client.aclose()
    response = await client.put(
        f"/api/v1/jobs/{job.json()['id']}/application",
        json={"resume_version_id": resume.json()["id"]},
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_job_query_with_missing_column_returns_migration_hint(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    """A partially upgraded database gives an actionable error without leaking SQL."""

    await register(client, "missing-column@example.com")
    with test_app.state.session_factory() as session:
        session.execute(text("ALTER TABLE job_postings DROP COLUMN source_type"))
        session.commit()

    response = await client.get("/api/v1/jobs")

    assert response.status_code == 503
    assert response.json()["code"] == "database_schema_outdated"
    assert "uv run alembic upgrade head" in response.json()["detail"]
    assert "SELECT" not in response.text


@pytest.mark.anyio
async def test_other_database_errors_do_not_report_missing_migrations(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    """Unrelated SQL failures keep a generic error and do not leak the statement."""

    @test_app.get("/test/database-failure")
    def trigger_database_failure() -> dict[str, str]:
        with test_app.state.session_factory() as session:
            session.execute(text("SELECT unavailable_database_function()"))
        return {"status": "ok"}

    response = await client.get("/test/database-failure")

    assert response.status_code == 500
    assert response.json() == {"detail": "Database request failed"}
    assert "unavailable_database_function" not in response.text
