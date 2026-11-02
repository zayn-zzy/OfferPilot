"""Exercise real Alembic upgrades against an existing user database."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import inspect, text

from app.core.config import Settings
from app.db import create_session_factory
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    """Run the migration and API workflow using asyncio."""

    return "asyncio"


@pytest.mark.anyio
async def test_upgrade_existing_profile_database_preserves_data_and_enables_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade revision 0002 without losing accounts, profiles, or resume links."""

    backend_dir = Path(__file__).resolve().parents[1]
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'existing-user.db'}",
        secret_key="test-migration-secret-that-is-long-enough-for-testing",
        storage_dir=tmp_path / "private-storage",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    migration_config = Config(str(backend_dir / "alembic.ini"))
    migration_config.set_main_option("script_location", str(backend_dir / "migrations"))
    migration_config.set_main_option("prepend_sys_path", str(backend_dir))
    command.upgrade(migration_config, "20261030_0002")

    engine, factory = create_session_factory(settings)
    try:
        assert "job_postings" not in inspect(engine).get_table_names()
        app = create_app(settings, factory)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            credentials = {
                "email": "existing-user@example.com",
                "password": "correct-horse-battery",
            }
            registered = await client.post("/api/v1/auth/register", json=credentials)
            assert registered.status_code == 201
            original_user = registered.json()

            saved_profile = await client.put(
                "/api/v1/profile",
                json={
                    "graduation_year": 2027,
                    "education": "硕士",
                    "major": "计算机科学",
                    "target_roles": ["后端工程师"],
                    "target_cities": ["上海"],
                    "skills": ["Python", "SQL"],
                },
            )
            assert saved_profile.status_code == 200
            created_resume = await client.post(
                "/api/v1/resumes/text",
                json={"text": "升级前的简历：Python、SQL，求职目标后端工程师。"},
            )
            assert created_resume.status_code == 201
            resume_id = created_resume.json()["id"]
            confirmed_resume = await client.post(f"/api/v1/resumes/{resume_id}/confirm")
            assert confirmed_resume.status_code == 200

            missing_schema = await client.get("/api/v1/jobs")
            assert missing_schema.status_code == 503
            assert missing_schema.json()["code"] == "database_schema_outdated"
            assert "uv run alembic upgrade head" in missing_schema.json()["detail"]

            command.upgrade(migration_config, "head")
            assert {
                "companies",
                "job_postings",
                "applications",
                "application_status_events",
                "reminders",
                "notifications",
                "approval_requests",
                "application_prep_packs",
                "audit_events",
            }.issubset(inspect(engine).get_table_names())
            assert "timezone" in {
                column["name"] for column in inspect(engine).get_columns("users")
            }
            assert {
                "skill_id",
                "skill_version",
                "idempotency_key",
                "request_hash",
                "resume_version_id",
            }.issubset(
                {column["name"] for column in inspect(engine).get_columns("agent_runs")}
            )
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    ScriptDirectory.from_config(migration_config).get_current_head()
                )

            # Existing credentials and saved data must work after the upgrade.
            assert (await client.post("/api/v1/auth/logout")).status_code == 204
            logged_in = await client.post("/api/v1/auth/login", json=credentials)
            assert logged_in.status_code == 200
            assert logged_in.json() == original_user
            assert (await client.get("/api/v1/profile")).json() == saved_profile.json()
            assert (await client.get(f"/api/v1/resumes/{resume_id}")).json() == (
                confirmed_resume.json()
            )
            assert (await client.get("/health")).status_code == 200
            initial_jobs = await client.get("/api/v1/jobs")
            assert initial_jobs.status_code == 200
            assert initial_jobs.json() == []

            # Use the new tables and link an application to the pre-upgrade resume.
            payload = {
                "company_name": "迁移回归公司",
                "title": "后端工程师",
                "city": "上海",
                "source_url": "https://jobs.example/migration-regression",
            }
            created_job = await client.post("/api/v1/jobs", json=payload)
            assert created_job.status_code == 201
            job_id = created_job.json()["id"]
            payload["title"] = "平台后端工程师"
            edited_job = await client.put(f"/api/v1/jobs/{job_id}", json=payload)
            assert edited_job.status_code == 200
            read_job = await client.get(f"/api/v1/jobs/{job_id}")
            assert read_job.status_code == 200
            assert read_job.json()["title"] == payload["title"]

            added = await client.post(f"/api/v1/jobs/{job_id}/application")
            assert added.status_code == 201
            updated = await client.put(
                f"/api/v1/jobs/{job_id}/application",
                json={
                    "status": "applied",
                    "applied_at": "2026-10-31",
                    "resume_version_id": resume_id,
                    "notes": "使用升级前保存的简历",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["application"]["resume_version_id"] == resume_id
            tracked_jobs = await client.get("/api/v1/jobs?tracked=true&status=applied")
            assert tracked_jobs.status_code == 200
            assert [job["id"] for job in tracked_jobs.json()] == [job_id]
            history = await client.get(f"/api/v1/jobs/{job_id}/application/history")
            assert history.status_code == 200
            assert [event["to_status"] for event in history.json()] == [
                "to_research", "applied"
            ]

            assert (await client.delete(f"/api/v1/jobs/{job_id}")).status_code == 204
            assert (await client.get("/api/v1/jobs")).json() == []
            assert (await client.get("/api/v1/profile")).json() == saved_profile.json()
            assert (await client.get(f"/api/v1/resumes/{resume_id}")).json() == (
                confirmed_resume.json()
            )
    finally:
        engine.dispose()
