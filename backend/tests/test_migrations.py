"""Exercise real Alembic upgrades against an existing user database."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import MetaData, Table, inspect, text

from app.core.config import Settings
from app.core.security import hash_password
from app.db import create_session_factory
from app.main import create_app
from app.models import CandidateProfile, ResumeVersion, User, utc_now


@pytest.mark.anyio
async def test_upgrade_existing_profile_database_preserves_data_and_enables_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade revision 0002 without losing accounts, profiles, or resume links."""

    backend_dir = Path(__file__).resolve().parents[1]
    settings = Settings(
        _env_file=None,
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
        credentials = {
            "email": "existing-user@example.com",
            "password": "correct-horse-battery",
        }
        user_id = uuid4()
        resume_id = uuid4()
        timestamp = utc_now()
        resume_text = "升级前的简历：Python、SQL，求职目标后端工程师。"
        legacy_users = Table("users", MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            # Seed rows using only columns present at revision 0002. The current ORM
            # includes later columns, so current API writes must wait until migration.
            connection.execute(
                legacy_users.insert().values(
                    id=user_id.hex,
                    email=credentials["email"],
                    password_hash=hash_password(credentials["password"]),
                    created_at=timestamp,
                )
            )
            connection.execute(
                CandidateProfile.__table__.insert().values(
                    id=uuid4(),
                    user_id=user_id,
                    graduation_year=2027,
                    education="硕士",
                    major="计算机科学",
                    target_roles=["后端工程师"],
                    target_cities=["上海"],
                    industries=[],
                    skills=["Python", "SQL"],
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            connection.execute(
                ResumeVersion.__table__.insert().values(
                    id=resume_id,
                    user_id=user_id,
                    filename="pasted-resume.txt",
                    source_type="text",
                    content_type="text/plain",
                    storage_key=None,
                    extracted_text=resume_text,
                    confirmed_at=timestamp,
                    created_at=timestamp,
                )
            )

        app = create_app(settings, factory)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            missing_schema = await client.get("/health")
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
                "external_action_approvals",
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
            logged_in = await client.post("/api/v1/auth/login", json=credentials)
            assert logged_in.status_code == 200
            assert logged_in.json()["id"] == str(user_id)
            saved_profile = await client.get("/api/v1/profile")
            assert saved_profile.status_code == 200
            assert saved_profile.json()["graduation_year"] == 2027
            assert saved_profile.json()["target_roles"] == ["后端工程师"]
            confirmed_resume = await client.get(f"/api/v1/resumes/{resume_id}")
            assert confirmed_resume.status_code == 200
            assert confirmed_resume.json()["extracted_text"] == resume_text
            assert confirmed_resume.json()["confirmed_at"] is not None
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
                    "resume_version_id": str(resume_id),
                    "notes": "使用升级前保存的简历",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["application"]["resume_version_id"] == str(resume_id)
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
