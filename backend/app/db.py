"""Database engine, session factory, and request-scoped session dependency."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from collections.abc import Generator


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
