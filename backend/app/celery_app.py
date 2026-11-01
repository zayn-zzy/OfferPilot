"""Celery worker and periodic scheduler configuration."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "offerpilot",
    broker=settings.celery_broker_url,
    include=["app.tasks.reminders"],
)
celery_app.conf.update(
    accept_content=["json"],
    beat_schedule={
        "deliver-due-reminders-every-minute": {
            "task": "app.tasks.reminders.dispatch_due_reminders",
            "schedule": 60.0,
        }
    },
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    task_default_queue="offerpilot",
    task_ignore_result=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    timezone="UTC",
    worker_prefetch_multiplier=1,
)
