"""Reminder endpoint and Celery delivery logic tests without Redis or network services."""

import asyncio
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.celery_app import celery_app
from app.core.config import Settings
from app.main import create_app
from app.models import Base, Notification, Reminder, User, utc_now
from app.routes.auth import update_current_user_timezone
from app.routes.reminders import (
    complete_reminder,
    create_reminder,
    list_reminders,
    mark_notification_read,
    pause_reminder,
    retry_reminder_delivery,
    resume_reminder,
    snooze_reminder,
)
from app.schemas import ReminderCreate, ReminderSnooze, UserTimezoneWrite
from app.services.reminder_delivery import deliver_due_reminders
from app.tasks.reminders import dispatch_due_reminders


@pytest.fixture
def test_context(tmp_path: Path) -> Generator[dict, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reminders-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite://",
        secret_key="reminder-test-secret-that-is-long-enough",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
    )
    with factory.begin() as session:
        owner = User(email="reminder-owner@example.com", password_hash="unused")
        other = User(email="reminder-other@example.com", password_hash="unused")
        session.add_all([owner, other])
        session.flush()
        owner_id, other_id = owner.id, other.id

    app = create_app(settings, factory)
    with factory() as session:
        yield {
            "app": app,
            "factory": factory,
            "owner_id": owner_id,
            "other_id": other_id,
            "settings": settings,
            "request": _request(),
            "session": session,
        }
    engine.dispose()


def _request() -> Request:
    """Create a minimal Starlette request for directly exercising route handlers."""

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/reminders",
            "raw_path": b"/api/v1/reminders",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
        }
    )


def reminder_payload(**overrides: object) -> ReminderCreate:
    payload: dict[str, object] = {
        "title": "星河科技网申截止",
        "details": "检查附件并提交申请",
        "kind": "deadline",
        "event_at": "2026-11-15T09:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "lead_minutes": 60,
        "channel": "in_app",
        "idempotency_key": str(uuid4()),
    }
    payload.update(overrides)
    return ReminderCreate.model_validate(payload)


def run(coroutine):
    """Run one async route handler without the in-process ASGI dependency runner."""

    return asyncio.run(coroutine)


def test_create_reminder_is_timezone_aware_and_idempotent(test_context: dict) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    payload = reminder_payload()
    first_response = Response(status_code=201)
    created = run(
        create_reminder(
            payload,
            context["request"],
            first_response,
            owner,
            session,
            context["settings"],
        )
    )
    first_status = first_response.status_code
    replay_response = Response()
    replayed = run(
        create_reminder(
            payload,
            context["request"],
            replay_response,
            owner,
            session,
            context["settings"],
        )
    )

    assert first_status == 201
    assert replay_response.status_code == 200
    assert replayed.id == created.id
    assert created.notify_at.isoformat() == "2026-11-15T00:00:00+00:00"
    assert created.timezone == "Asia/Shanghai"

    with pytest.raises(HTTPException) as conflict:
        run(
            create_reminder(
                reminder_payload(
                    idempotency_key=payload.idempotency_key,
                    title="内容不同的请求",
                ),
                context["request"],
                Response(),
                owner,
                session,
                context["settings"],
            )
        )
    assert conflict.value.status_code == 409


def test_reminder_lists_are_scoped_to_the_owner(test_context: dict) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    other = session.get(User, context["other_id"])
    assert owner is not None and other is not None
    response = Response()
    run(
        create_reminder(
            reminder_payload(), context["request"], response, owner, session, context["settings"]
        )
    )

    assert len(run(list_reminders(owner, session)).reminders) == 1
    assert run(list_reminders(other, session)).reminders == []


def test_snooze_increments_revision_and_complete_changes_status(test_context: dict) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    created = run(
        create_reminder(
            reminder_payload(),
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )

    snoozed = run(
        snooze_reminder(
            created.id,
            ReminderSnooze(delay_minutes=1440),
            context["request"],
            owner,
            session,
            context["settings"],
        )
    )
    assert snoozed.schedule_revision == 2
    assert snoozed.status == "scheduled"
    assert snoozed.event_at == created.event_at

    completed = run(
        complete_reminder(
            created.id, context["request"], owner, session, context["settings"]
        )
    )
    assert completed.status == "completed"


def test_due_delivery_is_atomic_and_does_not_duplicate_notifications(
    test_context: dict,
) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    due_payload = reminder_payload(
        event_at=(utc_now() - timedelta(minutes=2)).isoformat(), lead_minutes=0
    )
    created = run(
        create_reminder(
            due_payload,
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )

    assert deliver_due_reminders(context["factory"]) == 1
    assert deliver_due_reminders(context["factory"]) == 0
    session.expire_all()
    assert session.scalar(select(func.count(Notification.id))) == 1
    reminder = session.get(Reminder, created.id)
    assert reminder is not None and reminder.status == "notified"

    center = run(list_reminders(owner, session))
    notification = center.notifications[0]
    assert center.unread_count == 1
    read = run(
        mark_notification_read(
            notification.id,
            context["request"],
            owner,
            session,
            context["settings"],
        )
    )
    assert read.read_at is not None
    assert run(list_reminders(owner, session)).unread_count == 0


def test_paused_reminders_are_skipped_and_resume_requeues_overdue_items(
    test_context: dict,
) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    created = run(
        create_reminder(
            reminder_payload(
                event_at=(utc_now() - timedelta(minutes=2)).isoformat(), lead_minutes=0
            ),
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )

    paused = run(
        pause_reminder(
            created.id, context["request"], owner, session, context["settings"]
        )
    )
    assert paused.status == "paused"
    assert deliver_due_reminders(context["factory"]) == 0

    resumed = run(
        resume_reminder(
            created.id, context["request"], owner, session, context["settings"]
        )
    )
    assert resumed.status == "scheduled"
    assert resumed.notify_at >= utc_now() - timedelta(seconds=1)
    assert deliver_due_reminders(context["factory"], now=utc_now() + timedelta(seconds=1)) == 1


def test_timezone_change_rebases_future_reminders(test_context: dict) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    created = run(
        create_reminder(
            reminder_payload(),
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )
    paused = run(
        create_reminder(
            reminder_payload(title="暂停中的未来事项"),
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )
    run(
        pause_reminder(
            paused.id, context["request"], owner, session, context["settings"]
        )
    )
    updated = run(
        update_current_user_timezone(
            UserTimezoneWrite(timezone="America/Los_Angeles", recalculate_future=True),
            context["request"],
            owner,
            session,
            context["settings"],
        )
    )

    assert updated.user.timezone == "America/Los_Angeles"
    assert updated.recalculated_reminders == 2
    reminders = run(list_reminders(owner, session)).reminders
    reminder = next(item for item in reminders if item.id == created.id)
    paused_after_timezone_change = next(item for item in reminders if item.id == paused.id)
    event_at = reminder.event_at.astimezone(ZoneInfo("America/Los_Angeles"))
    assert event_at.hour == 9
    assert reminder.schedule_revision == 2
    assert reminder.event_at != created.event_at
    assert paused_after_timezone_change.status == "paused"
    assert paused_after_timezone_change.timezone == "America/Los_Angeles"


def test_failed_delivery_can_be_retried_manually(test_context: dict) -> None:
    context = test_context
    session = context["session"]
    owner = session.get(User, context["owner_id"])
    assert owner is not None
    created = run(
        create_reminder(
            reminder_payload(),
            context["request"],
            Response(),
            owner,
            session,
            context["settings"],
        )
    )
    reminder = session.get(Reminder, created.id)
    assert reminder is not None
    reminder.status = "failed"
    reminder.delivery_attempts = 5
    reminder.last_delivery_error = "站内通知投递失败，后台会重试。"
    session.commit()

    retried = run(
        retry_reminder_delivery(
            created.id,
            context["request"],
            owner,
            session,
            context["settings"],
        )
    )
    assert retried.status == "scheduled"
    assert retried.delivery_attempts == 0
    assert retried.last_delivery_error is None
    assert retried.schedule_revision == 2


def test_celery_beat_is_configured_for_periodic_reminder_dispatch() -> None:
    schedule = celery_app.conf.beat_schedule["deliver-due-reminders-every-minute"]
    assert schedule["task"] == "app.tasks.reminders.dispatch_due_reminders"
    assert schedule["schedule"] == 60.0
    assert dispatch_due_reminders.name == "app.tasks.reminders.dispatch_due_reminders"
    assert dispatch_due_reminders.max_retries == 5


def test_reminder_api_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/reminders" in paths
    assert "post" in paths["/api/v1/reminders"]
    assert "/api/v1/reminders/{reminder_id}/pause" in paths
    assert "/api/v1/reminders/{reminder_id}/resume" in paths
    assert "/api/v1/notifications/{notification_id}/read" in paths
