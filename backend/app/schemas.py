"""Validated API input and response schemas."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)


ApplicationStage = Literal[
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
]


class UserCreate(BaseModel):
    """New user registration payload."""

    email: EmailStr
    password: SecretStr = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize account identity for case-insensitive uniqueness."""

        return value.strip().lower()


class UserLogin(BaseModel):
    """User login payload."""

    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize account identity for lookup."""

        return value.strip().lower()


class UserRead(BaseModel):
    """Public account fields returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    created_at: datetime


class HealthRead(BaseModel):
    """Health endpoint response."""

    status: str
    database: str


class CandidateProfileWrite(BaseModel):
    """Editable fields in a candidate's private profile."""

    graduation_year: int | None = Field(default=None, ge=1980, le=2100)
    education: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=120)
    target_roles: list[str] = Field(default_factory=list, max_length=30)
    target_cities: list[str] = Field(default_factory=list, max_length=30)
    industries: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("education", "major")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Trim free-text fields and normalize empty strings to null."""

        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("target_roles", "target_cities", "industries", "skills")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        """Trim list entries, drop blanks, and remove case-insensitive duplicates."""

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            key = item.casefold()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized


class CandidateProfileRead(CandidateProfileWrite):
    """Profile data returned to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResumeTextCreate(BaseModel):
    """Resume text pasted by the user for parsing preview."""

    filename: str = Field(default="粘贴的简历内容.txt", max_length=255)
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("text")
    @classmethod
    def normalize_resume_text(cls, value: str) -> str:
        """Reject blank input and remove leading/trailing whitespace."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("简历内容不能为空")
        return normalized


class ResumeSummary(BaseModel):
    """Resume version metadata without the full extracted text."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    source_type: str
    content_type: str
    created_at: datetime
    confirmed_at: datetime | None
    extracted_char_count: int


class ResumeDetail(ResumeSummary):
    """Resume metadata and extracted text shown in the review screen."""

    extracted_text: str


class JobPostingWrite(BaseModel):
    """User-entered job and company fields; incomplete records remain reviewable."""

    company_name: str | None = Field(default=None, max_length=200)
    company_website_url: str | None = Field(default=None, max_length=2048)
    recruitment_url: str | None = Field(default=None, max_length=2048)
    industry: str | None = Field(default=None, max_length=120)
    company_notes: str | None = Field(default=None, max_length=5000)
    title: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    job_type: str | None = Field(default=None, max_length=80)
    batch: str | None = Field(default=None, max_length=120)
    deadline: date | None = None
    education_requirement: str | None = Field(default=None, max_length=120)
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    description: str | None = Field(default=None, max_length=30_000)
    source_url: str | None = Field(default=None, max_length=2048)
    source_type: Literal["manual", "paste", "link", "agent"] = "manual"
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator(
        "company_name",
        "company_website_url",
        "recruitment_url",
        "industry",
        "company_notes",
        "title",
        "city",
        "job_type",
        "batch",
        "education_requirement",
        "description",
        "source_url",
    )
    @classmethod
    def normalize_optional_job_text(cls, value: str | None) -> str | None:
        """Trim optional text and convert blank values to null."""

        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("source_url", "company_website_url", "recruitment_url")
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        """Accept only absolute HTTP(S) links so stored evidence is clickable."""

        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("链接必须以 http:// 或 https:// 开头")
        return value

    @field_validator("required_skills", "tags")
    @classmethod
    def normalize_job_lists(cls, values: list[str]) -> list[str]:
        """Drop blanks and case-insensitive duplicates from user-maintained lists."""

        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            key = item.casefold()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized

    @model_validator(mode="after")
    def require_some_job_information(self) -> "JobPostingWrite":
        """Prevent empty rows while allowing partially known postings."""

        if not any((self.company_name, self.title, self.source_url, self.description)):
            raise ValueError(
                "请至少填写公司、职位、来源链接或岗位描述中的一项"
            )
        return self


class ApplicationUpdate(BaseModel):
    """Editable application-board details; omitted values remain unchanged."""

    status: ApplicationStage | None = None
    applied_at: date | None = None
    resume_version_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)
    next_action: str | None = Field(default=None, max_length=500)
    next_action_due: date | None = None

    @field_validator("notes", "next_action")
    @classmethod
    def normalize_application_text(cls, value: str | None) -> str | None:
        """Convert blank notes and actions to null."""

        normalized = value.strip() if value else ""
        return normalized or None


class ApplicationStatusEventRead(BaseModel):
    """One user-confirmed transition in an application timeline."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_status: str | None
    to_status: ApplicationStage
    created_at: datetime


class ApplicationRead(BaseModel):
    """Application tracking data attached to a job summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ApplicationStage
    applied_at: date | None
    resume_version_id: UUID | None
    notes: str | None
    next_action: str | None
    next_action_due: date | None
    created_at: datetime
    updated_at: datetime


class JobPostingRead(BaseModel):
    """Job, company, source, and optional board data shown to its owner."""

    id: UUID
    company_id: UUID | None
    company_name: str | None
    company_website_url: str | None
    recruitment_url: str | None
    industry: str | None
    company_notes: str | None
    title: str | None
    city: str | None
    job_type: str | None
    batch: str | None
    deadline: date | None
    education_requirement: str | None
    required_skills: list[str]
    description: str | None
    source_url: str | None
    source_type: Literal["manual", "paste", "link", "agent"]
    source_captured_at: datetime
    tags: list[str]
    review_status: Literal["needs_review", "verified"]
    created_at: datetime
    updated_at: datetime
    application: ApplicationRead | None


class JobCsvPreviewRowRead(BaseModel):
    """One validated CSV row before it becomes a saved job."""

    row_number: int
    status: Literal["ready", "duplicate", "invalid"]
    company_name: str | None
    title: str | None
    city: str | None
    deadline: str | None
    source_url: str | None
    data: JobPostingWrite | None
    errors: list[str] = Field(default_factory=list)
    duplicate_detail: str | None = None


class JobCsvPreviewRead(BaseModel):
    """Validation and duplicate summary for an uploaded job CSV."""

    rows: list[JobCsvPreviewRowRead]
    ready_count: int
    duplicate_count: int
    invalid_count: int


class JobBulkImportWrite(BaseModel):
    """Owner-confirmed CSV jobs to save in one database transaction."""

    jobs: list[JobPostingWrite] = Field(min_length=1, max_length=500)


class AgentJobExtractionCreate(BaseModel):
    """User-provided job text submitted for structured extraction."""

    text: str = Field(min_length=20, max_length=30_000)
    source_url: str | None = Field(default=None, max_length=2048)

    @field_validator("text")
    @classmethod
    def normalize_source_text(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 20:
            raise ValueError("岗位描述至少需要 20 个字符")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("来源链接必须以 http:// 或 https:// 开头")
        return value.strip()


class AgentTaskRead(BaseModel):
    """Observable task state without exposing stored raw prompt text."""

    id: UUID
    task_type: Literal["job_extraction"]
    status: Literal["queued", "running", "succeeded", "failed", "confirmed"]
    source_url: str | None
    result: dict | None
    events: list[dict]
    error_code: str | None
    error_message: str | None
    model_name: str | None
    attempt_count: int
    job_id: UUID | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AgentTaskSourceRead(BaseModel):
    """Owner-only source text used for evidence review before confirmation."""

    task_id: UUID
    source_url: str | None
    source_text: str


class JobExtractionConfirm(BaseModel):
    """Optional user corrections applied before extracted data becomes a job."""

    model_config = ConfigDict(extra="forbid")

    source_url: str | None = Field(default=None, max_length=2048)
    company_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    job_type: str | None = Field(default=None, max_length=80)
    batch: str | None = Field(default=None, max_length=120)
    deadline: date | None = None
    education_requirement: str | None = Field(default=None, max_length=120)
    required_skills: list[str] | None = Field(default=None, max_length=50)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("来源链接必须以 http:// 或 https:// 开头")
        return value.strip()


class JobSourceEvidenceRead(BaseModel):
    """Original source text and field citations for a saved extracted job."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    source_url: str | None
    source_text: str
    field_evidence: dict
    captured_at: datetime
