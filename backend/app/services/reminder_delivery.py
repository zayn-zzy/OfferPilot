"""Idempotent database delivery for due in-app reminders."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Notification, Reminder, utc_now


def _as_utc(value: datetime) -> datetime:
    """Treat SQLite's naive datetimes as UTC and normalize aware values."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def deliver_due_reminders(
    session_factory: sessionmaker[Session],
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    """Create one notification per due schedule revision and mark it delivered."""

    now_utc = _as_utc(now or utc_now())
    with session_factory() as session:
        due_ids = session.scalars(
            select(Reminder.id)
            .where(Reminder.status == "scheduled", Reminder.notify_at <= now_utc)
            .order_by(Reminder.notify_at, Reminder.id)
            .limit(max(1, min(batch_size, 500)))
        ).all()

    delivered = 0
    first_error: SQLAlchemyError | None = None
    for reminder_id in due_ids:
        try:
            with session_factory() as session, session.begin():
                reminder = session.scalar(
                    select(Reminder)
                    .where(
                        Reminder.id == reminder_id,
                        Reminder.status == "scheduled",
                        Reminder.notify_at <= now_utc,
                    )
                    .with_for_update(skip_locked=True)
                )
                if reminder is None:
                    continue

                existing = session.scalar(
                    select(Notification.id).where(
                        Notification.user_id == reminder.user_id,
                        Notification.idempotency_key
                        == f"reminder:{reminder.id}:v{reminder.schedule_revision}",
                    )
                )
                if existing is not None:
                    reminder.status = "notified"
                    reminder.updated_at = now_utc
                    continue

                event_at = _as_utc(reminder.event_at)
                event_time = event_at.isoformat(timespec="minutes").replace("+00:00", "Z")
                session.add(
                    Notification(
                        user_id=reminder.user_id,
                        reminder_id=reminder.id,
                        title=reminder.title,
                        body=reminder.details or (
                            f"提醒时间已到。事项时间：{event_time}（{reminder.timezone}）"
                        ),
                        idempotency_key=f"reminder:{reminder.id}:v{reminder.schedule_revision}",
                        created_at=now_utc,
                    )
                )
                reminder.status = "notified"
                reminder.delivery_attempts += 1
                reminder.last_attempt_at = now_utc
                reminder.last_delivery_error = None
                reminder.updated_at = now_utc
                session.flush()
                delivered += 1
        except IntegrityError:
            # A concurrent/retried worker may have committed this exact key first.
            existing_delivery = False
            try:
                with session_factory() as recovery, recovery.begin():
                    reminder = recovery.get(Reminder, reminder_id)
                    if reminder is not None:
                        existing = recovery.scalar(
                            select(Notification.id).where(
                                Notification.user_id == reminder.user_id,
                                Notification.idempotency_key
                                == f"reminder:{reminder.id}:v{reminder.schedule_revision}",
                            )
                        )
                        existing_delivery = existing is not None
                        if existing_delivery and reminder.status == "scheduled":
                            reminder.status = "notified"
                            reminder.updated_at = now_utc
            except SQLAlchemyError as exc:
                first_error = first_error or exc
                _record_delivery_failure(session_factory, reminder_id, now_utc)
            if not existing_delivery:
                first_error = first_error or SQLAlchemyError(
                    "Reminder notification idempotency conflict"
                )
                _record_delivery_failure(session_factory, reminder_id, now_utc)
        except SQLAlchemyError as exc:
            first_error = first_error or exc
            _record_delivery_failure(session_factory, reminder_id, now_utc)

    if first_error is not None:
        raise first_error
    return delivered


def _record_delivery_failure(
    session_factory: sessionmaker[Session], reminder_id: UUID, now: datetime
) -> None:
    """Persist safe retry state when the database is available after a failure."""

    try:
        with session_factory() as session, session.begin():
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.status == "scheduled",
                )
            )
            if reminder is None:
                return
            reminder.delivery_attempts += 1
            reminder.last_attempt_at = now
            reminder.last_delivery_error = "站内通知投递失败，后台会重试。"
            if reminder.delivery_attempts >= 5:
                reminder.status = "failed"
            reminder.updated_at = now
    except SQLAlchemyError:
        # If the database itself is unavailable, Celery retries and Beat will scan again.
        return
