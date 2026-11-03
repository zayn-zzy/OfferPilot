"""Shared limits for persisted background Agent runs."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentRun

MAX_AGENT_ATTEMPTS = 3
MAX_ACTIVE_AGENT_RUNS_PER_USER = 3
ACTIVE_AGENT_RUN_STATUSES = ("queued", "running", "cancelling")


def count_active_agent_runs(session: Session, user_id: UUID) -> int:
    """Count the owner's queued, running, and cooperatively cancelling runs."""

    return session.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user_id,
            AgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
        )
    ) or 0
