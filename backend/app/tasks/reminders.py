"""Celery entry point for scheduled reminder delivery."""

from celery import Task
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db import create_session_factory
from app.services.reminder_delivery import deliver_due_reminders


@celery_app.task(
    bind=True,
    name="app.tasks.reminders.dispatch_due_reminders",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def dispatch_due_reminders(_task: Task) -> int:
    """Deliver due reminders, retrying transient database failures safely."""

    settings = get_settings()
    engine, factory = create_session_factory(settings)
    try:
        return deliver_due_reminders(factory)
    finally:
        engine.dispose()
