"""Owner-scoped, read-only company research backed by an MCP search tool."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mcp.server import MCPServer
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import AgentRun, Company, JobPosting, User, utc_now
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import CompanyResearchRead
from app.services.company_research import (
    CompanyResearchError,
    CompanyResearchFindingCandidate,
    CompanyResearchSummaryProvider,
    call_company_search_tool,
    validate_research_findings,
)

router = APIRouter(prefix="/jobs", tags=["company research"])
logger = logging.getLogger(__name__)
RESEARCH_CACHE_MINUTES = 30
RESEARCH_RATE_LIMIT_PER_HOUR = 10
RESEARCH_STALE_AFTER_DAYS = 7


def _append_research_event(run: AgentRun, event: str, message: str, step: str) -> None:
    events = list(run.events or [])
    events.append(
        {
            "id": len(events) + 1,
            "event": event,
            "message": message,
            "step": step,
            "created_at": utc_now().isoformat(),
        }
    )
    run.events = events
    run.updated_at = utc_now()


def _response_from_run(run: AgentRun, job_id: UUID, company_name: str) -> CompanyResearchRead:
    result = run.result or {}
    try:
        researched_at = datetime.fromisoformat(
            str(result.get("researched_at", run.finished_at or run.created_at)).replace(
                "Z", "+00:00"
            )
        )
        if researched_at.tzinfo is None:
            researched_at = researched_at.replace(tzinfo=timezone.utc)
        return CompanyResearchRead(
            run_id=run.id,
            job_id=job_id,
            company_name=company_name,
            job_title=result.get("job_title"),
            query=str(result.get("query", run.input_text)),
            researched_at=researched_at,
            is_stale=utc_now() - researched_at > timedelta(days=RESEARCH_STALE_AFTER_DAYS),
            summary=str(result.get("summary", "")),
            findings=result.get("findings", []),
            sources=result.get("sources", []),
            no_evidence=bool(result.get("no_evidence", True)),
            warning=result.get("warning"),
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=500, detail="保存的公司研究结果无法读取，请重新研究。"
        ) from None


def _owned_job_and_company(
    session: Session, user: User, job_id: UUID
) -> tuple[JobPosting, Company]:
    job = session.scalar(
        select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if job.company_id is None:
        raise HTTPException(status_code=409, detail="请先在岗位卡片中补充公司名称。")
    company = session.scalar(
        select(Company).where(Company.id == job.company_id, Company.user_id == user.id)
    )
    if company is None:
        raise HTTPException(status_code=409, detail="岗位关联的公司资料不可用，请先检查岗位信息。")
    return job, company


def _mark_research_failed(
    run: AgentRun,
    code: str,
    message: str,
    step: str,
) -> None:
    run.status = "failed"
    run.error_code = code
    run.error_message = message
    run.finished_at = utc_now()
    _append_research_event(run, "failed", message, step)


async def run_company_research_workflow(
    run_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    mcp_server: MCPServer,
    summarizer: CompanyResearchSummaryProvider,
) -> None:
    """Run a persisted, owner-scoped company research task and save its evidence."""

    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if (
            run is None
            or run.task_type != "company_research"
            or run.status != "queued"
        ):
            return

        job = session.scalar(
            select(JobPosting).where(
                JobPosting.id == run.job_id,
                JobPosting.user_id == run.user_id,
            )
        )
        company = (
            session.scalar(
                select(Company).where(
                    Company.id == job.company_id,
                    Company.user_id == run.user_id,
                )
            )
            if job is not None and job.company_id is not None
            else None
        )
        if job is None or company is None:
            _mark_research_failed(
                run,
                "research_target_unavailable",
                "岗位或关联公司已不可用，请检查岗位信息后重试。",
                "load_context",
            )
            session.commit()
            raise HTTPException(
                status_code=409,
                detail="岗位或关联公司已不可用，请检查岗位信息后重试。",
            )

        user_id = run.user_id
        job_id = job.id
        company_name = company.name
        job_title = job.title
        query = run.input_text
        run.status = "running"
        run.attempt_count += 1
        run.error_code = None
        run.error_message = None
        run.finished_at = None
        _append_research_event(
            run,
            "progress",
            "开始搜索公司公开招聘信息。",
            "public_search",
        )
        session.commit()

    try:
        sources, searched_at = await call_company_search_tool(
            mcp_server,
            query,
            count=8,
        )
    except CompanyResearchError as exc:
        with session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is not None and run.status == "running":
                _mark_research_failed(run, exc.code, exc.message, "public_search")
                session.commit()
        logger.warning("Company research run %s failed (%s)", run_id, exc.code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": exc.message, "run_id": str(run_id)},
        ) from None

    findings: list[CompanyResearchFindingCandidate] = []
    warning: str | None = None
    model_name: str | None = None
    if sources:
        with session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "running":
                raise HTTPException(
                    status_code=409,
                    detail="研究任务状态已变化，请刷新后重试。",
                )
            _append_research_event(
                run,
                "progress",
                "已获得公开搜索结果，正在整理来源摘要。",
                "summarize",
            )
            session.commit()
        try:
            candidate, model_name = await summarizer.summarize(
                company_name,
                job_title,
                query,
                sources,
                settings,
            )
            findings = validate_research_findings(candidate, sources)
        except CompanyResearchError as exc:
            warning = exc.message
            error_code = exc.code
        except Exception as exc:
            logger.error(
                "Company research summarization failed for run %s (%s)",
                run_id,
                type(exc).__name__,
            )
            warning = (
                "摘要模型遇到意外错误，已保留搜索来源；"
                "请查看来源或稍后重试。"
            )
            error_code = "research_summary_internal_error"
        else:
            error_code = None
    else:
        error_code = None

    if findings:
        summary = "；".join(finding.claim for finding in findings)
        no_evidence = False
    elif warning:
        summary = (
            "已找到公开来源，但暂时无法生成摘要。"
            "请先查看来源链接，稍后可重新研究。"
        )
        no_evidence = True
    elif sources:
        summary = (
            "已找到公开来源，但其中没有足够的可核验证据形成事实摘要。"
            "请打开来源人工检查。"
        )
        no_evidence = True
    else:
        summary = (
            "公开搜索暂未返回结果。请稍后重试，"
            "或直接打开公司招聘主页核对。"
        )
        no_evidence = True

    result = {
        "company_name": company_name,
        "query": query,
        "job_title": job_title,
        "researched_at": searched_at.isoformat(),
        "summary": summary,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "sources": [source.model_dump(mode="json") for source in sources],
        "no_evidence": no_evidence,
        "warning": warning,
        "search_provider": "tavily_search",
    }
    with session_factory() as session:
        current_run = session.get(AgentRun, run_id)
        current_job = session.scalar(
            select(JobPosting).where(
                JobPosting.id == job_id,
                JobPosting.user_id == user_id,
            )
        )
        current_company = (
            session.scalar(
                select(Company).where(
                    Company.id == current_job.company_id,
                    Company.user_id == user_id,
                )
            )
            if current_job is not None and current_job.company_id is not None
            else None
        )
        if current_run is None:
            raise HTTPException(status_code=404, detail="公司研究任务已被删除。")
        if current_job is None or current_company is None or current_company.name != company_name:
            _mark_research_failed(
                current_run,
                "research_target_changed",
                "岗位或公司信息在研究期间发生变化，请重新发起研究。",
                "validate_target",
            )
            session.commit()
            raise HTTPException(
                status_code=409,
                detail=(
                    "岗位或公司信息在研究期间发生变化，"
                    "请重新发起研究。"
                ),
            )

        current_run.result = result
        current_run.status = "succeeded"
        current_run.error_code = error_code
        current_run.error_message = warning
        current_run.model_name = model_name
        current_run.finished_at = utc_now()
        _append_research_event(
            current_run,
            "completed",
            "公司研究完成，结果保留来源链接和可核验引用。",
            "completed",
        )
        session.commit()


@router.post(
    "/{job_id}/research",
    response_model=CompanyResearchRead,
    status_code=status.HTTP_200_OK,
)
async def research_company_for_job(
    job_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    refresh: bool = False,
) -> CompanyResearchRead:
    """Search public recruitment information and retain a cited research run."""

    enforce_same_origin(request, settings)
    job, company = _owned_job_and_company(session, user, job_id)
    cached_run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.user_id == user.id,
            AgentRun.job_id == job.id,
            AgentRun.task_type == "company_research",
            AgentRun.status == "succeeded",
            AgentRun.result.is_not(None),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if cached_run is not None and cached_run.result.get("company_name") == company.name:
        cached_response = _response_from_run(cached_run, job.id, company.name)
        if not refresh and utc_now() - cached_response.researched_at <= timedelta(
            minutes=RESEARCH_CACHE_MINUTES
        ):
            return cached_response

    recent_runs = session.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user.id,
            AgentRun.task_type == "company_research",
            AgentRun.created_at >= utc_now() - timedelta(hours=1),
        )
    ) or 0
    if recent_runs >= RESEARCH_RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "research_rate_limited",
                "message": "公司研究每个账户每小时最多 10 次，请稍后再试。",
            },
        )

    query_parts = [f'"{company.name}"', "招聘 校招 官方"]
    if job.title:
        query_parts.append(job.title)
    query = " ".join(query_parts)[:600]

    run = AgentRun(
        user_id=user.id,
        job_id=job.id,
        task_type="company_research",
        status="queued",
        input_text=query,
        events=[],
        attempt_count=0,
    )
    _append_research_event(
        run,
        "progress",
        "已创建待执行的只读公开搜索任务。",
        "queued",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    await request.app.state.agent_workflow_graph.ainvoke(
        {
            "task_type": "company_research",
            "operation": "run",
            "run_id": run.id,
        },
        version="v2",
    )
    session.expire_all()
    completed_run = session.get(AgentRun, run.id)
    if completed_run is None:
        raise HTTPException(status_code=404, detail="公司研究任务已被删除。")
    if completed_run.status != "succeeded":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": completed_run.error_code or "research_workflow_incomplete",
                "message": completed_run.error_message
                or "公司研究未能完成，请稍后重试。",
                "run_id": str(completed_run.id),
            },
        )
    return _response_from_run(completed_run, job.id, company.name)


@router.get("/{job_id}/research", response_model=CompanyResearchRead)
def read_latest_company_research(
    job_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> CompanyResearchRead:
    """Return the latest successful public research run for this owned job."""

    _, company = _owned_job_and_company(session, user, job_id)
    run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.user_id == user.id,
            AgentRun.job_id == job_id,
            AgentRun.task_type == "company_research",
            AgentRun.status == "succeeded",
            AgentRun.result.is_not(None),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="该岗位还没有公司研究结果。")
    if run.result.get("company_name") != company.name:
        raise HTTPException(status_code=404, detail="公司信息已更新，请重新生成研究结果。")
    return _response_from_run(run, job_id, company.name)
