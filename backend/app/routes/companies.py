"""Owner-scoped company archive aggregating saved jobs and cited research."""

from collections import defaultdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentRun, Application, Company, JobPosting, User
from app.routes.auth import current_user_dependency, session_dependency
from app.routes.research import _response_from_run
from app.schemas import (
    CompanyArchiveFindingRead,
    CompanyArchiveJobRead,
    CompanyArchiveRead,
    CompanyArchiveSourceRead,
    CompanyResearchRead,
)

router = APIRouter(prefix="/companies", tags=["company archive"])


def _build_archives(
    session: Session, user: User, companies: list[Company]
) -> list[CompanyArchiveRead]:
    if not companies:
        return []

    company_by_id = {company.id: company for company in companies}
    company_ids = list(company_by_id)
    jobs = session.scalars(
        select(JobPosting)
        .where(
            JobPosting.user_id == user.id,
            JobPosting.company_id.in_(company_ids),
        )
        .order_by(JobPosting.deadline.asc(), JobPosting.updated_at.desc(), JobPosting.id)
    ).all()
    jobs_by_company: dict[UUID, list[JobPosting]] = defaultdict(list)
    job_by_id: dict[UUID, JobPosting] = {}
    for job in jobs:
        if job.company_id is not None:
            jobs_by_company[job.company_id].append(job)
            job_by_id[job.id] = job

    job_ids = list(job_by_id)
    applications = session.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.job_id.in_(job_ids),
        )
    ).all() if job_ids else []
    application_by_job = {application.job_id: application for application in applications}

    research_runs: list[AgentRun] = []
    if job_ids:
        research_runs = session.scalars(
            select(AgentRun)
            .where(
                AgentRun.user_id == user.id,
                AgentRun.job_id.in_(job_ids),
                AgentRun.task_type == "company_research",
                AgentRun.status == "succeeded",
                AgentRun.result.is_not(None),
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        ).all()
    latest_run_by_job: dict[UUID, AgentRun] = {}
    for run in research_runs:
        if run.job_id is not None and run.job_id not in latest_run_by_job:
            latest_run_by_job[run.job_id] = run

    archives: list[CompanyArchiveRead] = []
    for company in companies:
        company_jobs = jobs_by_company.get(company.id, [])
        job_research: dict[UUID, CompanyResearchRead] = {}
        archive_findings: list[CompanyArchiveFindingRead] = []
        archive_sources: list[CompanyArchiveSourceRead] = []
        research_dates: list[datetime] = []
        stale_count = 0
        research_count = 0

        for job in company_jobs:
            run = latest_run_by_job.get(job.id)
            if run is None or (run.result or {}).get("company_name") != company.name:
                continue
            try:
                research = _response_from_run(run, job.id, company.name)
            except HTTPException:
                continue
            job_research[job.id] = research
            research_count += 1
            research_dates.append(research.researched_at)
            stale_count += int(research.is_stale)
            sources_by_id = {source.source_id: source for source in research.sources}

            for source in research.sources:
                archive_sources.append(
                    CompanyArchiveSourceRead(
                        research_run_id=research.run_id,
                        job_id=job.id,
                        job_title=job.title,
                        source_id=source.source_id,
                        title=source.title,
                        url=source.url,
                        excerpt=source.excerpt,
                        age=source.age,
                        researched_at=research.researched_at,
                        is_stale=research.is_stale,
                    )
                )
            for finding in research.findings:
                source = sources_by_id.get(finding.source_id)
                if source is None:
                    continue
                archive_findings.append(
                    CompanyArchiveFindingRead(
                        job_id=job.id,
                        job_title=job.title,
                        claim=finding.claim,
                        quote=finding.quote,
                        source_title=source.title,
                        source_url=source.url,
                        researched_at=research.researched_at,
                        is_stale=research.is_stale,
                    )
                )

        job_reads = []
        for job in company_jobs:
            research = job_research.get(job.id)
            application = application_by_job.get(job.id)
            job_reads.append(
                CompanyArchiveJobRead(
                    id=job.id,
                    title=job.title,
                    city=job.city,
                    job_type=job.job_type,
                    batch=job.batch,
                    deadline=job.deadline,
                    application_status=application.status if application else None,
                    source_url=job.source_url,
                    source_captured_at=job.source_captured_at,
                    research_summary=research.summary if research else None,
                    research_is_stale=research.is_stale if research else None,
                    research_no_evidence=research.no_evidence if research else None,
                    researched_at=research.researched_at if research else None,
                )
            )

        if research_count == 0:
            research_summary = "尚无已保存的公开研究结果。可从岗位卡片开始研究，结果会归档于此。"
        elif archive_findings:
            research_summary = (
                f"已汇总 {research_count} 份岗位研究，包含 {len(archive_findings)} 条带来源引用的事实。"
                "请打开来源核验；招聘信息可能变化。"
            )
        else:
            research_summary = (
                f"已汇总 {research_count} 份岗位研究，但当前没有足够证据支持事实摘要。"
                "请直接查看原始来源或稍后重新研究。"
            )

        archives.append(
            CompanyArchiveRead(
                id=company.id,
                name=company.name,
                industry=company.industry,
                website_url=company.website_url,
                recruitment_url=company.recruitment_url,
                notes=company.notes,
                batches=sorted({job.batch for job in company_jobs if job.batch}),
                jobs=job_reads,
                research_summary=research_summary,
                research_count=research_count,
                finding_count=len(archive_findings),
                source_count=len(archive_sources),
                last_researched_at=max(research_dates) if research_dates else None,
                stale_research_count=stale_count,
                no_evidence=not archive_findings,
                findings=archive_findings,
                sources=archive_sources,
            )
        )
    return archives


@router.get("", response_model=list[CompanyArchiveRead])
def list_company_archives(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[CompanyArchiveRead]:
    """List the current user's companies with saved jobs and latest cited research."""

    companies = session.scalars(
        select(Company)
        .where(Company.user_id == user.id)
        .order_by(Company.name, Company.id)
    ).all()
    companies.sort(key=lambda company: (company.name.casefold(), str(company.id)))
    return _build_archives(session, user, companies)


@router.get("/{company_id}", response_model=CompanyArchiveRead)
def get_company_archive(
    company_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> CompanyArchiveRead:
    """Return one archive after checking ownership in the database query."""

    company = session.scalar(
        select(Company).where(Company.id == company_id, Company.user_id == user.id)
    )
    if company is None:
        raise HTTPException(status_code=404, detail="公司档案不存在。")
    return _build_archives(session, user, [company])[0]
