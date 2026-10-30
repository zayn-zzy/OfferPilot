"""Environment-backed application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
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


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""

    return Settings()
