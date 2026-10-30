"""FastAPI application factory and health endpoint."""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db import create_session_factory, session_dependency
from app.routes.auth import router as auth_router
from app.routes.profile import router as profile_router
from app.routes.resumes import router as resumes_router
from app.schemas import HealthRead

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Create an app instance, optionally injecting test settings and a database."""

    app_settings = settings or get_settings()
    if not app_settings.secret_key.get_secret_value():
        if app_settings.environment == "production":
            raise RuntimeError("OFFERPILOT_SECRET_KEY must be configured in production")
        app_settings.secret_key = type(app_settings.secret_key)(secrets.token_urlsafe(48))
        logger.warning("No session secret configured; using an ephemeral development secret")

    engine = None
    if session_factory is None:
        engine, factory = create_session_factory(app_settings)
    else:
        factory = session_factory

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="OfferPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.session_factory = factory

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(resumes_router, prefix="/api/v1")

    @app.get("/health", response_model=HealthRead, tags=["system"])
    def health(session: Session = Depends(session_dependency(factory))) -> HealthRead:
        """Check API availability and database connectivity."""

        try:
            session.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return HealthRead(status="ok", database="ok")

    return app


app = create_app()
