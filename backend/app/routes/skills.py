"""Owner-scoped versioned skill workflows and approval-gated local writes."""

import hashlib
import json
import logging
from datetime import timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import (
    AgentRun,
    ApplicationPrepPack,
    ApprovalRequest,
    AuditEvent,
    CandidateProfile,
    Company,
    JobPosting,
    ResumeVersion,
    User,
    utc_now,
)
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    ApprovalRequestRead,
    ApplicationPrepPackRead,
    AuditEventRead,
    SkillCatalogItem,
    SkillDraftRead,
    SkillRunCreate,
    SkillRunRead,
)
from app.services.skills import (
    SKILL_BY_ID,
    SKILLS,
    SkillDraftCandidate,
    SkillProvider,
    SkillServiceError,
    source_text_for_model,
    validate_skill_draft,
)
from app.services.skill_graph import (
    SkillWorkflowState,
    build_skill_graph,
    open_skill_checkpointer,
)

router = APIRouter(prefix="/skills", tags=["skills"])
logger = logging.getLogger(__name__)
MAX_ACTIVE_SKILL_RUNS = 3
MAX_SKILL_ATTEMPTS = 3
APPROVAL_TTL = timedelta(minutes=30)
SAVE_PREP_PACK_ACTION = "save_application_prep_pack"


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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


def _skill_run_read(run: AgentRun) -> SkillRunRead:
    if run.skill_id not in SKILL_BY_ID or run.skill_version is None or run.job_id is None:
        raise HTTPException(status_code=500, detail="求职 Skill 任务记录不完整。")
    result = (
        SkillDraftRead.model_validate(run.result)
        if run.result and run.status == "succeeded"
        else None
    )
    return SkillRunRead(
        id=run.id,
        skill_id=run.skill_id,  # type: ignore[arg-type]
        skill_version=run.skill_version,
        job_id=run.job_id,
        status=run.status,  # type: ignore[arg-type]
        result=result,
        events=list(run.events or []),
        error_code=run.error_code,
        error_message=run.error_message,
        model_name=run.model_name,
        attempt_count=run.attempt_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
    )


def _owned_skill_run(session: Session, user: User, run_id: UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user.id,
            AgentRun.task_type == "skill_workflow",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="求职 Skill 任务不存在。")
    return run


def _owned_approval(session: Session, user: User, approval_id: UUID) -> ApprovalRequest:
    approval = session.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.user_id == user.id,
        )
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="审批记录不存在。")
    return approval


def _profile_payload(profile: CandidateProfile | None) -> dict[str, object] | None:
    if profile is None:
        return None
    return {
        "graduation_year": profile.graduation_year,
        "education": profile.education,
        "major": profile.major,
        "target_roles": profile.target_roles,
        "target_cities": profile.target_cities,
        "industries": profile.industries,
        "skills": profile.skills,
    }


def _job_payload(job: JobPosting, company: Company | None) -> dict[str, object]:
    return {
        "company_name": company.name if company else None,
        "industry": company.industry if company else None,
        "title": job.title,
        "city": job.city,
        "job_type": job.job_type,
        "batch": job.batch,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "education_requirement": job.education_requirement,
        "required_skills": job.required_skills,
        "source_url": job.source_url,
    }


def _context_for_run(
    session: Session, run: AgentRun
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    list[str],
    list[dict[str, str | None]],
    bool,
]:
    if run.job_id is None or run.skill_id not in SKILL_BY_ID:
        raise SkillServiceError("skill_context_missing", "任务关联岗位不存在，请重新创建任务。")
    payload = json.loads(run.input_text)
    skill = SKILL_BY_ID[run.skill_id]
    job = session.scalar(
        select(JobPosting).where(JobPosting.id == run.job_id, JobPosting.user_id == run.user_id)
    )
    if job is None:
        raise SkillServiceError("skill_job_missing", "关联岗位已删除，请选择其他岗位。")
    company = None
    if job.company_id:
        company = session.scalar(
            select(Company).where(
                Company.id == job.company_id,
                Company.user_id == run.user_id,
            )
        )
    job_data = _job_payload(job, company)
    profile = session.scalar(
        select(CandidateProfile).where(CandidateProfile.user_id == run.user_id)
    )
    profile_data = _profile_payload(profile)
    sources: list[dict[str, str | None]] = []
    truncated = False

    job_text = job.description or "\n".join(
        f"{key}: {value}"
        for key, value in job_data.items()
        if value not in (None, [], "")
    )
    if job_text:
        was_truncated = len(job_text) > 18_000
        job_text, _ = source_text_for_model(job_text[:18_000])
        truncated = truncated or was_truncated
        sources.append(
            {
                "id": "job-description",
                "label": f"{company.name + ' ' if company else ''}{job.title or '岗位'}招聘信息",
                "url": job.source_url,
                "text": job_text,
            }
        )

    resume: ResumeVersion | None = None
    if run.resume_version_id is not None:
        resume = session.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == run.resume_version_id,
                ResumeVersion.user_id == run.user_id,
                ResumeVersion.confirmed_at.is_not(None),
            )
        )
    if skill.needs_resume and resume is None:
        raise SkillServiceError(
            "confirmed_resume_required", "该 Skill 需要一份已确认的简历，请先到个人档案确认简历。"
        )
    if resume is not None:
        was_truncated = len(resume.extracted_text) > 24_000
        resume_text, _ = source_text_for_model(resume.extracted_text[:24_000])
        truncated = truncated or was_truncated
        sources.append(
            {
                "id": "confirmed-resume",
                "label": f"已确认简历：{resume.filename}",
                "url": None,
                "text": resume_text,
            }
        )

    if profile_data:
        raw_profile_text = json.dumps(profile_data, ensure_ascii=False)
        was_truncated = len(raw_profile_text) > 6000
        profile_text, _ = source_text_for_model(raw_profile_text[:6000])
        truncated = truncated or was_truncated
        sources.append(
            {"id": "candidate-profile", "label": "个人档案", "url": None, "text": profile_text}
        )

    research_run_id = payload.get("research_run_id")
    research_run: AgentRun | None = None
    if research_run_id or skill.id in {"interview_prep", "application_prep_pack"}:
        try:
            research_uuid = UUID(str(research_run_id)) if research_run_id else None
        except ValueError:
            research_uuid = None
        if research_uuid is not None:
            research_run = session.scalar(
                select(AgentRun).where(
                    AgentRun.id == research_uuid,
                    AgentRun.user_id == run.user_id,
                    AgentRun.job_id == job.id,
                    AgentRun.task_type == "company_research",
                    AgentRun.status == "succeeded",
                )
            )
        else:
            research_run = session.scalar(
                select(AgentRun)
                .where(
                    AgentRun.user_id == run.user_id,
                    AgentRun.job_id == job.id,
                    AgentRun.task_type == "company_research",
                    AgentRun.status == "succeeded",
                )
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(1)
            )
    if research_run is not None and (research_run.result or {}).get("company_name") != (
        company.name if company else None
    ):
        research_run = None
    if skill.needs_research and research_run is None:
        raise SkillServiceError(
            "company_research_required",
            "该 Skill 需要已有的公司研究结果，请先在岗位卡片运行公司研究。",
        )
    if research_run is not None:
        research_sources = (research_run.result or {}).get("sources", [])
        if isinstance(research_sources, list):
            for index, item in enumerate(research_sources[:8]):
                if not isinstance(item, dict):
                    continue
                excerpt = item.get("excerpt")
                source_id = item.get("source_id")
                if not isinstance(excerpt, str) or not excerpt.strip() or not isinstance(source_id, str):
                    continue
                excerpt = excerpt.strip()[:2500]
                sources.append(
                    {
                        "id": f"research:{source_id}",
                        "label": str(item.get("title") or f"公司公开来源 {index + 1}")[:500],
                        "url": str(item.get("url"))[:2048] if item.get("url") else None,
                        "text": excerpt,
                    }
                )

    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        questions = []
    return job_data, profile_data, questions, sources, truncated


class _SkillGraphNodes:
    """Database and model operations called by named LangGraph nodes."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        provider: SkillProvider,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.provider = provider

    def _mark_failed(
        self,
        session: Session,
        run: AgentRun,
        code: str,
        message: str,
        step: str,
    ) -> None:
        run.status = "failed"
        run.error_code = code
        run.error_message = message
        run.finished_at = utc_now()
        _append_event(run, "failed", message, code=code, step=step)

    def validate_context(self, state: SkillWorkflowState) -> dict[str, object]:
        """Check required user-owned context without placing PII in graph state."""

        run_id = UUID(state["run_id"])
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "queued":
                return {"outcome": "cancelled"}
            run.status = "running"
            run.attempt_count += 1
            run.error_code = None
            run.error_message = None
            run.finished_at = None
            _append_event(
                run,
                "progress",
                "正在检查岗位、简历与研究资料权限。",
                step="validate_context",
            )
            try:
                _context_for_run(session, run)
            except SkillServiceError as exc:
                self._mark_failed(session, run, exc.code, exc.message, "validate_context")
                session.commit()
                return {"outcome": "failed"}
            session.commit()
        return {"outcome": "ready"}

    async def generate_draft(self, state: SkillWorkflowState) -> dict[str, object]:
        """Generate a structured candidate and keep it private until evidence checks."""

        run_id = UUID(state["run_id"])
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "running":
                return {"outcome": "cancelled"}
            try:
                job_data, profile_data, questions, sources, _ = _context_for_run(session, run)
            except SkillServiceError as exc:
                self._mark_failed(session, run, exc.code, exc.message, "generate_draft")
                session.commit()
                return {"outcome": "failed"}
            skill = SKILL_BY_ID[run.skill_id or ""]
            _append_event(run, "progress", "正在调用模型生成结构化草稿。", step="generate_draft")
            session.commit()

        try:
            candidate, model_name = await self.provider.generate(
                skill,
                job=job_data,
                profile=profile_data,
                questions=questions,
                sources=sources,
                settings=self.settings,
            )
        except SkillServiceError as exc:
            failure_code, failure_message = exc.code, exc.message
        except Exception as exc:  # Never log prompts, resume text, keys, or provider bodies.
            logger.error("Skill graph %s failed (%s)", run_id, type(exc).__name__)
            failure_code = "skill_workflow_error"
            failure_message = "求职草稿生成遇到意外错误，请检查配置后重试。"
        else:
            with self.session_factory() as session:
                run = session.get(AgentRun, run_id)
                if run is None or run.status != "running":
                    return {"outcome": "cancelled"}
                run.result = candidate.model_dump(mode="json")
                run.model_name = model_name
                _append_event(
                    run,
                    "progress",
                    "模型已返回结构化草稿，正在校验引用证据。",
                    step="generate_draft",
                )
                session.commit()
            return {"outcome": "generated"}

        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is not None and run.status == "running":
                self._mark_failed(
                    session,
                    run,
                    failure_code,
                    failure_message,
                    "generate_draft",
                )
                session.commit()
        return {"outcome": "failed"}

    def validate_evidence(self, state: SkillWorkflowState) -> dict[str, object]:
        """Verify model citations against original sources and persist the safe draft."""

        run_id = UUID(state["run_id"])
        with self.session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "running" or not run.result:
                return {"outcome": "cancelled"}
            try:
                _, _, _, sources, source_truncated = _context_for_run(session, run)
                candidate = SkillDraftCandidate.model_validate(run.result)
                draft = validate_skill_draft(candidate, sources)
                if source_truncated:
                    draft.warnings.append(
                        "部分超长资料仅使用前段生成，请在保存前检查完整原文。"
                    )
            except (SkillServiceError, ValueError) as exc:
                if isinstance(exc, SkillServiceError):
                    code, message = exc.code, exc.message
                else:
                    code, message = (
                        "invalid_skill_candidate",
                        "模型草稿未通过结构校验，请重新运行。",
                    )
                self._mark_failed(session, run, code, message, "validate_evidence")
                session.commit()
                return {"outcome": "failed"}

            run.result = draft.model_dump(mode="json")
            run.status = "succeeded"
            run.finished_at = utc_now()
            requires_approval = run.skill_id == "application_prep_pack"
            _append_event(
                run,
                "progress",
                "模型结果已通过结构和引用校验。",
                step="validate_evidence",
            )
            _append_event(
                run,
                "completed",
                "求职草稿已生成；保存前请逐项检查内容和引用。",
                step="completed",
            )
            session.commit()
        return {"outcome": "succeeded", "requires_approval": requires_approval}

    def execute_local_save(self, state: SkillWorkflowState) -> dict[str, object]:
        """Revalidate approval and perform the graph's sole allowlisted write."""

        run_id = UUID(state["run_id"])
        try:
            approval_id = UUID(state["approval_id"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="审批关联信息无效。") from exc

        with self.session_factory() as session:
            approval = session.get(ApprovalRequest, approval_id)
            run = session.get(AgentRun, run_id)
            if (
                approval is None
                or run is None
                or approval.agent_run_id != run.id
                or approval.user_id != run.user_id
            ):
                raise HTTPException(status_code=404, detail="审批或求职任务不存在。")

            existing_pack = session.scalar(
                select(ApplicationPrepPack).where(
                    ApplicationPrepPack.user_id == run.user_id,
                    ApplicationPrepPack.agent_run_id == run.id,
                )
            )
            if existing_pack is not None and approval.status == "executed":
                return {"outcome": "executed", "pack_id": str(existing_pack.id)}
            if approval.status != "approved":
                raise HTTPException(status_code=409, detail="只有已批准的操作可以执行。")

            now = utc_now()
            job = session.scalar(
                select(JobPosting).where(
                    JobPosting.id == approval.job_id,
                    JobPosting.user_id == run.user_id,
                )
            )
            payload_hash, approval_hash = _expected_approval_hash(approval, run)
            if (
                _utc(approval.expires_at) <= now
                or job is None
                or run.status != "succeeded"
                or run.skill_id != "application_prep_pack"
                or approval.action_type != SAVE_PREP_PACK_ACTION
                or payload_hash != approval.payload_hash
                or approval_hash != approval.approval_hash
            ):
                approval.status = (
                    "expired" if _utc(approval.expires_at) <= now else "invalidated"
                )
                approval.updated_at = now
                _audit(
                    session,
                    user_id=run.user_id,
                    approval_id=approval.id,
                    action=(
                        "approval_expired"
                        if approval.status == "expired"
                        else "approval_invalidated"
                    ),
                    entity_type="application_prep_pack",
                    entity_id=run.id,
                    details={"reason": "execution_revalidation_failed"},
                )
                session.commit()
                raise HTTPException(status_code=409, detail="草稿、目标或审批已变化，不能保存。")

            pack = ApplicationPrepPack(
                user_id=run.user_id,
                job_id=job.id,
                agent_run_id=run.id,
                skill_id=run.skill_id,
                skill_version=run.skill_version or "",
                content=run.result or {},
                created_at=now,
            )
            session.add(pack)
            approval.status = "executed"
            approval.executed_at = now
            approval.updated_at = now
            _audit(
                session,
                user_id=run.user_id,
                approval_id=approval.id,
                action="application_prep_pack_saved",
                entity_type="application_prep_pack",
                entity_id=run.id,
                details={"job_id": str(job.id), "skill_version": run.skill_version or ""},
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_pack = session.scalar(
                    select(ApplicationPrepPack).where(
                        ApplicationPrepPack.user_id == run.user_id,
                        ApplicationPrepPack.agent_run_id == run.id,
                    )
                )
                if existing_pack is None:
                    raise HTTPException(
                        status_code=409,
                        detail="准备包保存冲突，请刷新后重试。",
                    ) from None
                return {"outcome": "executed", "pack_id": str(existing_pack.id)}
            return {"outcome": "executed", "pack_id": str(pack.id)}


def _skill_thread_id(run_id: UUID, attempt_count: int) -> str:
    return f"{run_id}:{attempt_count}"


async def _invoke_skill_graph(
    run_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: SkillProvider,
    *,
    resume: dict[str, str] | None = None,
    checkpoint_saver=None,
) -> dict[str, object]:
    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="求职 Skill 任务不存在。")
        attempt_count = run.attempt_count
        if resume is None:
            attempt_count += 1

    async with open_skill_checkpointer(
        settings.database_url,
        settings.storage_dir,
        checkpoint_saver,
    ) as checkpointer:
        graph = build_skill_graph(
            checkpointer,
            _SkillGraphNodes(session_factory, settings, provider),
        )
        graph_input = Command(resume=resume) if resume is not None else {"run_id": str(run_id)}
        graph_result = await graph.ainvoke(
            graph_input,
            {"configurable": {"thread_id": _skill_thread_id(run_id, attempt_count)}},
            durability="sync",
            version="v2",
        )
        if graph_result.interrupts:
            if isinstance(graph_result.value, dict):
                return {
                    **graph_result.value,
                    "__interrupt__": list(graph_result.interrupts),
                }
            return {"__interrupt__": list(graph_result.interrupts)}
        return graph_result.value


async def run_skill_workflow(
    run_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: SkillProvider,
    checkpoint_saver=None,
) -> dict[str, object] | None:
    """Invoke LangGraph for a new run and checkpoint it under a stable attempt ID."""

    try:
        return await _invoke_skill_graph(
            run_id,
            session_factory,
            settings,
            provider,
            checkpoint_saver=checkpoint_saver,
        )
    except Exception as exc:
        logger.error("Skill graph %s could not start (%s)", run_id, type(exc).__name__)
        with session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is not None and run.status in {"queued", "running"}:
                _SkillGraphNodes(session_factory, settings, provider)._mark_failed(
                    session,
                    run,
                    "skill_graph_error",
                    "求职工作流启动失败，请检查服务后重试。",
                    "graph_start",
                )
                session.commit()
        return None


async def resume_skill_workflow(
    run_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    provider: SkillProvider,
    *,
    approval_id: UUID,
    decision: str,
    checkpoint_saver=None,
) -> dict[str, object]:
    """Resume a paused LangGraph thread with a validated human decision."""

    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="审批决定无效。")
    try:
        return await _invoke_skill_graph(
            run_id,
            session_factory,
            settings,
            provider,
            resume={"approval_id": str(approval_id), "decision": decision},
            checkpoint_saver=checkpoint_saver,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Skill graph %s could not resume (%s)", run_id, type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="求职工作流无法恢复，请刷新任务状态后重试。",
        ) from None


@router.get("", response_model=list[SkillCatalogItem])
def list_skills(
    _: Annotated[User, Depends(current_user_dependency)],
) -> list[SkillCatalogItem]:
    """List the immutable, versioned workflow templates available to the owner."""

    return [skill.catalog_item() for skill in SKILLS]


@router.post("/runs", response_model=SkillRunRead, status_code=status.HTTP_202_ACCEPTED)
def create_skill_run(
    payload: SkillRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> SkillRunRead:
    """Persist and launch a skill run; duplicate submissions are idempotent."""

    enforce_same_origin(request, settings)
    skill = SKILL_BY_ID[payload.skill_id]
    job = session.scalar(
        select(JobPosting).where(JobPosting.id == payload.job_id, JobPosting.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在。")

    resume = None
    if skill.needs_resume:
        resume = session.scalar(
            select(ResumeVersion)
            .where(
                ResumeVersion.user_id == user.id,
                ResumeVersion.confirmed_at.is_not(None),
            )
            .order_by(ResumeVersion.created_at.desc(), ResumeVersion.id.desc())
            .limit(1)
        )
        if resume is None:
            raise HTTPException(
                status_code=409,
                detail="该 Skill 需要已确认的简历，请先到个人档案确认简历。",
            )

    research_run = None
    if skill.needs_research:
        research_run = session.scalar(
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
        if research_run is None:
            raise HTTPException(
                status_code=409,
                detail="该 Skill 需要已有的公司研究结果，请先在岗位卡片运行公司研究。",
            )

    run_input = {
        "questions": payload.questions,
        "research_run_id": str(research_run.id) if research_run else None,
    }
    request_hash = _canonical_hash(
        {
            "skill_id": skill.id,
            "skill_version": skill.version,
            "job_id": str(job.id),
            "resume_id": str(resume.id) if resume else None,
            **run_input,
        }
    )
    existing = session.scalar(
        select(AgentRun).where(
            AgentRun.user_id == user.id,
            AgentRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于其他任务，请重新提交。")
        response.status_code = status.HTTP_200_OK
        return _skill_run_read(existing)

    active_count = session.scalar(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == user.id,
            AgentRun.status.in_(("queued", "running")),
        )
    ) or 0
    if active_count >= MAX_ACTIVE_SKILL_RUNS:
        raise HTTPException(status_code=429, detail="当前已有 3 个 Agent 任务运行，请稍后再试。")

    run = AgentRun(
        user_id=user.id,
        job_id=job.id,
        resume_version_id=resume.id if resume else None,
        task_type="skill_workflow",
        skill_id=skill.id,
        skill_version=skill.version,
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        status="queued",
        input_text=json.dumps(run_input, ensure_ascii=False, sort_keys=True),
        events=[],
    )
    _append_event(run, "progress", "求职 Skill 任务已排队。", step="queued")
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
        if existing is None or existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="求职任务创建冲突，请重新提交。") from None
        response.status_code = status.HTTP_200_OK
        return _skill_run_read(existing)
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "skill_workflow", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _skill_run_read(run)


@router.get("/runs", response_model=list[SkillRunRead])
def list_skill_runs(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    limit: int = 20,
) -> list[SkillRunRead]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 100 之间。")
    runs = session.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id, AgentRun.task_type == "skill_workflow")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    return [_skill_run_read(run) for run in runs]


@router.get("/runs/{run_id}", response_model=SkillRunRead)
def read_skill_run(
    run_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> SkillRunRead:
    return _skill_run_read(_owned_skill_run(session, user, run_id))


@router.post("/runs/{run_id}/retry", response_model=SkillRunRead, status_code=202)
def retry_skill_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> SkillRunRead:
    enforce_same_origin(request, settings)
    run = _owned_skill_run(session, user, run_id)
    if run.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败的求职任务可以重试。")
    if run.attempt_count >= MAX_SKILL_ATTEMPTS:
        raise HTTPException(status_code=409, detail="任务已达到最多 3 次尝试次数。")
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    _append_event(run, "progress", "已安排求职任务重试。", step="retry_queued")
    session.commit()
    session.refresh(run)
    background_tasks.add_task(
        request.app.state.agent_workflow_graph.ainvoke,
        {"task_type": "skill_workflow", "operation": "run", "run_id": run.id},
        version="v2",
    )
    return _skill_run_read(run)


@router.post("/runs/{run_id}/cancel", response_model=SkillRunRead)
def cancel_skill_run(
    run_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> SkillRunRead:
    enforce_same_origin(request, settings)
    run = _owned_skill_run(session, user, run_id)
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="只有排队中或运行中的任务可以取消。")
    run.status = "cancelled"
    run.finished_at = utc_now()
    _append_event(run, "cancelled", "用户已取消求职任务。", step="cancelled")
    session.commit()
    return _skill_run_read(run)


def _approval_read(approval: ApprovalRequest) -> ApprovalRequestRead:
    return ApprovalRequestRead.model_validate(approval)


def _audit(
    session: Session,
    *,
    user_id: UUID,
    approval_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | str,
    details: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            user_id=user_id,
            approval_id=approval_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
    )


def _expected_approval_hash(
    approval: ApprovalRequest, run: AgentRun
) -> tuple[str, str]:
    payload_hash = _canonical_hash(run.result)
    approval_hash = _canonical_hash(
        {
            "action_type": approval.action_type,
            "approval_id": str(approval.id),
            "agent_run_id": str(run.id),
            "expires_at": _utc(approval.expires_at).isoformat(),
            "job_id": str(approval.job_id),
            "payload_hash": payload_hash,
            "skill_id": run.skill_id,
            "skill_version": run.skill_version,
            "summary": approval.summary,
        }
    )
    return payload_hash, approval_hash


@router.get("/approvals", response_model=list[ApprovalRequestRead])
def list_approvals(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[ApprovalRequestRead]:
    approvals = session.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.user_id == user.id)
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .limit(100)
    )
    return [_approval_read(approval) for approval in approvals]


@router.post("/runs/{run_id}/approval", response_model=ApprovalRequestRead, status_code=201)
def request_prep_pack_approval(
    run_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ApprovalRequestRead:
    """Create an expiring approval for the exact application-prep draft shown to the user."""

    enforce_same_origin(request, settings)
    run = _owned_skill_run(session, user, run_id)
    if run.status != "succeeded" or not run.result or run.skill_id != "application_prep_pack":
        raise HTTPException(status_code=409, detail="只有成功的申请准备包可以请求保存审批。")
    if run.job_id is None:
        raise HTTPException(status_code=409, detail="任务关联岗位已删除，无法保存准备包。")
    job = session.scalar(
        select(JobPosting).where(JobPosting.id == run.job_id, JobPosting.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="关联岗位不存在。")

    existing = session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.user_id == user.id,
            ApprovalRequest.agent_run_id == run.id,
            ApprovalRequest.action_type == SAVE_PREP_PACK_ACTION,
        )
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .limit(1)
    )
    company = (
        session.scalar(
            select(Company).where(Company.id == job.company_id, Company.user_id == user.id)
        )
        if job.company_id
        else None
    )
    target_label = " · ".join(item for item in (company.name if company else None, job.title) if item)
    summary = f"保存「{target_label or '当前岗位'}」的申请准备包到本地工作台；不会提交到招聘网站。"
    payload_hash = _canonical_hash(run.result)
    if existing is not None:
        if existing.status == "executed":
            return _approval_read(existing)
        if existing.status in {"rejected", "invalidated"}:
            raise HTTPException(
                status_code=409,
                detail="该准备包的审批已结束或失效，请重新运行申请准备包后再申请保存。",
            )
        if existing.status in {"pending", "approved"}:
            current_hash = _canonical_hash(
                {
                    "action_type": existing.action_type,
                    "approval_id": str(existing.id),
                    "agent_run_id": str(run.id),
                    "expires_at": _utc(existing.expires_at).isoformat(),
                    "job_id": str(existing.job_id),
                    "payload_hash": payload_hash,
                    "skill_id": run.skill_id,
                    "skill_version": run.skill_version,
                    "summary": summary,
                }
            )
            if _utc(existing.expires_at) > utc_now() and existing.payload_hash == payload_hash and current_hash == existing.approval_hash:
                return _approval_read(existing)
            existing.status = "expired" if _utc(existing.expires_at) <= utc_now() else "invalidated"
            existing.updated_at = utc_now()
            _audit(
                session,
                user_id=user.id,
                approval_id=existing.id,
                action="approval_expired" if existing.status == "expired" else "approval_invalidated",
                entity_type="application_prep_pack",
                entity_id=run.id,
                details={"reason": "expired" if existing.status == "expired" else "content_or_target_changed"},
            )
            session.commit()

    approval = ApprovalRequest(
        user_id=user.id,
        agent_run_id=run.id,
        job_id=job.id,
        action_type=SAVE_PREP_PACK_ACTION,
        summary=summary,
        payload_hash=payload_hash,
        approval_hash="pending",
        status="pending",
        expires_at=utc_now() + APPROVAL_TTL,
    )
    session.add(approval)
    session.flush()
    _, approval_hash = _expected_approval_hash(approval, run)
    approval.approval_hash = approval_hash
    _audit(
        session,
        user_id=user.id,
        approval_id=approval.id,
        action="approval_requested",
        entity_type="application_prep_pack",
        entity_id=run.id,
        details={"action_type": SAVE_PREP_PACK_ACTION, "approval_hash": approval_hash},
    )
    session.commit()
    session.refresh(approval)
    return _approval_read(approval)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRequestRead)
def approve_request(
    approval_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ApprovalRequestRead:
    """Approve only the exact pending action while it is still valid and unexpired."""

    enforce_same_origin(request, settings)
    approval = _owned_approval(session, user, approval_id)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="该审批不处于待确认状态。")
    now = utc_now()
    if _utc(approval.expires_at) <= now:
        approval.status = "expired"
        approval.updated_at = now
        _audit(
            session,
            user_id=user.id,
            approval_id=approval.id,
            action="approval_expired",
            entity_type="application_prep_pack",
            entity_id=approval.agent_run_id,
            details={"approval_hash": approval.approval_hash},
        )
        session.commit()
        raise HTTPException(status_code=409, detail="审批已过期，请重新生成并检查草稿。")
    run = _owned_skill_run(session, user, approval.agent_run_id)
    payload_hash, approval_hash = _expected_approval_hash(approval, run)
    job = session.scalar(
        select(JobPosting).where(
            JobPosting.id == approval.job_id,
            JobPosting.user_id == user.id,
        )
    )
    if (
        job is None
        or run.status != "succeeded"
        or payload_hash != approval.payload_hash
        or approval_hash != approval.approval_hash
    ):
        approval.status = "invalidated"
        approval.updated_at = now
        _audit(
            session,
            user_id=user.id,
            approval_id=approval.id,
            action="approval_invalidated",
            entity_type="application_prep_pack",
            entity_id=approval.agent_run_id,
            details={"reason": "approved_content_or_target_changed"},
        )
        session.commit()
        raise HTTPException(status_code=409, detail="草稿或目标岗位已变化，审批已失效。")

    approval.status = "approved"
    approval.approved_at = now
    approval.updated_at = now
    _audit(
        session,
        user_id=user.id,
        approval_id=approval.id,
        action="approval_approved",
        entity_type="application_prep_pack",
        entity_id=approval.agent_run_id,
        details={"approval_hash": approval.approval_hash},
    )
    session.commit()
    session.refresh(approval)
    return _approval_read(approval)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalRequestRead)
async def reject_request(
    approval_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ApprovalRequestRead:
    enforce_same_origin(request, settings)
    approval = _owned_approval(session, user, approval_id)
    if approval.status == "rejected":
        return _approval_read(approval)
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="该审批不处于待确认状态。")
    if approval.status == "pending":
        now = utc_now()
        expired = _utc(approval.expires_at) <= now
        approval.status = "expired" if expired else "rejected"
        approval.updated_at = now
        _audit(
            session,
            user_id=user.id,
            approval_id=approval.id,
            action="approval_expired" if expired else "approval_rejected",
            entity_type="application_prep_pack",
            entity_id=approval.agent_run_id,
            details={"approval_hash": approval.approval_hash},
        )
        session.commit()
        if expired:
            raise HTTPException(status_code=409, detail="审批已过期，请重新申请并检查草稿。")
        session.refresh(approval)

    run = _owned_skill_run(session, user, approval.agent_run_id)
    await request.app.state.agent_workflow_graph.ainvoke(
        {
            "task_type": "skill_workflow",
            "operation": "resume",
            "run_id": run.id,
            "approval_id": approval.id,
            "decision": "rejected",
        },
        version="v2",
    )
    return _approval_read(approval)


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/approvals/{approval_id}/execute", response_model=ApplicationPrepPackRead)
async def execute_approved_action(
    approval_id: UUID,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ApplicationPrepPackRead:
    """Resume the paused graph; its executor rechecks approval and writes the local pack."""

    enforce_same_origin(request, settings)
    approval = _owned_approval(session, user, approval_id)
    existing_pack = session.scalar(
        select(ApplicationPrepPack).where(
            ApplicationPrepPack.user_id == user.id,
            ApplicationPrepPack.agent_run_id == approval.agent_run_id,
        )
    )
    if existing_pack is not None and approval.status == "executed":
        response.status_code = status.HTTP_200_OK
        return ApplicationPrepPackRead.model_validate(existing_pack)
    if approval.status != "approved":
        raise HTTPException(status_code=409, detail="只有已批准且未执行的操作可以执行。")
    now = utc_now()
    if _utc(approval.expires_at) <= now:
        approval.status = "expired"
        approval.updated_at = now
        _audit(
            session,
            user_id=user.id,
            approval_id=approval.id,
            action="approval_expired",
            entity_type="application_prep_pack",
            entity_id=approval.agent_run_id,
            details={"approval_hash": approval.approval_hash},
        )
        session.commit()
        raise HTTPException(status_code=409, detail="审批已过期，请重新生成并检查草稿。")
    if approval.action_type != SAVE_PREP_PACK_ACTION:
        raise HTTPException(status_code=403, detail="此操作没有可用的执行器。")

    run = _owned_skill_run(session, user, approval.agent_run_id)
    await request.app.state.agent_workflow_graph.ainvoke(
        {
            "task_type": "skill_workflow",
            "operation": "resume",
            "run_id": run.id,
            "approval_id": approval.id,
            "decision": "approved",
        },
        version="v2",
    )
    session.expire_all()
    pack = session.scalar(
        select(ApplicationPrepPack).where(
            ApplicationPrepPack.user_id == user.id,
            ApplicationPrepPack.agent_run_id == run.id,
        )
    )
    if pack is None:
        raise HTTPException(status_code=503, detail="LangGraph 已恢复但未返回已保存的准备包。")
    session.refresh(approval)
    response.status_code = status.HTTP_201_CREATED
    return ApplicationPrepPackRead.model_validate(pack)


@router.get("/packs", response_model=list[ApplicationPrepPackRead])
def list_prep_packs(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    limit: int = 50,
) -> list[ApplicationPrepPackRead]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 100 之间。")
    packs = session.scalars(
        select(ApplicationPrepPack)
        .where(ApplicationPrepPack.user_id == user.id)
        .order_by(ApplicationPrepPack.created_at.desc(), ApplicationPrepPack.id.desc())
        .limit(limit)
    )
    return [ApplicationPrepPackRead.model_validate(pack) for pack in packs]


@router.get("/audit", response_model=list[AuditEventRead])
def list_skill_audit_events(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    limit: int = 100,
) -> list[AuditEventRead]:
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 200 之间。")
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.user_id == user.id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    )
    return [AuditEventRead.model_validate(event) for event in events]
