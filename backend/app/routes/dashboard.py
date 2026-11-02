"""Owner-scoped dashboard summary queries."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import AgentRun, Application, Company, JobPosting, Reminder, User, utc_now
from app.routes.auth import current_user_dependency, session_dependency
from app.schemas import (
    ApplicationStage,
    DashboardAgentRunRead,
    DashboardCurrentStageRead,
    DashboardDeadlineRead,
    DashboardRead,
    DashboardStageCountRead,
    DashboardTaskRead,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
STAGE_ORDER: tuple[ApplicationStage, ...] = (
    "to_research",
    "interested",
    "preparing",
    "applied",
    "assessment",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "closed",
)
TERMINAL_APPLICATION_STAGES = ("accepted", "rejected", "withdrawn", "closed")
TASK_WINDOW_DAYS = 7
DEADLINE_WINDOW_DAYS = 14
MAX_DASHBOARD_ITEMS = 5


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _job_label(company_name: str | None, title: str | None) -> str:
    company = company_name or "未填写公司"
    role = title or "未填写职位"
    return f"{company} · {role}"


def get_dashboard(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> DashboardRead:
    """Collect the next actions, deadlines, pipeline, and Agent activity for one user."""

    now = _as_utc(utc_now())
    user_zone = ZoneInfo(user.timezone)
    local_today = now.astimezone(user_zone).date()
    task_window_start = now - timedelta(days=1)
    task_window_end = now + timedelta(days=TASK_WINDOW_DAYS)
    task_date_start = local_today - timedelta(days=1)
    task_date_end = local_today + timedelta(days=TASK_WINDOW_DAYS)
    deadline_end = local_today + timedelta(days=DEADLINE_WINDOW_DAYS)

    raw_stage_counts = session.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user.id)
        .group_by(Application.status)
    ).all()
    counts = Counter({str(stage): int(count) for stage, count in raw_stage_counts})
    stage_counts = [
        DashboardStageCountRead(status=stage, count=counts[stage])
        for stage in STAGE_ORDER
        if counts[stage]
    ]

    latest_active = session.execute(
        select(Application, JobPosting, Company.name)
        .join(
            JobPosting,
            and_(
                JobPosting.id == Application.job_id,
                JobPosting.user_id == user.id,
            ),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(
            Application.user_id == user.id,
            Application.status.not_in(TERMINAL_APPLICATION_STAGES),
        )
        .order_by(Application.updated_at.desc(), Application.id.desc())
        .limit(1)
    ).first()
    current_stage = None
    if latest_active:
        application, job, company_name = latest_active
        current_stage = DashboardCurrentStageRead(
            status=application.status,
            job_id=job.id,
            job_label=_job_label(company_name, job.title),
            updated_at=_as_utc(application.updated_at),
        )

    tasks: list[DashboardTaskRead] = []
    reminder_rows = session.execute(
        select(Reminder, JobPosting, Company.name)
        .outerjoin(
            JobPosting,
            and_(JobPosting.id == Reminder.job_id, JobPosting.user_id == user.id),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(
            Reminder.user_id == user.id,
            Reminder.status.in_(("scheduled", "notified", "failed")),
            Reminder.event_at >= task_window_start,
            Reminder.event_at <= task_window_end,
        )
        .order_by(Reminder.event_at.asc(), Reminder.id)
        .limit(MAX_DASHBOARD_ITEMS)
    ).all()
    for reminder, job, company_name in reminder_rows:
        tasks.append(
            DashboardTaskRead(
                id=reminder.id,
                kind="reminder",
                title=reminder.title,
                due_at=_as_utc(reminder.event_at),
                timezone=reminder.timezone,
                status=reminder.status,
                job_id=job.id if job else None,
                job_label=_job_label(company_name, job.title) if job else None,
            )
        )

    follow_up_rows = session.execute(
        select(Application, JobPosting, Company.name)
        .join(
            JobPosting,
            and_(JobPosting.id == Application.job_id, JobPosting.user_id == user.id),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(
            Application.user_id == user.id,
            Application.status.not_in(TERMINAL_APPLICATION_STAGES),
            Application.next_action.is_not(None),
            Application.next_action_due >= task_date_start,
            Application.next_action_due <= task_date_end,
        )
        .order_by(Application.next_action_due.asc(), Application.updated_at.desc())
        .limit(MAX_DASHBOARD_ITEMS)
    ).all()
    for application, job, company_name in follow_up_rows:
        tasks.append(
            DashboardTaskRead(
                id=application.id,
                kind="application_follow_up",
                title=application.next_action or "投递跟进",
                due_date=application.next_action_due,
                timezone=user.timezone,
                status=application.status,
                job_id=job.id,
                job_label=_job_label(company_name, job.title),
            )
        )

    tasks.sort(
        key=lambda item: (
            item.due_at or datetime.combine(item.due_date, datetime.min.time(), user_zone),
            item.kind,
            str(item.id),
        )
    )

    deadline_rows = session.execute(
        select(JobPosting, Application.status, Company.name)
        .outerjoin(
            Application,
            and_(Application.job_id == JobPosting.id, Application.user_id == user.id),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(
            JobPosting.user_id == user.id,
            JobPosting.deadline >= local_today,
            JobPosting.deadline <= deadline_end,
        )
        .order_by(JobPosting.deadline.asc(), JobPosting.updated_at.desc(), JobPosting.id)
        .limit(MAX_DASHBOARD_ITEMS)
    ).all()
    deadlines = [
        DashboardDeadlineRead(
            job_id=job.id,
            job_label=_job_label(company_name, job.title),
            deadline=job.deadline,
            days_remaining=(job.deadline - local_today).days,
            application_status=application_status,
        )
        for job, application_status, company_name in deadline_rows
        if job.deadline is not None
    ]

    recent_rows = session.execute(
        select(AgentRun, JobPosting, Company.name)
        .outerjoin(
            JobPosting,
            and_(JobPosting.id == AgentRun.job_id, JobPosting.user_id == user.id),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(MAX_DASHBOARD_ITEMS)
    ).all()
    recent_runs = [
        DashboardAgentRunRead(
            id=run.id,
            task_type=run.task_type,
            status=run.status,
            created_at=_as_utc(run.created_at),
            finished_at=_as_utc(run.finished_at) if run.finished_at else None,
            job_id=job.id if job else None,
            job_label=_job_label(company_name, job.title) if job else None,
        )
        for run, job, company_name in recent_rows
    ]

    return DashboardRead(
        email=user.email,
        timezone=user.timezone,
        today=local_today,
        current_stage=current_stage,
        stage_counts=stage_counts,
        upcoming_tasks=tasks[:MAX_DASHBOARD_ITEMS],
        approaching_deadlines=deadlines,
        recent_agent_runs=recent_runs,
    )


@router.get("", response_model=DashboardRead)
def read_dashboard(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> DashboardRead:
    """Return the authenticated user's dashboard summary."""

    return get_dashboard(user, session)
