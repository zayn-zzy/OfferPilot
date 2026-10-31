"""Database engine, session dependencies, and schema error classification."""

from collections.abc import Generator
from sqlite3 import OperationalError as SQLiteOperationalError

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

SCHEMA_OUTDATED_CODE = "database_schema_outdated"
SCHEMA_OUTDATED_DETAIL = (
    "数据库结构尚未更新，请在 backend 目录执行 uv run alembic upgrade head，"
    "完成后刷新页面。"
)


def is_missing_schema_error(error: DBAPIError) -> bool:
    """Recognize missing tables or columns in SQLite and PostgreSQL drivers."""

    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate in {"42P01", "42703"}:
        return True
    if isinstance(original, SQLiteOperationalError):
        message = str(original).lower()
        return message.startswith(("no such table:", "no such column:")) or (
            "has no column named" in message
        )
    return False


def create_session_factory(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    """Build a SQLAlchemy engine and session factory for the configured database."""

    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_dependency(session_factory: sessionmaker[Session]):
    """Create a request dependency bound to one application session factory."""

    def get_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    return get_session
