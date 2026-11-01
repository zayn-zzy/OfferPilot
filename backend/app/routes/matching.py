"""Transparent, owner-scoped job-to-profile and confirmed-resume comparison."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateProfile, Company, JobPosting, ResumeVersion, User
from app.routes.auth import current_user_dependency, session_dependency
from app.schemas import JobMatchRead, MatchCriterionRead, MatchSkillRead

router = APIRouter(prefix="/jobs", tags=["matching"])


def _degree_level(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.replace(" ", "")
    if any(token in normalized for token in ("不限", "无要求")):
        return 0
    if any(separator in normalized for separator in ("或", "/", "、")):
        return None
    for token, level in (("博士", 4), ("硕士", 3), ("本科", 2), ("大专", 1), ("专科", 1), ("高中", 0)):
        if token in normalized:
            return level
    return None


def _evidence_for(text: str, term: str) -> str | None:
    """Return one original line containing a term, without synthesizing evidence."""

    needle = term.casefold()
    for line in re.split(r"[\r\n。；;]+", text):
        candidate = line.strip()
        escaped = re.escape(needle)
        if needle and re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", candidate.casefold()):
            return candidate[:500]
    return None


def _preference_criterion(
    *,
    key: str,
    label: str,
    requirement: str | None,
    candidate_value: str | None,
    explanation: str,
    status: str,
) -> MatchCriterionRead:
    return MatchCriterionRead(
        key=key,
        label=label,
        category="preference",
        status=status,
        requirement=requirement,
        candidate_value=candidate_value,
        explanation=explanation,
    )


@router.get("/{job_id}/match", response_model=JobMatchRead)
def analyze_job_match(
    job_id: UUID,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> JobMatchRead:
    """Compare structured job requirements against this user's confirmed data."""

    job = session.scalar(
        select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user.id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
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
        raise HTTPException(status_code=409, detail="请先在个人档案中导入并确认一份简历。")

    profile = session.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    company = (
        session.scalar(
            select(Company).where(Company.id == job.company_id, Company.user_id == user.id)
        )
        if job.company_id
        else None
    )
    resume_text = resume.extracted_text
    criteria: list[MatchCriterionRead] = []

    required_degree = _degree_level(job.education_requirement)
    candidate_degree = _degree_level(profile.education if profile else None)
    if not job.education_requirement:
        degree_status = "unknown"
        degree_explanation = "岗位没有记录学历要求。"
    elif required_degree == 0:
        degree_status = "meets"
        degree_explanation = "岗位明确标注学历不限。"
    elif required_degree is None or candidate_degree is None:
        degree_status = "unknown"
        degree_explanation = "岗位或个人档案中的学历无法可靠归一化，需人工核对。"
    elif candidate_degree >= required_degree:
        degree_status = "meets"
        degree_explanation = "按岗位最低学历要求与档案学历进行等级比较。"
    else:
        degree_status = "does_not_meet"
        degree_explanation = "档案学历低于岗位写明的学历要求，请人工确认要求是否可协商。"
    criteria.append(
        MatchCriterionRead(
            key="education",
            label="学历要求",
            category="hard_requirement",
            status=degree_status,
            requirement=job.education_requirement,
            candidate_value=profile.education if profile else None,
            explanation=degree_explanation,
        )
    )

    target_cities = profile.target_cities if profile else []
    city_status = "unknown"
    city_explanation = "岗位城市或目标城市偏好未填写。"
    if job.city and target_cities:
        city_status = (
            "meets"
            if any(city.casefold() in job.city.casefold() or job.city.casefold() in city.casefold() for city in target_cities)
            else "does_not_meet"
        )
        city_explanation = (
            "岗位城市符合已保存的目标城市。"
            if city_status == "meets"
            else "岗位城市不在已保存的目标城市中；这表示偏好不一致，不代表无法申请。"
        )
    criteria.append(
        _preference_criterion(
            key="city",
            label="城市偏好",
            requirement=job.city,
            candidate_value="、".join(target_cities) or None,
            explanation=city_explanation,
            status=city_status,
        )
    )

    target_roles = profile.target_roles if profile else []
    role_status = "unknown"
    role_explanation = "岗位职位或目标岗位偏好未填写。"
    if job.title and target_roles:
        normalized_title = job.title.casefold()
        role_status = (
            "meets"
            if any(role.casefold() in normalized_title or normalized_title in role.casefold() for role in target_roles)
            else "does_not_meet"
        )
        role_explanation = (
            "岗位名称与已保存的目标岗位文本相符。"
            if role_status == "meets"
            else "岗位名称与已保存的目标岗位文本未匹配；请检查岗位名称和偏好关键词。"
        )
    criteria.append(
        _preference_criterion(
            key="target_role",
            label="岗位偏好",
            requirement=job.title,
            candidate_value="、".join(target_roles) or None,
            explanation=role_explanation,
            status=role_status,
        )
    )

    industries = profile.industries if profile else []
    job_industry = company.industry if company else None
    industry_status = "unknown"
    industry_explanation = "行业信息或行业偏好未填写。"
    if job_industry and industries:
        industry_status = (
            "meets"
            if any(item.casefold() in job_industry.casefold() or job_industry.casefold() in item.casefold() for item in industries)
            else "does_not_meet"
        )
        industry_explanation = (
            "岗位行业符合已保存的偏好。"
            if industry_status == "meets"
            else "岗位行业与已保存的偏好不一致。"
        )
    criteria.append(
        _preference_criterion(
            key="industry",
            label="行业偏好",
            requirement=job_industry,
            candidate_value="、".join(industries) or None,
            explanation=industry_explanation,
            status=industry_status,
        )
    )

    known_skills = [skill.strip() for skill in (profile.skills if profile else []) if skill.strip()]
    skills: list[MatchSkillRead] = []
    for required in job.required_skills:
        excerpt = _evidence_for(resume_text, required)
        profile_match = any(item.casefold() == required.casefold() for item in known_skills)
        skills.append(
            MatchSkillRead(
                skill=required,
                status="evidenced" if excerpt or profile_match else "not_found",
                evidence=excerpt or ("个人档案技能：" + required if profile_match else None),
            )
        )

    return JobMatchRead(
        job_id=job.id,
        resume_id=resume.id,
        resume_filename=resume.filename,
        criteria=criteria,
        skills=skills,
        disclaimer=(
            "这是对已填写条件和简历文字的规则比对，不是录用概率或完整能力评估。"
            "“未找到”只表示当前资料没有写出该技能，不代表你不具备。"
        ),
    )
