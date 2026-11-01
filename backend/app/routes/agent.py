"""Owner-scoped job extraction tasks, progress streaming, retry, and confirmation."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import (
    AgentRun,
    Application,
    Company,
    JobPosting,
    JobSourceEvidence,
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
    AgentTaskRead,
    AgentTaskSourceRead,
    JobExtractionConfirm,
    JobPostingRead,
    JobPostingWrite,
    JobSourceEvidenceRead,
)
from app.services.job_extraction import JobExtractionError, JobExtractionProvider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])
MAX_ATTEMPTS = 3
MAX_ACTIVE_TASKS_PER_USER = 3
TERMINAL_STATUSES = {"succeeded", "failed", "confirmed"}


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


def _owned_task(session: Session, user: User, task_id: UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun).where(AgentRun.id == task_id, AgentRun.user_id == user.id)
    )
    if run is None or run.task_type != "job_extraction":
        raise HTTPException(status_code=404, detail="Agent 任务不存在")
    return run


async def run_job_extraction(
    task_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: JobExtractionProvider,
) -> None:
    """Run one persisted task and record each transition before continuing."""

    with session_factory() as session:
        run = session.get(AgentRun, task_id)
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
            run = session.get(AgentRun, task_id)
            if run is None or run.status != "running":
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
        run = session.get(AgentRun, task_id)
        if run is None or run.status != "running":
            return
        run.status = "failed"
        run.error_code = failure_code
        run.error_message = failure_message
        run.finished_at = utc_now()
        _append_event(run, "failed", failure_message, code=failure_code)
        session.commit()


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
            AgentRun.status.in_(("queued", "running")),
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
        run_job_extraction,
        run.id,
        request.app.state.session_factory,
        settings,
        request.app.state.job_extraction_provider,
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
        run_job_extraction,
        run.id,
        request.app.state.session_factory,
        settings,
        request.app.state.job_extraction_provider,
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
    if run.status in {"queued", "running"}:
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
