"""Owner-scoped reminder management and in-app notification history."""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Company, JobPosting, Notification, Reminder, User, utc_now
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    NotificationRead,
    ReminderCenterRead,
    ReminderCreate,
    ReminderRead,
    ReminderSnooze,
)

router = APIRouter(prefix="/reminders", tags=["reminders"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


def _as_utc(value: datetime) -> datetime:
    """Normalize database and input timestamps to timezone-aware UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_reminder(session: Session, user: User, reminder: Reminder) -> ReminderRead:
    job_label = None
    if reminder.job_id is not None:
        job = session.scalar(
            select(JobPosting).where(
                JobPosting.id == reminder.job_id,
                JobPosting.user_id == user.id,
            )
        )
        if job is not None:
            company = (
                session.scalar(
                    select(Company).where(
                        Company.id == job.company_id,
                        Company.user_id == user.id,
                    )
                )
                if job.company_id is not None
                else None
            )
            job_label = " · ".join(
                item for item in (company.name if company else None, job.title) if item
            ) or "关联岗位"

    return ReminderRead(
        id=reminder.id,
        job_id=reminder.job_id,
        job_label=job_label,
        title=reminder.title,
        details=reminder.details,
        kind=reminder.kind,
        event_at=_as_utc(reminder.event_at),
        notify_at=_as_utc(reminder.notify_at),
        timezone=reminder.timezone,
        lead_minutes=reminder.lead_minutes,
        channel=reminder.channel,
        status=reminder.status,
        schedule_revision=reminder.schedule_revision,
        delivery_attempts=reminder.delivery_attempts,
        last_delivery_error=reminder.last_delivery_error,
        created_at=_as_utc(reminder.created_at),
        updated_at=_as_utc(reminder.updated_at),
    )


def _owned_reminder(session: Session, user: User, reminder_id: UUID) -> Reminder:
    reminder = session.scalar(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_id == user.id,
        )
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return reminder


@router.get("", response_model=ReminderCenterRead)
async def list_reminders(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    include_closed: bool = False,
) -> ReminderCenterRead:
    """Return the current user's reminders and latest in-app notifications."""

    statement = select(Reminder).where(Reminder.user_id == user.id)
    if not include_closed:
        statement = statement.where(
            Reminder.status.in_(("scheduled", "paused", "notified", "failed"))
        )
    reminders = session.scalars(
        statement.order_by(Reminder.notify_at.asc(), Reminder.created_at.desc()).limit(100)
    ).all()
    notifications = session.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(50)
    ).all()
    unread_count = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
    ) or 0
    return ReminderCenterRead(
        reminders=[_read_reminder(session, user, reminder) for reminder in reminders],
        notifications=[NotificationRead.model_validate(item) for item in notifications],
        unread_count=unread_count,
    )


@router.post("", response_model=ReminderRead, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    payload: ReminderCreate,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Persist a user-confirmed reminder; repeated submissions use one idempotency key."""

    enforce_same_origin(request, settings)
    if payload.job_id is not None:
        job = session.scalar(
            select(JobPosting).where(
                JobPosting.id == payload.job_id,
                JobPosting.user_id == user.id,
            )
        )
        if job is None:
            raise HTTPException(status_code=404, detail="关联岗位不存在")

    request_hash = hashlib.sha256(
        payload.model_dump_json(exclude={"idempotency_key"}).encode("utf-8")
    ).hexdigest()
    existing = session.scalar(
        select(Reminder).where(
            Reminder.user_id == user.id,
            Reminder.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="该请求幂等键已用于不同内容，请刷新表单后重试。",
            )
        response.status_code = status.HTTP_200_OK
        return _read_reminder(session, user, existing)

    now = utc_now()
    event_at = _as_utc(payload.event_at)
    reminder = Reminder(
        id=uuid4(),
        user_id=user.id,
        job_id=payload.job_id,
        title=payload.title,
        details=payload.details,
        kind=payload.kind,
        event_at=event_at,
        notify_at=event_at - timedelta(minutes=payload.lead_minutes),
        timezone=payload.timezone,
        lead_minutes=payload.lead_minutes,
        channel=payload.channel,
        status="scheduled",
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        schedule_revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(reminder)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Reminder).where(
                Reminder.user_id == user.id,
                Reminder.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None or existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="提醒创建冲突，请刷新后重试。") from None
        response.status_code = status.HTTP_200_OK
        return _read_reminder(session, user, existing)
    session.refresh(reminder)
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/complete", response_model=ReminderRead)
async def complete_reminder(
    reminder_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Mark an active reminder complete; repeat completion is harmless."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status == "cancelled":
        raise HTTPException(status_code=409, detail="已取消的提醒不能标记为完成")
    reminder.status = "completed"
    reminder.updated_at = utc_now()
    session.commit()
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/pause", response_model=ReminderRead)
async def pause_reminder(
    reminder_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Pause a scheduled reminder without losing its current delivery time."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status != "scheduled":
        raise HTTPException(status_code=409, detail="只有待提醒状态可以暂停")
    reminder.status = "paused"
    reminder.updated_at = utc_now()
    session.commit()
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/resume", response_model=ReminderRead)
async def resume_reminder(
    reminder_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Resume a paused reminder, delivering immediately if its time has passed."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status != "paused":
        raise HTTPException(status_code=409, detail="只有已暂停的提醒可以恢复")
    now = utc_now()
    if _as_utc(reminder.notify_at) < now:
        reminder.notify_at = now
    reminder.status = "scheduled"
    reminder.updated_at = now
    session.commit()
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/cancel", response_model=ReminderRead)
async def cancel_reminder(
    reminder_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Cancel an active reminder; repeat cancellation is harmless."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status == "completed":
        raise HTTPException(status_code=409, detail="已完成的提醒不能取消")
    reminder.status = "cancelled"
    reminder.updated_at = utc_now()
    session.commit()
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/snooze", response_model=ReminderRead)
async def snooze_reminder(
    reminder_id: UUID,
    payload: ReminderSnooze,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Postpone an active reminder and rotate its delivery idempotency revision."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="已结束的提醒不能延期")
    now = utc_now()
    reminder.notify_at = now + timedelta(minutes=payload.delay_minutes)
    reminder.status = "scheduled"
    reminder.schedule_revision += 1
    reminder.updated_at = now
    session.commit()
    return _read_reminder(session, user, reminder)


@router.post("/{reminder_id}/retry", response_model=ReminderRead)
async def retry_reminder_delivery(
    reminder_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ReminderRead:
    """Schedule an immediate, new idempotent delivery attempt after a failure."""

    enforce_same_origin(request, settings)
    reminder = _owned_reminder(session, user, reminder_id)
    if reminder.status not in {"failed", "scheduled"} or not reminder.last_delivery_error:
        raise HTTPException(status_code=409, detail="该提醒当前没有可重试的投递失败")
    now = utc_now()
    reminder.status = "scheduled"
    reminder.notify_at = now
    reminder.schedule_revision += 1
    reminder.delivery_attempts = 0
    reminder.last_attempt_at = None
    reminder.last_delivery_error = None
    reminder.updated_at = now
    session.commit()
    return _read_reminder(session, user, reminder)


@notifications_router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> NotificationRead:
    """Mark one of the current user's notifications read."""

    enforce_same_origin(request, settings)
    notification = session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    if notification.read_at is None:
        notification.read_at = utc_now()
        session.commit()
    return NotificationRead.model_validate(notification)
