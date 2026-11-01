"""Private job posting management and application-board endpoints."""

from datetime import date, datetime, timezone
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AgentRun,
    Application,
    ApplicationStatusEvent,
    Company,
    JobSourceEvidence,
    JobPosting,
    ResumeVersion,
    User,
)
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    ApplicationRead,
    ApplicationStage,
    ApplicationStatusEventRead,
    ApplicationUpdate,
    JobBulkImportWrite,
    JobCsvPreviewRead,
    JobCsvPreviewRowRead,
    JobPostingRead,
    JobPostingWrite,
)
from app.services.job_csv import (
    JobCsvImportError,
    build_job_csv_template,
    parse_job_csv,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
ApplicationFilter = Literal[
    "to_research",
    "interested",
    "preparing",
    "applied",
    "assessment",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "closed",
    "untracked",
]


def _normalize_source_url(value: str | None) -> str | None:
    """Normalize URL host, trailing slash, and fragment for duplicate checks."""

    if value is None:
        return None
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _owned_job(session: Session, user: User, job_id: UUID) -> JobPosting:
    """Resolve a job through its owner id rather than trusting a supplied UUID."""

    job = session.scalar(
        select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    return job


def _owned_application(session: Session, user: User, job_id: UUID) -> Application:
    """Resolve the current user's application record for a job."""

    application = session.scalar(
        select(Application).where(
            Application.job_id == job_id,
            Application.user_id == user.id,
        )
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该岗位尚无投递记录",
        )
    return application


def _company_for_payload(
    session: Session,
    user: User,
    payload: JobPostingWrite,
    *,
    preserve_existing_details: bool = False,
) -> Company | None:
    """Find or create a company within the current user's private namespace."""

    if payload.company_name is None:
        return None
    normalized_name = payload.company_name.casefold()
    company = session.scalar(
        select(Company).where(
            Company.user_id == user.id,
            Company.normalized_name == normalized_name,
        )
    )
    if company is None:
        company = Company(
            user_id=user.id,
            name=payload.company_name,
            normalized_name=normalized_name,
            website_url=payload.company_website_url,
            recruitment_url=payload.recruitment_url,
            industry=payload.industry,
            notes=payload.company_notes,
        )
        session.add(company)
        session.flush()
        return company

    company.name = payload.company_name
    company_fields = {
        "website_url": payload.company_website_url,
        "recruitment_url": payload.recruitment_url,
        "industry": payload.industry,
        "notes": payload.company_notes,
    }
    for field, value in company_fields.items():
        if value is not None or not preserve_existing_details:
            setattr(company, field, value)
    return company


def _to_read(
    job: JobPosting,
    company: Company | None,
    application: Application | None,
) -> JobPostingRead:
    """Build a flattened job response without exposing other users' records."""

    return JobPostingRead(
        id=job.id,
        company_id=company.id if company else None,
        company_name=company.name if company else None,
        company_website_url=company.website_url if company else None,
        recruitment_url=company.recruitment_url if company else None,
        industry=company.industry if company else None,
        company_notes=company.notes if company else None,
        title=job.title,
        city=job.city,
        job_type=job.job_type,
        batch=job.batch,
        deadline=job.deadline,
        education_requirement=job.education_requirement,
        required_skills=job.required_skills,
        description=job.description,
        source_url=job.source_url,
        source_type=job.source_type,
        source_captured_at=job.source_captured_at,
        tags=job.tags,
        review_status=job.review_status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        application=ApplicationRead.model_validate(application) if application else None,
    )


def _duplicate_source_error() -> HTTPException:
    """Give an actionable duplicate-source response without merging silently."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "这个来源链接已在你的岗位列表中，请编辑已有岗位或检查来源链接后再保存。"
        ),
    )


def _assign_job_fields(job: JobPosting, payload: JobPostingWrite) -> None:
    """Replace editable job and source fields from a validated full form."""

    job.title = payload.title
    job.city = payload.city
    job.job_type = payload.job_type
    job.batch = payload.batch
    job.deadline = payload.deadline
    job.education_requirement = payload.education_requirement
    job.required_skills = payload.required_skills
    job.description = payload.description
    job.source_url = payload.source_url
    job.normalized_source_url = _normalize_source_url(payload.source_url)
    job.source_type = payload.source_type
    job.tags = payload.tags
    job.source_captured_at = datetime.now(timezone.utc)


@router.get("", response_model=list[JobPostingRead])
def list_jobs(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    search: str | None = None,
    company: str | None = None,
    title: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    status_filter: Annotated[ApplicationFilter | None, Query(alias="status")] = None,
    tag: str | None = None,
    deadline_before: date | None = None,
    tracked: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[JobPostingRead]:
    """List only the user's jobs with deterministic company/status/deadline filters."""

    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit 必须在 1 到 500 之间")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset 不能小于 0")

    statement = (
        select(JobPosting, Company, Application)
        .outerjoin(Company, Company.id == JobPosting.company_id)
        .outerjoin(
            Application,
            (Application.job_id == JobPosting.id) & (Application.user_id == user.id),
        )
        .where(JobPosting.user_id == user.id)
    )

    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                JobPosting.title.ilike(term),
                Company.name.ilike(term),
                JobPosting.city.ilike(term),
                Company.industry.ilike(term),
            )
        )
    if company and company.strip():
        statement = statement.where(Company.name.ilike(f"%{company.strip()}%"))
    if title and title.strip():
        statement = statement.where(JobPosting.title.ilike(f"%{title.strip()}%"))
    if city and city.strip():
        statement = statement.where(JobPosting.city.ilike(f"%{city.strip()}%"))
    if industry and industry.strip():
        statement = statement.where(Company.industry.ilike(f"%{industry.strip()}%"))
    if deadline_before is not None:
        statement = statement.where(JobPosting.deadline <= deadline_before)
    if status_filter == "untracked":
        statement = statement.where(Application.id.is_(None))
    elif status_filter is not None:
        statement = statement.where(Application.status == status_filter)
    if tracked is True:
        statement = statement.where(Application.id.is_not(None))
    elif tracked is False:
        statement = statement.where(Application.id.is_(None))
    if tag and tag.strip():
        # SQLAlchemy stores JSON strings with Unicode escapes on SQLite and
        # PostgreSQL. Match the full quoted JSON string so tags are exact.
        json_tag = json.dumps(tag.strip(), ensure_ascii=True).casefold()
        escaped_tag = json_tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            func.lower(cast(JobPosting.tags, String)).ilike(f"%{escaped_tag}%", escape="\\")
        )

    statement = statement.order_by(
        JobPosting.created_at.desc(),
        JobPosting.id.desc(),
    ).limit(limit).offset(offset)
    rows = session.execute(statement).all()
    return [_to_read(job, company_row, application) for job, company_row, application in rows]


@router.get("/import/template")
def download_job_csv_template(
    user: Annotated[User, Depends(current_user_dependency)],
) -> Response:
    """Download a UTF-8 CSV template for manually collected job postings."""

    del user
    return Response(
        content=build_job_csv_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="offerpilot_job_template.csv"'},
    )


@router.post("/import/preview", response_model=JobCsvPreviewRead)
def preview_job_csv(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobCsvPreviewRead:
    """Validate CSV rows and identify duplicate sources before saving anything."""

    enforce_same_origin(request, settings)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="请选择 CSV 文件")
    try:
        parsed_rows = parse_job_csv(file.file.read(5 * 1024 * 1024 + 1))
    except JobCsvImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing_sources = set(
        session.scalars(
            select(JobPosting.normalized_source_url).where(
                JobPosting.user_id == user.id,
                JobPosting.normalized_source_url.is_not(None),
            )
        )
    )
    seen_sources: dict[str, int] = {}
    preview_rows: list[JobCsvPreviewRowRead] = []
    for row in parsed_rows:
        payload = row.data
        row_status: Literal["ready", "duplicate", "invalid"] = (
            "ready" if payload is not None and not row.errors else "invalid"
        )
        duplicate_detail = None
        if payload is not None:
            normalized_url = _normalize_source_url(payload.source_url)
            if normalized_url and normalized_url in existing_sources:
                row_status = "duplicate"
                duplicate_detail = "该来源链接已存在于你的岗位列表"
            elif normalized_url and normalized_url in seen_sources:
                row_status = "duplicate"
                duplicate_detail = f"与 CSV 第 {seen_sources[normalized_url]} 行的来源链接重复"
            elif normalized_url:
                seen_sources[normalized_url] = row.row_number
        preview_rows.append(
            JobCsvPreviewRowRead(
                row_number=row.row_number,
                status=row_status,
                company_name=(payload.company_name if payload else row.fields.get("company_name") or None),
                title=(payload.title if payload else row.fields.get("title") or None),
                city=(payload.city if payload else row.fields.get("city") or None),
                deadline=(
                    payload.deadline.isoformat()
                    if payload and payload.deadline
                    else row.fields.get("deadline") or None
                ),
                source_url=(payload.source_url if payload else row.fields.get("source_url") or None),
                data=payload,
                errors=row.errors,
                duplicate_detail=duplicate_detail,
            )
        )

    return JobCsvPreviewRead(
        rows=preview_rows,
        ready_count=sum(row.status == "ready" for row in preview_rows),
        duplicate_count=sum(row.status == "duplicate" for row in preview_rows),
        invalid_count=sum(row.status == "invalid" for row in preview_rows),
    )


@router.post(
    "/import",
    response_model=list[JobPostingRead],
    status_code=status.HTTP_201_CREATED,
)
def import_jobs(
    payload: JobBulkImportWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> list[JobPostingRead]:
    """Save user-selected validated rows atomically after a preview."""

    enforce_same_origin(request, settings)
    existing_sources = set(
        session.scalars(
            select(JobPosting.normalized_source_url).where(
                JobPosting.user_id == user.id,
                JobPosting.normalized_source_url.is_not(None),
            )
        )
    )
    batch_sources: set[str] = set()
    for index, job_payload in enumerate(payload.jobs, start=1):
        normalized_url = _normalize_source_url(job_payload.source_url)
        if normalized_url and normalized_url in existing_sources:
            raise HTTPException(
                status_code=409,
                detail=f"第 {index} 条岗位的来源链接已存在，请检查预览后再导入。",
            )
        if normalized_url and normalized_url in batch_sources:
            raise HTTPException(
                status_code=409,
                detail=f"导入内容中第 {index} 条岗位的来源链接重复。",
            )
        if normalized_url:
            batch_sources.add(normalized_url)

    created: list[tuple[JobPosting, Company | None]] = []
    try:
        for job_payload in payload.jobs:
            company_row = _company_for_payload(
                session,
                user,
                job_payload,
                preserve_existing_details=True,
            )
            job = JobPosting(
                user_id=user.id,
                company_id=company_row.id if company_row else None,
                review_status=(
                    "verified"
                    if job_payload.company_name and job_payload.title
                    else "needs_review"
                ),
            )
            _assign_job_fields(job, job_payload)
            session.add(job)
            created.append((job, company_row))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="导入数据与现有岗位或公司信息冲突，请重新预览后再试。",
        ) from None

    results = []
    for job, company_row in created:
        session.refresh(job)
        results.append(_to_read(job, company_row, None))
    return results


@router.post("", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobPostingWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Save a manually entered job and preserve its source snapshot metadata."""

    enforce_same_origin(request, settings)
    normalized_source_url = _normalize_source_url(payload.source_url)
    if normalized_source_url and session.scalar(
        select(JobPosting.id).where(
            JobPosting.user_id == user.id,
            JobPosting.normalized_source_url == normalized_source_url,
        )
    ):
        raise _duplicate_source_error()
    company_row = _company_for_payload(session, user, payload, preserve_existing_details=True)
    job = JobPosting(
        user_id=user.id,
        company_id=company_row.id if company_row else None,
        review_status="verified" if payload.company_name and payload.title else "needs_review",
    )
    _assign_job_fields(job, payload)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if normalized_source_url:
            raise _duplicate_source_error() from None
        raise HTTPException(
            status_code=409, detail="公司信息冲突，请刷新后重试"
        ) from None
    session.refresh(job)
    return _to_read(job, company_row, None)


@router.get("/{job_id}", response_model=JobPostingRead)
def read_job(
    job_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> JobPostingRead:
    """Return one job, only when it belongs to the signed-in user."""

    job = _owned_job(session, user, job_id)
    company_row = session.get(Company, job.company_id) if job.company_id else None
    application = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    return _to_read(job, company_row, application)


@router.put("/{job_id}", response_model=JobPostingRead)
def update_job(
    job_id: UUID,
    payload: JobPostingWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Update a private job and its reusable company profile."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    old_source_url = job.normalized_source_url
    old_description = job.description
    old_source_captured_at = job.source_captured_at
    old_title = job.title
    old_company_id = job.company_id
    normalized_source_url = _normalize_source_url(payload.source_url)
    if normalized_source_url and session.scalar(
        select(JobPosting.id).where(
            JobPosting.user_id == user.id,
            JobPosting.normalized_source_url == normalized_source_url,
            JobPosting.id != job.id,
        )
    ):
        raise _duplicate_source_error()
    company_row = _company_for_payload(session, user, payload)
    job.company_id = company_row.id if company_row else None
    _assign_job_fields(job, payload)
    if old_source_url == job.normalized_source_url and old_description == job.description:
        # A regular edit should not make an existing source look newly collected.
        job.source_captured_at = old_source_captured_at
    if (
        old_title != job.title
        or old_company_id != job.company_id
        or old_source_url != job.normalized_source_url
        or old_description != job.description
    ):
        job.review_status = "needs_review"
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if normalized_source_url:
            raise _duplicate_source_error() from None
        raise HTTPException(
            status_code=409, detail="公司信息冲突，请刷新后重试"
        ) from None
    session.refresh(job)
    application = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    return _to_read(job, company_row, application)


@router.post("/{job_id}/verify", response_model=JobPostingRead)
def verify_job(
    job_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Let the owner confirm that the company and role fields were reviewed."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    company_row = session.get(Company, job.company_id) if job.company_id else None
    if not job.title or not company_row:
        raise HTTPException(
            status_code=409,
            detail="请先补充公司名称和职位名称，再标记为已核验。",
        )
    job.review_status = "verified"
    session.commit()
    session.refresh(job)
    application = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    return _to_read(job, company_row, application)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> None:
    """Delete an owned job and its tracking history, retaining reusable companies."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    application = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    if application is not None:
        session.query(ApplicationStatusEvent).filter(
            ApplicationStatusEvent.application_id == application.id
        ).delete(synchronize_session=False)
        session.delete(application)
    session.query(JobSourceEvidence).filter(
        JobSourceEvidence.job_id == job.id,
        JobSourceEvidence.user_id == user.id,
    ).delete(synchronize_session=False)
    session.query(AgentRun).filter(
        AgentRun.job_id == job.id,
        AgentRun.user_id == user.id,
    ).delete(synchronize_session=False)
    session.delete(job)
    session.commit()
    return None


@router.post(
    "/{job_id}/application",
    response_model=JobPostingRead,
    status_code=status.HTTP_201_CREATED,
)
def add_to_board(
    job_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Start tracking a job at the initial 'to research' stage."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    existing = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="该岗位已经在投递看板中。")
    application = Application(user_id=user.id, job_id=job.id, status="to_research")
    session.add(application)
    session.flush()
    session.add(
        ApplicationStatusEvent(
            user_id=user.id,
            application_id=application.id,
            from_status=None,
            to_status="to_research",
        )
    )
    session.commit()
    session.refresh(application)
    company_row = session.get(Company, job.company_id) if job.company_id else None
    return _to_read(job, company_row, application)


@router.put("/{job_id}/application", response_model=JobPostingRead)
def update_application(
    job_id: UUID,
    payload: ApplicationUpdate,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobPostingRead:
    """Save progress directly from a job card, creating tracking when needed."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    application = session.scalar(
        select(Application).where(Application.job_id == job.id, Application.user_id == user.id)
    )
    values = payload.model_dump(exclude_unset=True)
    new_status = values.pop("status", None)
    resume_version_id = values.get("resume_version_id")
    if resume_version_id is not None:
        resume = session.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == resume_version_id,
                ResumeVersion.user_id == user.id,
            )
        )
        if resume is None:
            raise HTTPException(status_code=404, detail="所选简历版本不存在")
    try:
        if application is None:
            application = Application(
                user_id=user.id,
                job_id=job.id,
                status=new_status or "to_research",
                **values,
            )
            session.add(application)
            session.flush()
            session.add(
                ApplicationStatusEvent(
                    user_id=user.id,
                    application_id=application.id,
                    from_status=None,
                    to_status=application.status,
                )
            )
        else:
            for field, value in values.items():
                setattr(application, field, value)
            if new_status is not None and new_status != application.status:
                old_status = application.status
                application.status = new_status
                session.add(
                    ApplicationStatusEvent(
                        user_id=user.id,
                        application_id=application.id,
                        from_status=old_status,
                        to_status=new_status,
                    )
                )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="投递记录已发生变化，请刷新后重试。",
        ) from None
    session.refresh(application)
    company_row = session.get(Company, job.company_id) if job.company_id else None
    return _to_read(job, company_row, application)


@router.get("/{job_id}/application/history", response_model=list[ApplicationStatusEventRead])
def read_application_history(
    job_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[ApplicationStatusEventRead]:
    """Return the append-only stage history for an owned application."""

    job = _owned_job(session, user, job_id)
    application = _owned_application(session, user, job.id)
    events = session.scalars(
        select(ApplicationStatusEvent)
        .where(
            ApplicationStatusEvent.application_id == application.id,
            ApplicationStatusEvent.user_id == user.id,
        )
        .order_by(ApplicationStatusEvent.created_at.asc())
    )
    return [ApplicationStatusEventRead.model_validate(event) for event in events]


@router.delete("/{job_id}/application", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_board(
    job_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> None:
    """Stop tracking a job and remove its board-only transition history."""

    enforce_same_origin(request, settings)
    job = _owned_job(session, user, job_id)
    application = _owned_application(session, user, job.id)
    session.query(ApplicationStatusEvent).filter(
        ApplicationStatusEvent.application_id == application.id
    ).delete(synchronize_session=False)
    session.delete(application)
    session.commit()
    return None
