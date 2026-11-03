"""Account data export and deletion endpoints."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Iterator
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import Settings
from app.core.security import verify_password
from app.models import (
    AgentRun,
    Application,
    ApplicationPrepPack,
    ApplicationStatusEvent,
    ApprovalRequest,
    AuditEvent,
    CandidateProfile,
    Company,
    DocumentChunk,
    ExternalActionApproval,
    JobPosting,
    JobSourceEvidence,
    KnowledgeNote,
    Notification,
    Reminder,
    ResumeVersion,
    User,
    UserModelConfiguration,
)
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/account", tags=["account"])


class AccountDeleteRequest(BaseModel):
    """Require both account credentials before irreversible deletion."""

    current_password: SecretStr
    confirmation_email: EmailStr


_OWNED_MODELS = (
    Notification,
    ApplicationStatusEvent,
    AuditEvent,
    ApprovalRequest,
    ApplicationPrepPack,
    ExternalActionApproval,
    UserModelConfiguration,
    JobSourceEvidence,
    Application,
    Reminder,
    DocumentChunk,
    AgentRun,
    JobPosting,
    ResumeVersion,
    KnowledgeNote,
    CandidateProfile,
    Company,
)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _safe_archive_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    safe = "".join(character for character in basename if character.isalnum() or character in " ._-()")
    return safe[:180] or "resume"


def _owned_rows(session: Session, model: type[Any], user_id: UUID) -> list[dict[str, Any]]:
    rows = session.scalars(select(model).where(model.user_id == user_id)).all()
    exported: list[dict[str, Any]] = []
    for row in rows:
        values = {
            attribute.key: getattr(row, attribute.key)
            for attribute in model.__mapper__.column_attrs
            if attribute.key not in {"password_hash", "embedding", "storage_key"}
        }
        exported.append(values)
    return exported


def _stream_file(file: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := file.read(1024 * 1024):
            yield chunk
    finally:
        file.close()


def _create_export_archive(
    user: User, session: Session, settings: Settings
) -> BinaryIO:
    """Build a spooled ZIP containing only the selected user's exportable data."""

    manifest: dict[str, Any] = {
        "format": "offerpilot-account-export-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "timezone": user.timezone,
            "created_at": user.created_at,
        },
        "data": {},
        "files": [],
        "warnings": [],
    }
    for model in _OWNED_MODELS:
        manifest["data"][model.__tablename__] = _owned_rows(session, model, user.id)

    archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    storage_root = settings.storage_dir.resolve()
    resume_rows = session.scalars(
        select(ResumeVersion).where(ResumeVersion.user_id == user.id)
    ).all()
    user_storage_dir = storage_root / str(user.id)
    try:
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for resume in resume_rows:
                if not resume.storage_key:
                    continue
                source = (storage_root / resume.storage_key).resolve()
                if (
                    user_storage_dir.is_symlink()
                    or user_storage_dir.resolve() not in source.parents
                ):
                    manifest["warnings"].append(
                        f"简历版本 {resume.id} 的文件路径无效，未加入原文件。"
                    )
                    continue
                if not source.is_file():
                    manifest["warnings"].append(
                        f"简历版本 {resume.id} 的原文件缺失，仅导出已解析文本。"
                    )
                    continue
                archive_name = (
                    f"resumes/{resume.id}_{_safe_archive_filename(resume.filename)}"
                )
                bundle.write(source, archive_name)
                manifest["files"].append(
                    {"resume_id": str(resume.id), "archive_path": archive_name}
                )
            bundle.writestr(
                "offerpilot-export.json",
                json.dumps(manifest, ensure_ascii=False, default=_json_default, indent=2),
            )
        archive.seek(0)
    except Exception:
        archive.close()
        raise

    return archive


@router.get("/export", response_class=StreamingResponse)
def export_account_data(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> StreamingResponse:
    """Download the user's database records and uploaded resume originals."""

    archive = _create_export_archive(user, session, settings)
    response = StreamingResponse(
        _stream_file(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="offerpilot-data-export.zip"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
    response.background = BackgroundTask(archive.close)
    return response


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: AccountDeleteRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> Response:
    """Permanently remove the account, its product data, and uploaded files."""

    enforce_same_origin(request, settings)
    if payload.confirmation_email.casefold() != user.email.casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="确认邮箱与当前账户不匹配。",
        )
    if not verify_password(payload.current_password.get_secret_value(), user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="密码不正确，账户未删除。",
        )

    storage_root = settings.storage_dir.resolve()
    user_directory = storage_root / str(user.id)
    staged_directory = storage_root / f".account-deletion-{user.id}-{uuid4()}"
    if user_directory.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="账户文件目录无效，未删除账户。",
        )
    if user_directory.exists():
        resolved_directory = user_directory.resolve()
        if storage_root not in resolved_directory.parents or not resolved_directory.is_dir():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="账户文件目录无效，未删除账户。",
            )
        os.replace(user_directory, staged_directory)

    try:
        for model in _OWNED_MODELS:
            session.execute(delete(model).where(model.user_id == user.id))
        session.execute(delete(User).where(User.id == user.id))
        session.commit()
    except Exception:
        session.rollback()
        if staged_directory.exists() and not user_directory.exists():
            os.replace(staged_directory, user_directory)
        raise

    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )
    if staged_directory.exists():
        try:
            shutil.rmtree(staged_directory)
        except OSError as exc:
            logger.exception("Account was deleted but its staged files could not be removed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="账户数据已删除，但原文件清理未完成，请联系管理员。",
            ) from exc
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
