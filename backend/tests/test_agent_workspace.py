"""Agent workspace catalog and cross-workflow history tests."""

from collections.abc import Generator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import AgentRun, Base, Company, JobPosting, User, utc_now
from app.routes.agent import read_agent_workspace


@pytest.fixture
def workspace_context() -> Generator[dict[str, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        owner = User(
            id=uuid4(),
            email="agent-workspace-owner@example.com",
            password_hash="unused",
            timezone="Asia/Shanghai",
        )
        other = User(
            id=uuid4(),
            email="agent-workspace-other@example.com",
            password_hash="unused",
            timezone="Asia/Tokyo",
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
            name="其他账户公司",
            normalized_name="其他账户公司",
        )
        owner_job = JobPosting(
            id=uuid4(),
            user_id=owner.id,
            company_id=owner_company.id,
            title="后端工程师",
            required_skills=[],
            source_type="manual",
            source_captured_at=utc_now(),
        )
        other_job = JobPosting(
            id=uuid4(),
            user_id=other.id,
            company_id=other_company.id,
            title="不应泄漏的岗位",
            required_skills=[],
            source_type="manual",
            source_captured_at=utc_now(),
        )
        now = utc_now()
        owner_run = AgentRun(
            id=uuid4(),
            user_id=owner.id,
            job_id=owner_job.id,
            task_type="skill_workflow",
            skill_id="job_analysis",
            skill_version="1.0.0",
            status="succeeded",
            input_text="private owner prompt",
            result={"private": "model result"},
            events=[
                {
                    "event": "telemetry",
                    "step": "telemetry",
                    "metrics": {
                        "duration_ms": 125,
                        "total_tokens": 72,
                        "token_usage_complete": True,
                        "estimated_cost_usd": 0.00012,
                        "cost_estimate_complete": True,
                    },
                }
            ],
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        other_run = AgentRun(
            id=uuid4(),
            user_id=other.id,
            job_id=other_job.id,
            task_type="company_research",
            status="failed",
            input_text="other account prompt",
            events=[],
            created_at=now + timedelta(minutes=1),
            updated_at=now + timedelta(minutes=1),
        )
        session.add_all(
            [owner, other, owner_company, other_company, owner_job, other_job, owner_run, other_run]
        )
        session.commit()
        session.refresh(owner)
        yield {"factory": factory, "owner": owner, "other": other, "run": owner_run}
    engine.dispose()


def test_workspace_lists_supported_workflows_and_owner_runs(
    workspace_context: dict[str, object],
) -> None:
    with workspace_context["factory"]() as session:
        workspace = read_agent_workspace(workspace_context["owner"], session)

    assert workspace.timezone == "Asia/Shanghai"
    assert {item.id for item in workspace.capabilities} == {
        "reminder_plan",
        "job_extraction",
        "job_match",
        "company_research",
        "knowledge_qa",
        "career_materials",
    }
    reminder = next(item for item in workspace.capabilities if item.id == "reminder_plan")
    assert reminder.confirmation_required is True
    assert reminder.action_level == "local_draft"
    matching = next(item for item in workspace.capabilities if item.id == "job_match")
    assert matching.confirmation_required is False
    assert matching.action_level == "read_only"

    assert len(workspace.recent_runs) == 1
    run = workspace.recent_runs[0]
    assert run.task_type == "skill_workflow"
    assert run.job_label == "星河科技 · 后端工程师"
    assert run.duration_ms == 125
    assert run.total_tokens == 72
    assert run.estimated_cost_usd == pytest.approx(0.00012)
    assert "input_text" not in run.model_dump()
    assert "result" not in run.model_dump()


def test_workspace_history_isolated_for_each_user(
    workspace_context: dict[str, object],
) -> None:
    with workspace_context["factory"]() as session:
        workspace = read_agent_workspace(workspace_context["other"], session)

    assert len(workspace.recent_runs) == 1
    assert workspace.recent_runs[0].task_type == "company_research"
    assert workspace.recent_runs[0].job_label == "其他账户公司 · 不应泄漏的岗位"
