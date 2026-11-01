"""Private resume upload, preview, confirmation, and deletion endpoints."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DocumentChunk, ResumeVersion, User
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import ResumeDetail, ResumeSummary, ResumeTextCreate
from app.services.resume_parser import MAX_EXTRACTED_CHARS, ResumeParseError, parse_resume

router = APIRouter(prefix="/resumes", tags=["resumes"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _safe_filename(filename: str | None, fallback: str) -> str:
    """Keep only a display name; never use the client path for storage."""

    normalized = (filename or fallback).replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    return normalized[:255] or fallback


def _owned_resume(session: Session, user: User, resume_id: UUID) -> ResumeVersion:
    """Look up a resume scoped to its owner to prevent cross-user access."""

    resume = session.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == resume_id,
            ResumeVersion.user_id == user.id,
        )
    )
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


def _detail(resume: ResumeVersion) -> ResumeDetail:
    """Build a response with extracted text while excluding the storage key."""

    return ResumeDetail(
        id=resume.id,
        filename=resume.filename,
        source_type=resume.source_type,
        content_type=resume.content_type,
        created_at=resume.created_at,
        confirmed_at=resume.confirmed_at,
        extracted_char_count=len(resume.extracted_text),
        extracted_text=resume.extracted_text,
    )


def _summary(resume: ResumeVersion) -> ResumeSummary:
    """Build a list response without returning the full resume text."""

    return ResumeSummary(
        id=resume.id,
        filename=resume.filename,
        source_type=resume.source_type,
        content_type=resume.content_type,
        created_at=resume.created_at,
        confirmed_at=resume.confirmed_at,
        extracted_char_count=len(resume.extracted_text),
    )


def _store_uploaded_resume(
    *,
    data: bytes,
    filename: str,
    user: User,
    settings: Settings,
    session: Session,
) -> ResumeVersion:
    """Parse and persist a file using a server-generated, owner-scoped path."""

    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".docx"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="仅支持 PDF 或 DOCX 简历")
    try:
        parsed = parse_resume(data, extension)
    except ResumeParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    resume_id = uuid4()
    storage_key = f"{user.id}/{resume_id}{extension}"
    storage_root = settings.storage_dir.resolve()
    file_path = (storage_root / storage_key).resolve()
    if storage_root not in file_path.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid storage path")
    storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_root.chmod(0o700)
    file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_path.parent.chmod(0o700)

    resume = ResumeVersion(
        id=resume_id,
        user_id=user.id,
        filename=filename,
        source_type="upload",
        content_type=parsed.content_type,
        storage_key=storage_key,
        extracted_text=parsed.text,
    )
    file_created = False
    try:
        file_descriptor = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        file_created = True
        with os.fdopen(file_descriptor, "wb") as stored_file:
            stored_file.write(data)
        session.add(resume)
        session.commit()
        session.refresh(resume)
    except Exception:
        session.rollback()
        if file_created:
            file_path.unlink(missing_ok=True)
        raise
    return resume


@router.get("", response_model=list[ResumeSummary])
def list_resumes(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[ResumeSummary]:
    """List resume versions belonging to the current user."""

    resumes = session.scalars(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.created_at.desc())
    )
    return [_summary(resume) for resume in resumes]


@router.post("/upload", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def upload_resume(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ResumeDetail:
    """Upload a PDF/DOCX resume and return an unconfirmed text preview."""

    enforce_same_origin(request, settings)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="文件不能超过 10 MB")
    filename = _safe_filename(file.filename, "resume")
    resume = _store_uploaded_resume(
        data=data,
        filename=filename,
        user=user,
        settings=settings,
        session=session,
    )
    return _detail(resume)


@router.post("/text", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def create_resume_from_text(
    payload: ResumeTextCreate,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ResumeDetail:
    """Save pasted resume text as a version pending user review."""

    enforce_same_origin(request, settings)
    text = "\n".join(line.strip() for line in payload.text.splitlines()).strip()
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    if not text or len(text) > MAX_EXTRACTED_CHARS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="简历文本无效或超过 100,000 字符")
    resume = ResumeVersion(
        user_id=user.id,
        filename=_safe_filename(payload.filename, "粘贴的简历内容.txt"),
        source_type="paste",
        content_type="text/plain",
        storage_key=None,
        extracted_text=text,
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    return _detail(resume)


@router.get("/{resume_id}", response_model=ResumeDetail)
def read_resume(
    resume_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> ResumeDetail:
    """Return the current user's resume text for review."""

    return _detail(_owned_resume(session, user, resume_id))


@router.post("/{resume_id}/confirm", response_model=ResumeDetail)
def confirm_resume(
    resume_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> ResumeDetail:
    """Mark a reviewed resume version as confirmed by its owner."""

    enforce_same_origin(request, settings)
    resume = _owned_resume(session, user, resume_id)
    if resume.confirmed_at is None:
        resume.confirmed_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(resume)
    return _detail(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> None:
    """Delete one owned resume version and its stored file, if present."""

    enforce_same_origin(request, settings)
    resume = _owned_resume(session, user, resume_id)
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.user_id == user.id,
            DocumentChunk.source_type == "resume",
            DocumentChunk.source_id == resume.id,
        )
    )
    if resume.storage_key:
        storage_root = settings.storage_dir.resolve()
        file_path = (storage_root / resume.storage_key).resolve()
        if storage_root not in file_path.parents:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid stored file path")
        file_path.unlink(missing_ok=True)
    session.delete(resume)
    session.commit()
    return None
