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
