"""Owner-scoped approval and execution API for allowlisted external actions."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AuditEvent, Company, ExternalActionApproval, JobPosting, User, utc_now
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    ExternalActionCapabilitiesRead,
    ExternalActionRead,
    ExternalEmailActionCreate,
)
from app.services.external_actions import EMAIL_SEND_ACTION, ExternalActionRegistry

router = APIRouter(prefix="/external-actions", tags=["external-actions"])
logger = logging.getLogger(__name__)
APPROVAL_TTL = timedelta(minutes=15)
MAX_ACTIONS_PER_USER = 50


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload_hash(action: ExternalActionApproval) -> str:
    return _canonical_hash(
        {
            "action_type": action.action_type,
            "job_id": str(action.job_id) if action.job_id else None,
            "payload": action.payload,
            "target": action.target,
        }
    )


def _approval_hash(action: ExternalActionApproval) -> str:
    return _canonical_hash(
        {
            "action_id": str(action.id),
            "action_type": action.action_type,
            "expires_at": _utc(action.expires_at).isoformat(),
            "job_id": str(action.job_id) if action.job_id else None,
            "payload_hash": action.payload_hash,
            "summary": action.summary,
            "target": action.target,
            "user_id": str(action.user_id),
        }
    )


def _audit(
    session: Session,
    action: ExternalActionApproval,
    event: str,
    *,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            user_id=action.user_id,
            approval_id=None,
            action=event,
            entity_type="external_action",
            entity_id=str(action.id),
            details={
                "action_type": action.action_type,
                "target": action.target,
                "payload_hash": action.payload_hash,
                **(details or {}),
            },
        )
    )


def _owned_action(
    session: Session,
    user: User,
    action_id: UUID,
    *,
    for_update: bool = False,
) -> ExternalActionApproval:
    statement = select(ExternalActionApproval).where(
        ExternalActionApproval.id == action_id,
        ExternalActionApproval.user_id == user.id,
    )
    if for_update:
        statement = statement.with_for_update()
    action = session.scalar(statement)
    if action is None:
        raise HTTPException(status_code=404, detail="外部动作记录不存在。")
    return action


def _ensure_action_integrity(action: ExternalActionApproval) -> None:
    if (
        action.action_type != EMAIL_SEND_ACTION
        or _payload_hash(action) != action.payload_hash
        or _approval_hash(action) != action.approval_hash
    ):
        action.status = "invalidated"
        action.updated_at = utc_now()
        raise HTTPException(
            status_code=409,
            detail="动作内容或审批摘要已变化，审批失效。",
        )


def _expire_if_needed(session: Session, action: ExternalActionApproval) -> None:
    if _utc(action.expires_at) > utc_now():
        return
    action.status = "expired"
    action.updated_at = utc_now()
    _audit(session, action, "external_action_expired")
    session.commit()
    raise HTTPException(
        status_code=409,
        detail="审批已过期，请重新创建并检查邮件内容。",
    )


@router.get("/capabilities", response_model=ExternalActionCapabilitiesRead)
def read_capabilities(
    request: Request,
    _user: Annotated[User, Depends(current_user_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ExternalActionCapabilitiesRead:
    """Expose enabled executors without revealing server credentials."""

    registry: ExternalActionRegistry = request.app.state.external_action_registry
    return ExternalActionCapabilitiesRead(
        email_send_enabled=registry.is_configured(EMAIL_SEND_ACTION, settings)
    )


@router.get("", response_model=list[ExternalActionRead])
def list_external_actions(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[ExternalActionRead]:
    now = utc_now()
    stale_actions = session.scalars(
        select(ExternalActionApproval).where(
            ExternalActionApproval.user_id == user.id,
            ExternalActionApproval.status.in_(("pending", "approved")),
            ExternalActionApproval.expires_at <= now,
        )
    ).all()
    for action in stale_actions:
        action.status = "expired"
        action.updated_at = now
        _audit(session, action, "external_action_expired")
    if stale_actions:
        session.commit()
    actions = session.scalars(
        select(ExternalActionApproval)
        .where(ExternalActionApproval.user_id == user.id)
        .order_by(ExternalActionApproval.created_at.desc(), ExternalActionApproval.id.desc())
        .limit(MAX_ACTIONS_PER_USER)
    ).all()
    return [ExternalActionRead.model_validate(action) for action in actions]


@router.post("", response_model=ExternalActionRead, status_code=status.HTTP_201_CREATED)
def create_email_action(
    payload: ExternalEmailActionCreate,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ExternalActionRead:
    """Create an email draft awaiting approval; this endpoint never sends mail."""

    enforce_same_origin(request, settings)
    action_payload = {"subject": payload.subject, "body": payload.body}
    request_hash = _canonical_hash(
        {
            "action_type": EMAIL_SEND_ACTION,
            "job_id": str(payload.job_id) if payload.job_id else None,
            "payload": action_payload,
            "target": payload.recipient,
        }
    )
    existing = session.scalar(
        select(ExternalActionApproval).where(
            ExternalActionApproval.user_id == user.id,
            ExternalActionApproval.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同邮件内容。")
        return ExternalActionRead.model_validate(existing)

    registry: ExternalActionRegistry = request.app.state.external_action_registry
    if not registry.is_configured(EMAIL_SEND_ACTION, settings):
        raise HTTPException(
            status_code=503,
            detail="外部邮件执行器尚未配置 SMTP，请先配置服务端邮件设置。",
        )
    now = utc_now()
    open_action_count = session.scalar(
        select(func.count(ExternalActionApproval.id)).where(
            ExternalActionApproval.user_id == user.id,
            or_(
                ExternalActionApproval.status == "executing",
                and_(
                    ExternalActionApproval.status.in_(("pending", "approved")),
                    ExternalActionApproval.expires_at > now,
                ),
            ),
        )
    ) or 0
    if open_action_count >= 5:
        raise HTTPException(
            status_code=429,
            detail=(
                "当前已有 5 个未完成的外部动作审批，"
                "请先处理或等待审批过期。"
            ),
        )

    job = None
    if payload.job_id is not None:
        job = session.scalar(
            select(JobPosting).where(
                JobPosting.id == payload.job_id,
                JobPosting.user_id == user.id,
            )
        )
        if job is None:
            raise HTTPException(status_code=404, detail="关联岗位不存在。")
        company = (
            session.scalar(
                select(Company).where(
                    Company.id == job.company_id,
                    Company.user_id == user.id,
                )
            )
            if job.company_id
            else None
        )
        job_label = " · ".join(
            part for part in (company.name if company else None, job.title) if part
        )
    else:
        job_label = "自定义目标"

    action = ExternalActionApproval(
        user_id=user.id,
        job_id=payload.job_id,
        action_type=EMAIL_SEND_ACTION,
        target=payload.recipient,
        summary=f"发送邮件至 {payload.recipient}（{job_label}）",
        payload=action_payload,
        idempotency_key=payload.idempotency_key,
        request_hash=request_hash,
        payload_hash="pending",
        approval_hash="pending",
        status="pending",
        expires_at=now + APPROVAL_TTL,
    )
    session.add(action)
    session.flush()
    action.payload_hash = _payload_hash(action)
    action.approval_hash = _approval_hash(action)
    _audit(session, action, "external_action_requested")
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ExternalActionApproval).where(
                ExternalActionApproval.user_id == user.id,
                ExternalActionApproval.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None and existing.request_hash == request_hash:
            return ExternalActionRead.model_validate(existing)
        raise HTTPException(
            status_code=409,
            detail="创建审批时发生冲突，请重新提交。",
        ) from None
    session.refresh(action)
    return ExternalActionRead.model_validate(action)


@router.post("/{action_id}/approve", response_model=ExternalActionRead)
def approve_external_action(
    action_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ExternalActionRead:
    enforce_same_origin(request, settings)
    action = _owned_action(session, user, action_id, for_update=True)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail="该动作不处于待审批状态。")
    _expire_if_needed(session, action)
    try:
        _ensure_action_integrity(action)
    except HTTPException:
        _audit(session, action, "external_action_invalidated")
        session.commit()
        raise
    now = utc_now()
    changed = session.execute(
        update(ExternalActionApproval)
        .where(
            ExternalActionApproval.id == action.id,
            ExternalActionApproval.user_id == user.id,
            ExternalActionApproval.status == "pending",
            ExternalActionApproval.expires_at > now,
        )
        .execution_options(synchronize_session=False)
        .values(status="approved", approved_at=now, updated_at=now)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="该动作已被处理，请刷新后重试。")
    session.refresh(action)
    _audit(session, action, "external_action_approved")
    session.commit()
    session.refresh(action)
    return ExternalActionRead.model_validate(action)


@router.post("/{action_id}/reject", response_model=ExternalActionRead)
def reject_external_action(
    action_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ExternalActionRead:
    enforce_same_origin(request, settings)
    action = _owned_action(session, user, action_id, for_update=True)
    if action.status == "rejected":
        return ExternalActionRead.model_validate(action)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail="该动作不处于待审批状态。")
    now = utc_now()
    changed = session.execute(
        update(ExternalActionApproval)
        .where(
            ExternalActionApproval.id == action.id,
            ExternalActionApproval.user_id == user.id,
            ExternalActionApproval.status == "pending",
        )
        .execution_options(synchronize_session=False)
        .values(status="rejected", updated_at=now)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="该动作已被处理，请刷新后重试。")
    session.refresh(action)
    _audit(session, action, "external_action_rejected")
    session.commit()
    session.refresh(action)
    return ExternalActionRead.model_validate(action)


@router.post("/{action_id}/execute", response_model=ExternalActionRead)
async def execute_external_action(
    action_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ExternalActionRead:
    """Execute one approved email at most once; uncertain SMTP outcomes are not retried."""

    enforce_same_origin(request, settings)
    action = _owned_action(session, user, action_id, for_update=True)
    if action.status == "executed":
        return ExternalActionRead.model_validate(action)
    if action.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="只有已批准且未执行的动作可以执行。",
        )
    _expire_if_needed(session, action)
    try:
        _ensure_action_integrity(action)
    except HTTPException:
        _audit(session, action, "external_action_invalidated")
        session.commit()
        raise

    registry: ExternalActionRegistry = request.app.state.external_action_registry
    if not registry.supports(action.action_type):
        raise HTTPException(status_code=403, detail="该外部动作没有获准的执行器。")
    if not registry.is_configured(action.action_type, settings):
        raise HTTPException(status_code=503, detail="外部动作执行器未配置，尚未执行。")

    started_at = utc_now()
    changed = session.execute(
        update(ExternalActionApproval)
        .where(
            ExternalActionApproval.id == action.id,
            ExternalActionApproval.user_id == user.id,
            ExternalActionApproval.status == "approved",
            ExternalActionApproval.approval_hash == action.approval_hash,
            ExternalActionApproval.expires_at > started_at,
        )
        .execution_options(synchronize_session=False)
        .values(status="executing", started_at=started_at, updated_at=started_at)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="该动作已被执行或处理，请刷新状态。",
        )
    session.refresh(action)
    _audit(session, action, "external_action_execution_started")
    session.commit()

    try:
        message_id = await registry.execute(
            action.action_type,
            settings,
            action_id=action.id,
            target=action.target,
            payload=action.payload,
        )
    except Exception as exc:
        logger.error("External email action %s failed (%s)", action.id, type(exc).__name__)
        action.status = "outcome_unknown"
        action.updated_at = utc_now()
        action.result = {"message": "SMTP 结果未知；请人工核对收件箱后再处理。"}
        _audit(
            session,
            action,
            "external_action_outcome_unknown",
            details={"exception_type": type(exc).__name__},
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail=(
                "邮件服务未能确认发送结果。"
                "请先核对收件箱，不会自动重试。"
            ),
        ) from None

    action.status = "executed"
    action.executed_at = utc_now()
    action.updated_at = action.executed_at
    action.result = {"provider": "smtp", "message_id": message_id}
    _audit(
        session,
        action,
        "external_action_executed",
        details={"provider": "smtp", "message_id": message_id},
    )
    session.commit()
    session.refresh(action)
    return ExternalActionRead.model_validate(action)
