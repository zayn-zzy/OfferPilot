"""Validated API input and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


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
