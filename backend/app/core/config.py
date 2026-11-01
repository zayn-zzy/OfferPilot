"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="OFFERPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./offerpilot.db"
    secret_key: SecretStr = SecretStr("")
    allowed_origins: list[str] = ["http://localhost:3000"]
    session_cookie_name: str = "offerpilot_session"
    session_ttl_minutes: int = 60
    storage_dir: Path = Path("storage")
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = Field(default="", max_length=120)
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    llm_low_confidence_threshold: float = Field(default=0.75, ge=0, le=1)
    embedding_base_url: str = ""
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = Field(default="", max_length=120)
    tavily_api_key: SecretStr = SecretStr("")
    research_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    celery_broker_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""

    return Settings()
