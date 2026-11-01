"""Agent task lifecycle, evidence validation, and owner-isolated API tests."""

from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import create_app
from app.models import AgentRun, Base, JobSourceEvidence
from app.services.job_extraction import (
    ExtractedDateField,
    ExtractedSkillsField,
    ExtractedTextField,
    JobExtractionCandidate,
    JobExtractionError,
    OpenAICompatibleJobExtractionProvider,
)

SOURCE_TEXT = (
    "星河科技招聘后端开发工程师，工作地点上海，岗位类型校招，批次 2027 届秋招。"
    "截止日期：2026-11-30，学历要求本科及以上，技能要求 Python 和 SQL。"
)


def candidate(*, city_confidence: float = 0.9) -> JobExtractionCandidate:
    return JobExtractionCandidate(
        company_name=ExtractedTextField(value="星河科技", confidence=0.98, evidence="星河科技"),
        title=ExtractedTextField(value="后端开发工程师", confidence=0.95, evidence="后端开发工程师"),
        city=ExtractedTextField(value="上海", confidence=city_confidence, evidence="工作地点上海"),
        job_type=ExtractedTextField(value="校招", confidence=0.9, evidence="岗位类型校招"),
        batch=ExtractedTextField(value="2027 届秋招", confidence=0.88, evidence="2027 届秋招"),
        deadline=ExtractedDateField(
            value="2026-11-30", confidence=0.96, evidence="截止日期：2026-11-30"
        ),
        education_requirement=ExtractedTextField(
            value="本科及以上", confidence=0.91, evidence="学历要求本科及以上"
        ),
        required_skills=ExtractedSkillsField(
            value=["Python", "SQL"], confidence=0.9, evidence="Python 和 SQL"
        ),
    )


class FakeProvider:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    async def extract(self, source_text: str, settings: Settings):
        self.calls += 1
        if self.calls <= self.failures:
            raise JobExtractionError("provider_timeout", "模型服务响应超时，请重试。")
        return candidate(city_confidence=0.42), "test-model"


@pytest.fixture
def test_app(tmp_path: Path) -> Generator[FastAPI, None, None]:
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
        secret_key="agent-test-secret-that-is-long-enough-for-testing",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
    )
    app = create_app(settings, factory, job_extraction_provider=FakeProvider())
    yield app
    engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as test_client:
        yield test_client


async def register(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.anyio
async def test_extraction_task_streams_progress_and_confirms_source_evidence(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "agent-owner@example.com")
    created = await client.post(
        "/api/v1/agent/job-extractions",
        json={"text": SOURCE_TEXT, "source_url": "https://jobs.example/xinghe/backend"},
    )

    assert created.status_code == 202
    initial = created.json()
    assert initial["status"] == "queued"
    assert "input_text" not in initial
    task_id = initial["id"]

    task = await client.get(f"/api/v1/agent/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["status"] == "succeeded"
    assert task.json()["attempt_count"] == 1
    assert task.json()["result"]["needs_review_fields"] == ["city"]
    assert task.json()["model_name"] == "test-model"

    stream = await client.get(f"/api/v1/agent/tasks/{task_id}/events")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: completed" in stream.text
    assert "字段已完成结构校验" in stream.text
    resumed_stream = await client.get(
        f"/api/v1/agent/tasks/{task_id}/events", headers={"Last-Event-ID": "3"}
    )
    assert "id: 3\n" not in resumed_stream.text
    assert "event: completed" in resumed_stream.text

    source = await client.get(f"/api/v1/agent/tasks/{task_id}/source")
    assert source.status_code == 200
    assert source.json()["source_text"] == SOURCE_TEXT

    invalid_source = await client.post(
        f"/api/v1/agent/tasks/{task_id}/confirm",
        json={"source_url": "javascript:alert(1)"},
    )
    assert invalid_source.status_code == 422

    saved = await client.post(
        f"/api/v1/agent/tasks/{task_id}/confirm",
        json={"city": "上海市"},
    )
    assert saved.status_code == 201
    job = saved.json()
    assert job["company_name"] == "星河科技"
    assert job["title"] == "后端开发工程师"
    assert job["city"] == "上海市"
    assert job["description"] == SOURCE_TEXT
    assert job["source_type"] == "agent"

    evidence = await client.get(f"/api/v1/agent/jobs/{job['id']}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()["source_text"] == SOURCE_TEXT
    assert evidence.json()["field_evidence"]["title"]["evidence"] == "后端开发工程师"
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}/source")).status_code == 409
    confirmed_task = await client.get(f"/api/v1/agent/tasks/{task_id}")
    assert confirmed_task.json()["status"] == "confirmed"
    assert confirmed_task.json()["job_id"] == job["id"]
    assert (await client.delete(f"/api/v1/agent/tasks/{task_id}")).status_code == 409

    # Confirmation is idempotent and does not create a second job/evidence row.
    again = await client.post(f"/api/v1/agent/tasks/{task_id}/confirm", json={})
    assert again.status_code == 201
    assert again.json()["id"] == job["id"]
    jobs = await client.get("/api/v1/jobs")
    assert len(jobs.json()) == 1
    with test_app.state.session_factory() as session:
        rows = session.scalars(select(JobSourceEvidence)).all()
        assert len(rows) == 1
        run = session.get(AgentRun, UUID(task_id))
        assert run is not None and run.input_text == ""

    # Removing the saved job also removes its source text/evidence and linked run.
    assert (await client.delete(f"/api/v1/jobs/{job['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/agent/jobs/{job['id']}/evidence")).status_code == 404
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}")).status_code == 404


@pytest.mark.anyio
async def test_failed_extraction_can_retry_and_stops_after_three_attempts(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "agent-retry@example.com")
    provider = FakeProvider(failures=3)
    test_app.state.job_extraction_provider = provider
    created = await client.post("/api/v1/agent/job-extractions", json={"text": SOURCE_TEXT})
    task_id = created.json()["id"]
    failed = await client.get(f"/api/v1/agent/tasks/{task_id}")
    assert failed.json()["status"] == "failed"
    assert failed.json()["attempt_count"] == 1
    assert failed.json()["error_code"] == "provider_timeout"

    second = await client.post(f"/api/v1/agent/tasks/{task_id}/retry")
    assert second.status_code == 202
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}")).json()["attempt_count"] == 2
    third = await client.post(f"/api/v1/agent/tasks/{task_id}/retry")
    assert third.status_code == 202
    final = await client.get(f"/api/v1/agent/tasks/{task_id}")
    assert final.json()["attempt_count"] == 3
    assert final.json()["status"] == "failed"
    assert (await client.post(f"/api/v1/agent/tasks/{task_id}/retry")).status_code == 409


@pytest.mark.anyio
async def test_agent_tasks_and_source_evidence_are_isolated_between_users(
    client: AsyncClient,
) -> None:
    await register(client, "agent-first@example.com")
    created = await client.post("/api/v1/agent/job-extractions", json={"text": SOURCE_TEXT})
    task_id = created.json()["id"]
    job = await client.post(f"/api/v1/agent/tasks/{task_id}/confirm", json={})
    job_id = job.json()["id"]

    await client.post("/api/v1/auth/logout")
    await register(client, "agent-second@example.com")
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}")).status_code == 404
    assert (await client.get(f"/api/v1/agent/jobs/{job_id}/evidence")).status_code == 404
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}/source")).status_code == 404


@pytest.mark.anyio
async def test_agent_mutations_require_same_origin_and_valid_source_text(
    client: AsyncClient,
) -> None:
    await register(client, "agent-origin@example.com")
    bad_origin = await client.post(
        "/api/v1/agent/job-extractions",
        headers={"Origin": "https://attacker.example"},
        json={"text": SOURCE_TEXT},
    )
    short_text = await client.post(
        "/api/v1/agent/job-extractions", json={"text": "太短"}
    )
    assert bad_origin.status_code == 403
    assert short_text.status_code == 422


@pytest.mark.anyio
async def test_failed_task_can_be_deleted_to_remove_retained_source_text(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "agent-delete@example.com")
    test_app.state.job_extraction_provider = FakeProvider(failures=1)
    created = await client.post("/api/v1/agent/job-extractions", json={"text": SOURCE_TEXT})
    task_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/agent/tasks/{task_id}")

    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}")).status_code == 404
    assert (await client.get(f"/api/v1/agent/tasks/{task_id}/source")).status_code == 404


@pytest.mark.anyio
async def test_provider_adapter_validates_json_and_removes_unsupported_quotes() -> None:
    output = candidate().model_dump(mode="json")
    output["company_name"]["evidence"] = "不是来自原文"

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-api-key"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][1]["content"] == SOURCE_TEXT
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    provider = OpenAICompatibleJobExtractionProvider(transport=httpx.MockTransport(respond))
    settings = Settings(
        _env_file=None,
        llm_base_url="https://model.example/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )
    result, model_name = await provider.extract(SOURCE_TEXT, settings)
    assert model_name == "test-model"
    assert result.company_name.confidence == 0
    assert result.company_name.evidence is None
    assert result.title.confidence == 0.95


@pytest.mark.anyio
async def test_provider_adapter_fails_clearly_when_not_configured() -> None:
    provider = OpenAICompatibleJobExtractionProvider()
    with pytest.raises(JobExtractionError) as error:
        await provider.extract(
            SOURCE_TEXT,
            Settings(
                _env_file=None,
                llm_base_url="",
                llm_api_key="",
                llm_model="",
            ),
        )
    assert error.value.code == "provider_not_configured"
    assert "OFFERPILOT_LLM_API_KEY" in error.value.message
