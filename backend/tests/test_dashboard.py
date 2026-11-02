"""Owner-scoped dashboard aggregation tests."""

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    AgentRun,
    Application,
    Base,
    Company,
    JobPosting,
    Reminder,
    User,
)
from app.routes import dashboard as dashboard_routes
from app.routes.dashboard import get_dashboard

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def dashboard_context(
    monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(dashboard_routes, "utc_now", lambda: NOW)

    with factory() as session:
        owner = User(
            id=uuid4(),
            email="dashboard-owner@example.com",
            password_hash="unused",
            timezone="Asia/Shanghai",
        )
        other = User(
            id=uuid4(),
            email="dashboard-other@example.com",
            password_hash="unused",
            timezone="Asia/Shanghai",
        )
        owner_company = Company(
            id=uuid4(),
            user_id=owner.id,
            name="星河科技",
            normalized_name="星河科技",
        )
        other_company = Company(
            id=uuid4(),
            user_id=other.id,
            name="其他用户公司",
            normalized_name="其他用户公司",
        )
        near_job = JobPosting(
            id=uuid4(),
            user_id=owner.id,
            company_id=owner_company.id,
            title="后端工程师",
            deadline=date(2026, 11, 7),
            required_skills=[],
            source_type="manual",
            source_captured_at=NOW,
            created_at=NOW - timedelta(days=5),
            updated_at=NOW - timedelta(hours=3),
        )
        untracked_job = JobPosting(
            id=uuid4(),
            user_id=owner.id,
            company_id=owner_company.id,
            title="数据工程师",
            deadline=date(2026, 11, 5),
            required_skills=[],
            source_type="manual",
            source_captured_at=NOW,
            created_at=NOW - timedelta(days=3),
            updated_at=NOW - timedelta(hours=2),
        )
        far_job = JobPosting(
            id=uuid4(),
            user_id=owner.id,
            company_id=owner_company.id,
            title="长期岗位",
            deadline=date(2026, 11, 25),
            required_skills=[],
            source_type="manual",
            source_captured_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        other_job = JobPosting(
            id=uuid4(),
            user_id=other.id,
            company_id=other_company.id,
            title="不应泄漏的岗位",
            deadline=date(2026, 11, 4),
            required_skills=[],
            source_type="manual",
            source_captured_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all(
            [owner, other, owner_company, other_company, near_job, untracked_job, far_job, other_job]
        )
        session.flush()

        latest_application = Application(
            id=uuid4(),
            user_id=owner.id,
            job_id=near_job.id,
            status="interview",
            next_action="准备技术面试",
            next_action_due=date(2026, 11, 4),
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(hours=1),
        )
        older_application = Application(
            id=uuid4(),
            user_id=owner.id,
            job_id=far_job.id,
            status="applied",
            created_at=NOW - timedelta(days=4),
            updated_at=NOW - timedelta(hours=6),
        )
        other_application = Application(
            id=uuid4(),
            user_id=other.id,
            job_id=other_job.id,
            status="offer",
            updated_at=NOW,
        )
        owner_reminder = Reminder(
            id=uuid4(),
            user_id=owner.id,
            job_id=near_job.id,
            title="查看面试通知",
            kind="interview",
            event_at=NOW + timedelta(days=1),
            notify_at=NOW + timedelta(hours=20),
            timezone="Asia/Shanghai",
            status="scheduled",
            idempotency_key="dashboard-owner-reminder-1",
            request_hash="owner-hash",
        )
        other_reminder = Reminder(
            id=uuid4(),
            user_id=other.id,
            job_id=other_job.id,
            title="其他用户提醒",
            kind="deadline",
            event_at=NOW + timedelta(hours=2),
            notify_at=NOW + timedelta(hours=1),
            timezone="Asia/Shanghai",
            status="scheduled",
            idempotency_key="dashboard-other-reminder-1",
            request_hash="other-hash",
        )
        owner_run = AgentRun(
            id=uuid4(),
            user_id=owner.id,
            job_id=near_job.id,
            task_type="company_research",
            status="succeeded",
            input_text="公司公开信息调研",
            events=[],
            created_at=NOW - timedelta(minutes=20),
            updated_at=NOW - timedelta(minutes=10),
            finished_at=NOW - timedelta(minutes=10),
        )
        other_run = AgentRun(
            id=uuid4(),
            user_id=other.id,
            job_id=other_job.id,
            task_type="skill_workflow",
            status="failed",
            input_text="其他用户任务",
            events=[],
            created_at=NOW,
            updated_at=NOW,
        )
        session.add_all(
            [
                latest_application,
                older_application,
                other_application,
                owner_reminder,
                other_reminder,
                owner_run,
                other_run,
            ]
        )
        session.commit()
        session.refresh(owner)
        yield {"factory": factory, "owner": owner, "other": other}

    engine.dispose()


def test_dashboard_aggregates_owner_pipeline_tasks_deadlines_and_runs(
    dashboard_context: dict[str, object],
) -> None:
    with dashboard_context["factory"]() as session:
        dashboard = get_dashboard(dashboard_context["owner"], session)

    assert dashboard.email == "dashboard-owner@example.com"
    assert dashboard.today == date(2026, 11, 3)
    assert dashboard.current_stage is not None
    assert dashboard.current_stage.status == "interview"
    assert dashboard.current_stage.job_label == "星河科技 · 后端工程师"
    assert [(item.status, item.count) for item in dashboard.stage_counts] == [
        ("applied", 1),
        ("interview", 1),
    ]
    assert {task.kind for task in dashboard.upcoming_tasks} == {
        "reminder",
        "application_follow_up",
    }
    assert all("其他用户" not in (task.job_label or "") for task in dashboard.upcoming_tasks)
    assert [item.job_label for item in dashboard.approaching_deadlines] == [
        "星河科技 · 数据工程师",
        "星河科技 · 后端工程师",
    ]
    assert [item.days_remaining for item in dashboard.approaching_deadlines] == [2, 4]
    assert len(dashboard.recent_agent_runs) == 1
    assert dashboard.recent_agent_runs[0].task_type == "company_research"
    assert dashboard.recent_agent_runs[0].job_label == "星河科技 · 后端工程师"


def test_dashboard_isolates_each_users_data(
    dashboard_context: dict[str, object],
) -> None:
    other = dashboard_context["other"]
    with dashboard_context["factory"]() as session:
        dashboard = get_dashboard(other, session)

    assert dashboard.current_stage is not None
    assert dashboard.current_stage.status == "offer"
    assert dashboard.stage_counts[0].count == 1
    assert dashboard.upcoming_tasks[0].title == "其他用户提醒"
    assert dashboard.approaching_deadlines[0].job_label == "其他用户公司 · 不应泄漏的岗位"
    assert dashboard.recent_agent_runs[0].status == "failed"
