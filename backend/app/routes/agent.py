"""Owner-scoped job extraction tasks, progress streaming, retry, and confirmation."""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Annotated, TypedDict
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from langgraph.graph import END, START, StateGraph
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import (
    AgentRun,
    Application,
    Company,
    JobPosting,
    JobSourceEvidence,
    Reminder,
    User,
    utc_now,
)
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.routes.jobs import (
    _assign_job_fields,
    _company_for_payload,
    _duplicate_source_error,
    _normalize_source_url,
    _to_read,
)
from app.schemas import (
    AgentJobExtractionCreate,
    AgentTaskPlanCreate,
    AgentTaskPlanPreview,
    AgentTaskPlanRead,
    AgentTaskRead,
    AgentTaskSourceRead,
    AgentCapabilityRead,
    AgentWorkspaceRead,
    AgentWorkspaceRunRead,
    JobExtractionConfirm,
    JobPostingRead,
    JobPostingWrite,
    JobSourceEvidenceRead,
)
from app.services.job_extraction import JobExtractionError, JobExtractionProvider
from app.services.task_planner import (
    TaskPlanCandidate,
    TaskPlannerError,
    TaskPlannerProvider,
    normalize_candidate_time,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])
MAX_ATTEMPTS = 3
MAX_ACTIVE_TASKS_PER_USER = 3
MAX_TASK_PLAN_ATTEMPTS = 3
TERMINAL_STATUSES = {"succeeded", "failed", "confirmed", "cancelled"}
AGENT_WORKSPACE_CAPABILITIES = (
    AgentCapabilityRead(
        id="reminder_plan",
        title="整理求职待办",
        description="用自然语言描述动作和日期，生成提醒草稿；确认后才保存到提醒中心。",
        action_label="规划提醒",
        href="/agent#task-planner",
        action_level="local_draft",
        confirmation_required=True,
    ),
    AgentCapabilityRead(
        id="job_extraction",
        title="提取岗位信息",
        description="从你粘贴的招聘原文提取岗位字段和引用，检查后再决定是否保存。",
        action_label="粘贴招聘原文",
        href="/jobs?task=extract",
        action_level="local_draft",
        confirmation_required=True,
    ),
    AgentCapabilityRead(
        id="job_match",
        title="查看岗位匹配",
        description="逐项比较岗位条件与已确认档案/简历内容，展示证据和未知项，不估算录用概率。",
        action_label="选择岗位",
        href="/jobs",
        action_level="read_only",
        confirmation_required=False,
    ),
    AgentCapabilityRead(
        id="company_research",
        title="研究招聘公司",
        description="查阅公开来源并显示引用、搜索时间和过期提示；来源不足时明确说明。",
        action_label="查看公司档案",
        href="/companies",
        action_level="read_only",
        confirmation_required=False,
    ),
    AgentCapabilityRead(
        id="knowledge_qa",
        title="询问个人求职资料",
        description="基于已确认简历和个人笔记回答，并展示检索到的原文片段。",
        action_label="提问并查看引用",
        href="/knowledge",
        action_level="read_only",
        confirmation_required=False,
    ),
    AgentCapabilityRead(
        id="career_materials",
        title="准备求职材料",
        description="选择岗位后生成岗位分析、简历建议、申请回答或面试准备草稿；保存准备包需要单独审批。",
        action_label="选择 Skill 与岗位",
        href="/skills",
        action_level="local_draft",
        confirmation_required=True,
    ),
)


class TaskPlanWorkflowState(TypedDict, total=False):
    """Transient LangGraph state for one reminder-planning run."""

    task_id: UUID
    source_text: str
    timezone: str
    candidate: dict[str, object]
    event_at: str | None
    model_name: str
    preview: dict[str, object]
    final_status: str
    error_code: str
    error_message: str


def _task_read(run: AgentRun) -> AgentTaskRead:
    return AgentTaskRead(
        id=run.id,
        task_type=run.task_type,
        status=run.status,
        source_url=run.source_url,
        result=run.result,
        events=run.events,
        error_code=run.error_code,
        error_message=run.error_message,
        model_name=run.model_name,
        attempt_count=run.attempt_count,
        job_id=run.job_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def _append_event(run: AgentRun, event: str, message: str, **details: object) -> None:
    events = list(run.events or [])
    events.append(
        {
            "id": len(events) + 1,
            "event": event,
            "message": message,
            "created_at": utc_now().isoformat(),
            **details,
        }
    )
    run.events = events
    run.updated_at = utc_now()


def _owned_task(
    session: Session, user: User, task_id: UUID, *, for_update: bool = False
) -> AgentRun:
    statement = select(AgentRun).where(
        AgentRun.id == task_id, AgentRun.user_id == user.id
    )
    if for_update:
        statement = statement.with_for_update()
    run = session.scalar(statement)
    if run is None or run.task_type != "job_extraction":
        raise HTTPException(status_code=404, detail="Agent 任务不存在")
    return run


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _run_telemetry_summary(events: list[dict]) -> dict[str, int | float | None]:
    attempts = [
        event.get("metrics")
        for event in events
        if event.get("step") == "telemetry" and isinstance(event.get("metrics"), dict)
    ]
    if not attempts:
        return {"duration_ms": None, "total_tokens": None, "estimated_cost_usd": None}

    durations = [item.get("duration_ms") for item in attempts]
    duration_ms = (
        sum(value for value in durations if isinstance(value, int) and not isinstance(value, bool))
        if all(isinstance(value, int) and not isinstance(value, bool) for value in durations)
        else None
    )
    token_values = [item.get("total_tokens") for item in attempts]
    total_tokens = (
        sum(value for value in token_values if isinstance(value, int) and not isinstance(value, bool))
        if all(
            item.get("token_usage_complete") is True
            and isinstance(item.get("total_tokens"), int)
            and not isinstance(item.get("total_tokens"), bool)
            for item in attempts
        )
        else None
    )
    cost_values = [item.get("estimated_cost_usd") for item in attempts]
    estimated_cost_usd = (
        sum(float(value) for value in cost_values if isinstance(value, (int, float)))
        if all(
            item.get("cost_estimate_complete") is True
            and isinstance(item.get("estimated_cost_usd"), (int, float))
            for item in attempts
        )
        else None
    )
    return {
        "duration_ms": duration_ms,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost_usd,
    }


def _task_plan_read(run: AgentRun) -> AgentTaskPlanRead:
    result = run.result or {}
    preview_data = result.get("preview")
    preview = AgentTaskPlanPreview.model_validate(preview_data) if preview_data else None
    reminder_id = result.get("reminder_id")
    return AgentTaskPlanRead(
        id=run.id,
        task_type="task_plan",
        status=run.status,
        preview=preview,
        reminder_id=UUID(str(reminder_id)) if reminder_id else None,
        events=list(run.events or []),
        error_code=run.error_code,
        error_message=run.error_message,
        model_name=run.model_name,
        attempt_count=run.attempt_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


@router.get("/workspace", response_model=AgentWorkspaceRead)
def read_agent_workspace(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> AgentWorkspaceRead:
    """Return supported task types and recent Agent runs for the signed-in user."""

    runs = session.execute(
        select(AgentRun, JobPosting, Company.name)
        .outerjoin(
            JobPosting,
            and_(JobPosting.id == AgentRun.job_id, JobPosting.user_id == user.id),
        )
        .outerjoin(
            Company,
            and_(Company.id == JobPosting.company_id, Company.user_id == user.id),
        )
        .where(AgentRun.user_id == user.id, AgentRun.task_type != "task_plan")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(10)
    ).all()
    recent_runs = [
        AgentWorkspaceRunRead(
            id=run.id,
            task_type=run.task_type,
            skill_id=run.skill_id,
            status=run.status,
            created_at=_as_utc(run.created_at),
            updated_at=_as_utc(run.updated_at),
            finished_at=_as_utc(run.finished_at) if run.finished_at else None,
            job_id=job.id if job else None,
            job_label=(
                f"{company_name or '未填写公司'} · {job.title or '未填写职位'}"
                if job
                else None
            ),
            **_run_telemetry_summary(list(run.events or [])),
        )
        for run, job, company_name in runs
    ]
    return AgentWorkspaceRead(
        timezone=user.timezone,
        capabilities=list(AGENT_WORKSPACE_CAPABILITIES),
        recent_runs=recent_runs,
    )


def _append_task_plan_event(run: AgentRun, event: str, message: str, **details: object) -> None:
    events = list(run.events or [])
    events.append(
        {
            "id": len(events) + 1,
            "event": event,
            "message": message,
            "created_at": utc_now().isoformat(),
            **details,
        }
    )
    run.events = events
    run.updated_at = utc_now()


def _task_plan_job_match(
    session: Session, user: User, candidate: TaskPlanCandidate
) -> tuple[UUID | None, str | None]:
    """Link only one unambiguous job owned by this user; otherwise leave it unlinked."""

    rows = session.execute(
        select(JobPosting, Company.name)
        .outerjoin(
            Company,
            (Company.id == JobPosting.company_id) & (Company.user_id == user.id),
        )
        .where(JobPosting.user_id == user.id)
    ).all()
    wanted_company = _normalize_task_match(candidate.company_name)
    wanted_title = _normalize_task_match(candidate.job_title)
    ranked: list[tuple[int, JobPosting, str | None]] = []
    for job, company_name in rows:
        actual_company = _normalize_task_match(company_name)
        actual_title = _normalize_task_match(job.title)
        company_score = _task_match_score(wanted_company, actual_company)
        title_score = _task_match_score(wanted_title, actual_title)
        if wanted_company and not company_score:
            continue
        if wanted_title and not title_score:
            continue
        if not wanted_company and not wanted_title:
            continue
        ranked.append((company_score + title_score, job, company_name))
    if not ranked:
        label = " · ".join(
            value for value in (candidate.company_name, candidate.job_title) if value
        )
        return None, label or None
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        label = " · ".join(
            value for value in (candidate.company_name, candidate.job_title) if value
        )
        return None, label or None
    _, job, company_name = ranked[0]
    label = " · ".join(value for value in (company_name, job.title) if value) or None
    return job.id, label


def _normalize_task_match(value: str | None) -> str:
    return "".join(value.casefold().split()) if value else ""


def _task_match_score(wanted: str, actual: str) -> int:
    if not wanted or not actual:
        return 0
    if wanted == actual:
        return 4
    if len(wanted) >= 2 and (wanted in actual or actual in wanted):
        return 2
    return 0


async def run_task_plan(
    task_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: TaskPlannerProvider,
) -> None:
    """Run the task through LangGraph and persist its preview before awaiting confirmation."""

    async def load_context(state: TaskPlanWorkflowState) -> dict[str, object]:
        with session_factory() as session:
            run = session.get(AgentRun, state["task_id"])
            if run is None or run.task_type != "task_plan" or run.status != "queued":
                return {"final_status": "skipped"}
            run.status = "running"
            run.attempt_count += 1
            run.error_code = None
            run.error_message = None
            run.finished_at = None
            user = session.get(User, run.user_id)
            if user is None:
                session.commit()
                return {
                    "final_status": "failed",
                    "error_code": "owner_missing",
                    "error_message": "任务所属账户不可用。",
                }
            source_text = run.input_text
            timezone_name = user.timezone
            _append_task_plan_event(
                run, "progress", "正在整理提醒草稿。", step="load_context"
            )
            session.commit()
            return {"source_text": source_text, "timezone": timezone_name}

    async def generate_candidate(state: TaskPlanWorkflowState) -> dict[str, object]:
        if "source_text" not in state:
            return {}
        try:
            now = utc_now()
            candidate, model_name = await provider.plan(
                state["source_text"], state["timezone"], now, settings
            )
            event_at = normalize_candidate_time(
                candidate, state["source_text"], state["timezone"], now
            )
            return {
                "candidate": candidate.model_dump(mode="json"),
                "event_at": event_at.isoformat() if event_at else None,
                "model_name": model_name,
            }
        except TaskPlannerError as exc:
            return {
                "final_status": "failed",
                "error_code": exc.code,
                "error_message": exc.message,
            }
        except Exception as exc:  # Never log prompt text or provider response bodies.
            logger.error("Task planning %s failed (%s)", task_id, type(exc).__name__)
            return {
                "final_status": "failed",
                "error_code": "internal_task_planning_error",
                "error_message": "任务规划遇到意外错误，请重试。",
            }

    async def validate_and_build_preview(state: TaskPlanWorkflowState) -> dict[str, object]:
        if "candidate" not in state or state.get("final_status") == "failed":
            return {}
        try:
            candidate = TaskPlanCandidate.model_validate(state["candidate"])
            timezone_name = state["timezone"]
            if candidate.needs_clarification:
                preview = AgentTaskPlanPreview(
                    timezone=timezone_name,
                    clarification_question=candidate.clarification_question,
                )
                final_status = "needs_clarification"
            else:
                raw_event_at = state.get("event_at")
                if raw_event_at is None:
                    raise TaskPlannerError(
                        "invalid_task_date", "任务日期无法确认，请重新描述。"
                    )
                event_at = datetime.fromisoformat(raw_event_at)
                with session_factory() as session:
                    run = session.get(AgentRun, state["task_id"])
                    user = session.get(User, run.user_id) if run is not None else None
                    if run is None or user is None:
                        raise TaskPlannerError("owner_missing", "任务所属账户不可用。")
                    job_id, job_label = _task_plan_job_match(session, user, candidate)
                preview = AgentTaskPlanPreview(
                    title=candidate.title,
                    details=candidate.details,
                    kind=candidate.kind,
                    event_at=event_at,
                    timezone=timezone_name,
                    job_id=job_id,
                    job_label=job_label,
                )
                final_status = "awaiting_confirmation"
            return {
                "preview": preview.model_dump(mode="json"),
                "final_status": final_status,
            }
        except TaskPlannerError as exc:
            return {
                "final_status": "failed",
                "error_code": exc.code,
                "error_message": exc.message,
            }
        except Exception as exc:
            logger.error("Task plan validation %s failed (%s)", task_id, type(exc).__name__)
            return {
                "final_status": "failed",
                "error_code": "invalid_task_plan",
                "error_message": "任务计划校验失败，请重试。",
            }

    async def persist_result(state: TaskPlanWorkflowState) -> dict[str, object]:
        final_status = state.get("final_status", "skipped")
        if final_status == "skipped":
            return {}
        with session_factory() as session:
            run = session.get(AgentRun, state["task_id"])
            if run is None or run.status != "running":
                return {}
            run.finished_at = utc_now()
            if final_status == "failed":
                run.status = "failed"
                run.error_code = state.get("error_code", "task_plan_failed")
                run.error_message = state.get("error_message", "任务规划失败，请重试。")
                _append_task_plan_event(
                    run, "failed", run.error_message, code=run.error_code
                )
            else:
                run.status = final_status
                run.result = {"preview": state["preview"]}
                run.model_name = state.get("model_name")
                message = (
                    "还需要补充信息，暂未创建提醒。"
                    if final_status == "needs_clarification"
                    else "提醒草稿已准备好；确认前不会写入提醒中心。"
                )
                _append_task_plan_event(run, "completed", message, step="preview_ready")
            session.commit()
        return {}

    graph = StateGraph(TaskPlanWorkflowState)
    graph.add_node("load_context", load_context)
    graph.add_node("generate_candidate", generate_candidate)
    graph.add_node("validate_and_build_preview", validate_and_build_preview)
    graph.add_node("persist_result", persist_result)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "generate_candidate")
    graph.add_edge("generate_candidate", "validate_and_build_preview")
    graph.add_edge("validate_and_build_preview", "persist_result")
    graph.add_edge("persist_result", END)
    await graph.compile().ainvoke({"task_id": task_id}, version="v2")


def _owned_task_plan(session: Session, user: User, task_id: UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == task_id,
            AgentRun.user_id == user.id,
            AgentRun.task_type == "task_plan",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent 任务计划不存在。")
    return run


@router.post(
    "/task-plans",
    response_model=AgentTaskPlanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_task_plan(
    payload: AgentTaskPlanCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskPlanRead:
    """Queue a natural-language reminder plan without performing the reminder write."""

    enforce_same_origin(request, settings)
    request_hash = hashlib.sha256(payload.text.encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(AgentRun).where(
            AgentRun.user_id == user.id,
            AgentRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.task_type != "task_plan" or existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409, detail="该请求标识已用于其他内容，请重新提交。"
            )
        return _task_plan_read(existing)

    active_count = session.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user.id,
            AgentRun.task_type == "task_plan",
            AgentRun.status.in_(("queued", "running")),
        )
    )
    if active_count and active_count >= MAX_ACTIVE_TASKS_PER_USER:
        raise HTTPException(
            status_code=429, detail="已有 3 个任务计划正在处理，请稍后再试。"
        )

    run = AgentRun(
        user_id=user.id,
        task_type="task_plan",
        status="queued",
        input_text=payload.text,
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        events=[],
    )
    _append_task_plan_event(run, "progress", "任务已排队。", step="queued")
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(AgentRun).where(
                AgentRun.user_id == user.id,
                AgentRun.idempotency_key == payload.idempotency_key,
            )
        )
        if (
            existing is None
            or existing.task_type != "task_plan"
            or existing.request_hash != request_hash
        ):
            raise HTTPException(
                status_code=409, detail="任务创建冲突，请重新提交。"
            ) from None
        return _task_plan_read(existing)
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "task_plan", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _task_plan_read(run)


@router.get("/task-plans", response_model=list[AgentTaskPlanRead])
def list_task_plans(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    limit: int = 20,
) -> list[AgentTaskPlanRead]:
    """List the current user's recent task-plan runs."""

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 100 之间")
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id, AgentRun.task_type == "task_plan")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    return [_task_plan_read(run) for run in runs]


@router.get("/task-plans/{task_id}", response_model=AgentTaskPlanRead)
def get_task_plan(
    task_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> AgentTaskPlanRead:
    return _task_plan_read(_owned_task_plan(session, user, task_id))


@router.post("/task-plans/{task_id}/retry", response_model=AgentTaskPlanRead)
def retry_task_plan(
    task_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskPlanRead:
    enforce_same_origin(request, settings)
    run = _owned_task_plan(session, user, task_id)
    if run.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败任务可以重试。")
    if run.attempt_count >= MAX_TASK_PLAN_ATTEMPTS:
        raise HTTPException(
            status_code=409, detail="任务已达到最大重试次数，请重新创建。"
        )
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    _append_task_plan_event(run, "progress", "已安排任务重试。", step="retry_queued")
    session.commit()
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "task_plan", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _task_plan_read(run)


@router.post("/task-plans/{task_id}/confirm", response_model=AgentTaskPlanRead)
def confirm_task_plan(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskPlanRead:
    """Write the proposed reminder only after the owner explicitly confirms it."""

    enforce_same_origin(request, settings)
    run = _owned_task_plan(session, user, task_id)
    if run.status == "confirmed":
        return _task_plan_read(run)
    if run.status != "awaiting_confirmation" or not run.result or not run.result.get("preview"):
        raise HTTPException(status_code=409, detail="当前任务计划尚不可确认。")
    preview = AgentTaskPlanPreview.model_validate(run.result["preview"])
    if not preview.title or preview.event_at is None:
        raise HTTPException(
            status_code=409, detail="任务计划缺少提醒标题或日期，无法确认。"
        )
    now = utc_now()
    event_at = preview.event_at
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        event_at = event_at.replace(tzinfo=ZoneInfo(preview.timezone))
    event_at = event_at.astimezone(timezone.utc)
    if event_at <= now:
        raise HTTPException(
            status_code=409,
            detail="提醒日期已过去，请取消后重新创建任务计划。",
        )

    job_id = preview.job_id
    if job_id is not None:
        job = session.scalar(
            select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user.id)
        )
        if job is None:
            job_id = None

    idempotency_key = f"task-plan:{run.id}"
    reminder_payload = {
        "job_id": str(job_id) if job_id else None,
        "title": preview.title,
        "details": preview.details,
        "kind": preview.kind,
        "event_at": event_at.isoformat(),
        "timezone": preview.timezone,
        "lead_minutes": 0,
        "channel": "in_app",
    }
    request_hash = hashlib.sha256(
        json.dumps(reminder_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    reminder = Reminder(
        id=uuid4(),
        user_id=user.id,
        job_id=job_id,
        title=preview.title,
        details=preview.details,
        kind=preview.kind,
        event_at=event_at,
        notify_at=event_at,
        timezone=preview.timezone,
        lead_minutes=0,
        channel="in_app",
        status="scheduled",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        schedule_revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(reminder)
    run.job_id = job_id
    run.status = "confirmed"
    run.result = {**run.result, "reminder_id": str(reminder.id)}
    run.finished_at = now
    _append_task_plan_event(
        run, "confirmed", "提醒已创建，可在提醒中心查看。", step="reminder_created"
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Reminder).where(
                Reminder.user_id == user.id,
                Reminder.idempotency_key == idempotency_key,
            )
        )
        if existing is None or existing.request_hash != request_hash:
            raise HTTPException(
                status_code=409, detail="提醒创建冲突，请重试。"
            ) from None
        run = _owned_task_plan(session, user, task_id)
        run.status = "confirmed"
        run.job_id = existing.job_id
        run.result = {**(run.result or {}), "reminder_id": str(existing.id)}
        run.finished_at = existing.updated_at
        session.commit()
        session.refresh(run)
        return _task_plan_read(run)
    session.refresh(run)
    return _task_plan_read(run)


@router.post("/task-plans/{task_id}/cancel", response_model=AgentTaskPlanRead)
def cancel_task_plan(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskPlanRead:
    enforce_same_origin(request, settings)
    run = _owned_task_plan(session, user, task_id)
    if run.status not in {"awaiting_confirmation", "needs_clarification", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="当前任务计划无法取消。")
    if run.status != "cancelled":
        run.status = "cancelled"
        run.finished_at = utc_now()
        _append_task_plan_event(
            run, "cancelled", "任务计划已取消，未创建提醒。", step="cancelled"
        )
        session.commit()
        session.refresh(run)
    return _task_plan_read(run)


async def run_job_extraction(
    task_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: JobExtractionProvider,
) -> None:
    """Run one persisted task and record each transition before continuing."""

    with session_factory() as session:
        run = session.scalar(
            select(AgentRun).where(AgentRun.id == task_id).with_for_update()
        )
        if run is None or run.status != "queued":
            return
        run.status = "running"
        run.attempt_count += 1
        run.error_code = None
        run.error_message = None
        run.finished_at = None
        _append_event(run, "progress", "已开始解析招聘信息。", step="started")
        _append_event(run, "progress", "正在请求配置的模型服务。", step="model_request")
        source_text = run.input_text
        session.commit()

    try:
        candidate, model_name = await provider.extract(source_text, settings)
        fields = candidate.model_dump(mode="json")
    except JobExtractionError as exc:
        failure_code = exc.code
        failure_message = exc.message
    except Exception as exc:  # Keep third-party exceptions and request content out of logs.
        logger.error("Job extraction task %s failed (%s)", task_id, type(exc).__name__)
        failure_code = "internal_extraction_error"
        failure_message = "岗位解析遇到意外错误，请重试。"
    else:
        review_fields = []
        for field_name, field_data in fields.items():
            has_value = bool(field_data["value"])
            has_evidence = bool(field_data["evidence"])
            if (
                not has_value
                or not has_evidence
                or field_data["confidence"] < settings.llm_low_confidence_threshold
            ):
                review_fields.append(field_name)
        with session_factory() as session:
            run = session.scalar(
                select(AgentRun).where(AgentRun.id == task_id).with_for_update()
            )
            if run is None:
                return
            if run.status == "cancelling":
                _finish_job_extraction_cancellation(run)
                session.commit()
                return
            if run.status != "running":
                return
            run.result = {"fields": fields, "needs_review_fields": review_fields}
            run.model_name = model_name
            run.status = "succeeded"
            run.finished_at = utc_now()
            _append_event(run, "progress", "字段已完成结构校验和来源引用检查。", step="validated")
            _append_event(
                run,
                "completed",
                "岗位信息提取完成，请核对字段和原文依据。",
                step="completed",
                needs_review_count=len(review_fields),
            )
            session.commit()
        return

    with session_factory() as session:
        run = session.scalar(
            select(AgentRun).where(AgentRun.id == task_id).with_for_update()
        )
        if run is None:
            return
        if run.status == "cancelling":
            _finish_job_extraction_cancellation(run)
            session.commit()
            return
        if run.status != "running":
            return
        run.status = "failed"
        run.error_code = failure_code
        run.error_message = failure_message
        run.finished_at = utc_now()
        _append_event(run, "failed", failure_message, code=failure_code)
        session.commit()


def _finish_job_extraction_cancellation(run: AgentRun) -> None:
    """Finalize a cooperative cancellation after the provider call returns."""

    run.status = "cancelled"
    run.finished_at = utc_now()
    run.error_code = None
    run.error_message = None
    _append_event(
        run,
        "cancelled",
        "取消已完成；模型返回内容未保存。",
        step="cancelled",
    )


@router.post("/tasks/{task_id}/cancel", response_model=AgentTaskRead)
def cancel_agent_task(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskRead:
    """Cancel a queued extraction immediately or request cooperative cancellation."""

    enforce_same_origin(request, settings)
    run = _owned_task(session, user, task_id, for_update=True)
    if run.status in {"cancelling", "cancelled"}:
        return _task_read(run)
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = utc_now()
        _append_event(
            run,
            "cancelled",
            "排队任务已取消，模型服务未调用。",
            step="cancelled",
        )
    elif run.status == "running":
        run.status = "cancelling"
        _append_event(
            run,
            "progress",
            "已请求取消；正在等待当前模型请求结束，返回内容不会保存。",
            step="cancel_requested",
        )
    else:
        raise HTTPException(status_code=409, detail="当前岗位解析任务无法取消。")
    session.commit()
    session.refresh(run)
    return _task_read(run)


@router.post(
    "/job-extractions",
    response_model=AgentTaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_job_extraction(
    payload: AgentJobExtractionCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskRead:
    """Queue extraction from text explicitly provided by the signed-in user."""

    enforce_same_origin(request, settings)
    active_count = session.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user.id,
            AgentRun.status.in_(("queued", "running", "cancelling")),
        )
    )
    if active_count and active_count >= MAX_ACTIVE_TASKS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail="当前已有 3 个岗位解析任务在运行，请等待完成后再提交。",
        )

    run = AgentRun(
        user_id=user.id,
        task_type="job_extraction",
        status="queued",
        input_text=payload.text,
        source_url=payload.source_url,
        events=[],
    )
    _append_event(run, "progress", "任务已排队。", step="queued")
    session.add(run)
    session.commit()
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "job_extraction", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _task_read(run)


@router.get("/tasks", response_model=list[AgentTaskRead])
def list_agent_tasks(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    limit: int = 20,
) -> list[AgentTaskRead]:
    """Return the current user's recent task summaries."""

    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 100 之间")
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id, AgentRun.task_type == "job_extraction")
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    return [_task_read(run) for run in runs]


@router.get("/tasks/{task_id}", response_model=AgentTaskRead)
def read_agent_task(
    task_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> AgentTaskRead:
    return _task_read(_owned_task(session, user, task_id))


@router.get("/tasks/{task_id}/source", response_model=AgentTaskSourceRead)
def read_agent_task_source(
    task_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> AgentTaskSourceRead:
    """Return the original text only to its owner while the task is reviewable."""

    run = _owned_task(session, user, task_id)
    if run.status == "confirmed" or not run.input_text:
        raise HTTPException(status_code=409, detail="原文已关联到已保存岗位的来源依据。")
    return AgentTaskSourceRead(
        task_id=run.id, source_url=run.source_url, source_text=run.input_text
    )


@router.get("/tasks/{task_id}/events")
async def stream_agent_task_events(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> StreamingResponse:
    """Replay persisted events and stream new task progress using SSE."""

    _owned_task(session, user, task_id)
    last_event_id = request.headers.get("last-event-id", "0")
    try:
        cursor = max(0, int(last_event_id))
    except ValueError:
        cursor = 0

    async def event_stream() -> AsyncIterator[str]:
        nonlocal cursor
        idle_count = 0
        while True:
            if await request.is_disconnected():
                return
            with request.app.state.session_factory() as event_session:
                run = event_session.scalar(
                    select(AgentRun).where(
                        AgentRun.id == task_id,
                        AgentRun.user_id == user.id,
                    )
                )
                if run is None:
                    return
                events = list(run.events or [])
                current_status = run.status
            new_events = [event for event in events if event["id"] > cursor]
            for event in new_events:
                cursor = event["id"]
                yield (
                    f"id: {cursor}\nevent: {event['event']}\ndata: "
                    f"{json.dumps(event, ensure_ascii=False)}\n\n"
                )
            if current_status in TERMINAL_STATUSES and cursor >= len(events):
                return
            idle_count += 1
            if idle_count % 20 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}/retry", response_model=AgentTaskRead, status_code=202)
def retry_agent_task(
    task_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> AgentTaskRead:
    """Retry a failed task up to the configured per-task attempt limit."""

    enforce_same_origin(request, settings)
    run = _owned_task(session, user, task_id)
    if run.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败的任务可以重试。")
    if run.attempt_count >= MAX_ATTEMPTS:
        raise HTTPException(status_code=409, detail="任务已达到最多 3 次尝试次数。")
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    _append_event(run, "progress", "已安排重试。", step="retry_queued")
    session.commit()
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "job_extraction", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _task_read(run)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_task(
    task_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> Response:
    """Delete an unconfirmed task and its retained source text."""

    enforce_same_origin(request, settings)
    run = _owned_task(session, user, task_id)
    if run.status in {"queued", "running", "cancelling"}:
        raise HTTPException(status_code=409, detail="运行中的任务不能删除，请等待任务结束。")
    if run.status == "confirmed":
        raise HTTPException(status_code=409, detail="请删除关联岗位以一并删除来源依据和任务记录。")
    session.delete(run)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tasks/{task_id}/confirm", response_model=JobPostingRead, status_code=201)
def confirm_job_extraction(
    task_id: UUID,
    payload: JobExtractionConfirm,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Let the owner correct extracted values and save a job with its citations."""

    enforce_same_origin(request, settings)
    run = _owned_task(session, user, task_id)
    if run.status == "confirmed" and run.job_id:
        job = session.scalar(
            select(JobPosting).where(JobPosting.id == run.job_id, JobPosting.user_id == user.id)
        )
        if job is not None:
            company = session.get(Company, job.company_id) if job.company_id else None
            application = session.scalar(
                select(Application).where(
                    Application.job_id == job.id,
                    Application.user_id == user.id,
                )
            )
            return _to_read(job, company, application)
    if run.status != "succeeded" or not run.result:
        raise HTTPException(status_code=409, detail="任务尚未成功完成，暂时不能保存岗位。")

    candidate_fields = {
        key: field.get("value")
        for key, field in run.result.get("fields", {}).items()
    }
    overrides = payload.model_dump(exclude_unset=True)
    candidate_fields.update(overrides)
    source_url = run.source_url
    if "source_url" in overrides:
        source_url = overrides["source_url"]
    job_payload = JobPostingWrite(
        company_name=candidate_fields.get("company_name"),
        title=candidate_fields.get("title"),
        city=candidate_fields.get("city"),
        job_type=candidate_fields.get("job_type"),
        batch=candidate_fields.get("batch"),
        deadline=candidate_fields.get("deadline"),
        education_requirement=candidate_fields.get("education_requirement"),
        required_skills=candidate_fields.get("required_skills") or [],
        description=run.input_text,
        source_url=source_url,
        source_type="agent",
    )
    normalized_source_url = _normalize_source_url(job_payload.source_url)
    if normalized_source_url and session.scalar(
        select(JobPosting.id).where(
            JobPosting.user_id == user.id,
            JobPosting.normalized_source_url == normalized_source_url,
        )
    ):
        raise _duplicate_source_error()

    company = _company_for_payload(session, user, job_payload, preserve_existing_details=True)
    job = JobPosting(
        user_id=user.id,
        company_id=company.id if company else None,
        review_status="verified",
    )
    _assign_job_fields(job, job_payload)
    job.source_captured_at = run.created_at
    session.add(job)
    session.flush()

    evidence = JobSourceEvidence(
        user_id=user.id,
        job_id=job.id,
        agent_run_id=run.id,
        source_url=job_payload.source_url,
        source_text=run.input_text,
        field_evidence=run.result["fields"],
        captured_at=run.created_at,
    )
    session.add(evidence)
    run.job_id = job.id
    run.status = "confirmed"
    run.input_text = ""
    run.finished_at = utc_now()
    _append_event(run, "confirmed", "岗位已保存，原文依据已关联到岗位。", job_id=str(job.id))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if normalized_source_url:
            raise _duplicate_source_error() from None
        raise HTTPException(status_code=409, detail="保存岗位失败，请刷新后重试。") from None
    session.refresh(job)
    if company is not None:
        session.refresh(company)
    return _to_read(job, company, None)


@router.get("/jobs/{job_id}/evidence", response_model=JobSourceEvidenceRead)
def read_job_source_evidence(
    job_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> JobSourceEvidenceRead:
    """Return field evidence only when the requested job belongs to this user."""

    evidence = session.scalar(
        select(JobSourceEvidence)
        .where(JobSourceEvidence.job_id == job_id, JobSourceEvidence.user_id == user.id)
        .order_by(JobSourceEvidence.captured_at.desc())
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="该岗位没有 Agent 来源依据。")
    return JobSourceEvidenceRead.model_validate(evidence)
