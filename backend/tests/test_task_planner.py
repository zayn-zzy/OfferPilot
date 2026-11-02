"""Task-plan parsing, durable preview, explicit confirmation, and retry tests."""

import json
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import Settings
from app.models import AgentRun, Base, Reminder, User
from app.routes.agent import confirm_task_plan, run_task_plan
from app.services.task_planner import (
    OpenAICompatibleTaskPlanner,
    TaskPlanCandidate,
    TaskPlannerError,
    normalize_candidate_time,
)


class StaticPlanner:
    def __init__(self, *, clarification: bool = False, fail_once: bool = False) -> None:
        self.clarification = clarification
        self.fail_once = fail_once
        self.calls = 0

    async def plan(self, text, timezone_name, now, settings):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise TaskPlannerError("provider_timeout", "模型服务响应超时，请重试。")
        if self.clarification:
            return TaskPlanCandidate(
                needs_clarification=True,
                clarification_question="请补充具体日期。",
            ), "test-model"
        return TaskPlanCandidate(
            title="跟进测评",
            details="检查测评邮件",
            kind="assessment",
            event_at="2030-11-11T09:00:00",
            company_name="星河科技",
            job_title="后端开发工程师",
        ), "test-model"


@pytest.fixture
def task_plan_database(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker[Session], Settings], None, None]:
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
        secret_key="task-planner-test-secret-that-is-long-enough",
        storage_dir=tmp_path / "storage",
    )
    yield factory, settings
    engine.dispose()


def create_task(factory: sessionmaker[Session]) -> tuple[UUID, UUID]:
    user = User(
        id=uuid4(),
        email=f"planner-{uuid4()}@example.com",
        password_hash="test-hash",
        timezone="Asia/Shanghai",
    )
    run = AgentRun(
        id=uuid4(),
        user_id=user.id,
        task_type="task_plan",
        status="queued",
        input_text="下周三前跟进星河科技的测评",
        events=[],
    )
    with factory() as session:
        session.add_all([user, run])
        session.commit()
        return user.id, run.id


def request_without_origin(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1234),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.anyio
async def test_task_plan_is_durable_and_reminder_requires_confirmation(
    task_plan_database: tuple[sessionmaker[Session], Settings],
) -> None:
    factory, settings = task_plan_database
    user_id, task_id = create_task(factory)
    await run_task_plan(task_id, factory, settings, StaticPlanner())

    with factory() as session:
        run = session.get(AgentRun, task_id)
        assert run is not None and run.status == "awaiting_confirmation"
        assert run.result["preview"]["title"] == "跟进测评"
        assert session.query(Reminder).count() == 0
        user = session.get(User, user_id)
        assert user is not None
        response = confirm_task_plan(
            task_id, request_without_origin(f"/api/v1/agent/task-plans/{task_id}/confirm"),
            user, session, settings,
        )
        assert response.status == "confirmed"
        assert response.reminder_id is not None

    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        repeated = confirm_task_plan(
            task_id, request_without_origin(f"/api/v1/agent/task-plans/{task_id}/confirm"),
            user, session, settings,
        )
        assert repeated.status == "confirmed"
        assert repeated.reminder_id == response.reminder_id
        assert session.query(Reminder).count() == 1


@pytest.mark.anyio
async def test_clarification_and_retry_states_do_not_write_reminders(
    task_plan_database: tuple[sessionmaker[Session], Settings],
) -> None:
    factory, settings = task_plan_database
    user_id, task_id = create_task(factory)
    planner = StaticPlanner(clarification=True)
    await run_task_plan(task_id, factory, settings, planner)
    with factory() as session:
        run = session.get(AgentRun, task_id)
        assert run is not None and run.status == "needs_clarification"
        user = session.get(User, user_id)
        assert user is not None
        with pytest.raises(HTTPException) as error:
            confirm_task_plan(
                task_id, request_without_origin(f"/api/v1/agent/task-plans/{task_id}/confirm"),
                user, session, settings,
            )
        assert error.value.status_code == 409
        assert session.query(Reminder).count() == 0

    user_id, retry_task_id = create_task(factory)
    retry_planner = StaticPlanner(fail_once=True)
    await run_task_plan(retry_task_id, factory, settings, retry_planner)
    with factory() as session:
        run = session.get(AgentRun, retry_task_id)
        assert run is not None and run.status == "failed"
        assert run.attempt_count == 1
        run.status = "queued"  # Same state transition used by the retry endpoint.
        session.commit()
    await run_task_plan(retry_task_id, factory, settings, retry_planner)
    with factory() as session:
        run = session.get(AgentRun, retry_task_id)
        assert run is not None and run.status == "awaiting_confirmation"
        assert run.attempt_count == 2
        assert session.query(Reminder).count() == 0


def test_date_only_plan_defaults_to_nine_am_in_account_timezone() -> None:
    now = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
    candidate = TaskPlanCandidate(title="跟进测评", event_at="2026-11-11")
    event_at = normalize_candidate_time(
        candidate, "下周三前跟进测评", "Asia/Shanghai", now
    )
    assert event_at is not None
    assert event_at.isoformat() == "2026-11-11T09:00:00+08:00"


@pytest.mark.anyio
async def test_openai_compatible_task_planner_sends_timezone_and_validates_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_payload = json.loads(body["messages"][1]["content"])
        assert "不可信数据" in body["messages"][0]["content"]
        assert user_payload["timezone"] == "Asia/Shanghai"
        assert "local_now" in user_payload
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "needs_clarification": False,
                                    "clarification_question": None,
                                    "title": "跟进测评",
                                    "details": None,
                                    "kind": "assessment",
                                    "event_at": "2030-11-11T09:00:00",
                                    "company_name": "星河科技",
                                    "job_title": None,
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleTaskPlanner(transport=httpx.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        llm_base_url="https://llm.example/v1",
        llm_api_key="test-key",
        llm_model="test-model",
    )
    now = datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc)
    candidate, model_name = await provider.plan(
        "下周三前跟进星河科技测评", "Asia/Shanghai", now, settings
    )
    assert candidate.kind == "assessment"
    assert model_name == "test-model"
