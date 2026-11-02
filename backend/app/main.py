"""FastAPI application factory and health endpoint."""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db import (
    SCHEMA_OUTDATED_CODE,
    SCHEMA_OUTDATED_DETAIL,
    create_session_factory,
    is_missing_schema_error,
    session_dependency,
)
from app.models import AgentRun, Base, utc_now
from app.routes.agent import router as agent_router
from app.routes.account import router as account_router
from app.routes.auth import router as auth_router
from app.routes.companies import router as companies_router
from app.routes.jobs import router as jobs_router
from app.routes.knowledge import router as knowledge_router
from app.routes.matching import router as matching_router
from app.routes.profile import router as profile_router
from app.routes.research import router as research_router
from app.routes.reminders import router as reminders_router
from app.routes.reminders import notifications_router
from app.routes.resumes import router as resumes_router
from app.routes.skills import router as skills_router
from app.schemas import HealthRead
from app.services.job_extraction import (
    JobExtractionProvider,
    OpenAICompatibleJobExtractionProvider,
)
from app.services.knowledge import (
    EmbeddingProvider,
    KnowledgeAnswerProvider,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerProvider,
)
from app.services.company_research import (
    TavilySearchProvider,
    CompanyResearchSummaryProvider,
    OpenAICompatibleCompanyResearchSummarizer,
    PublicSearchProvider,
    create_company_research_mcp_server,
)
from app.services.skills import SkillProvider, OpenAICompatibleSkillProvider
from app.services.task_planner import TaskPlannerProvider, OpenAICompatibleTaskPlanner
from app.services.skill_graph import in_memory_checkpointer_for

logger = logging.getLogger(__name__)


def _schema_outdated_response() -> JSONResponse:
    """Return an actionable migration error without exposing SQL or user data."""

    return JSONResponse(
        status_code=503,
        content={"code": SCHEMA_OUTDATED_CODE, "detail": SCHEMA_OUTDATED_DETAIL},
    )


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    job_extraction_provider: JobExtractionProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    knowledge_answer_provider: KnowledgeAnswerProvider | None = None,
    company_research_search_provider: PublicSearchProvider | None = None,
    company_research_summarizer: CompanyResearchSummaryProvider | None = None,
    skill_provider: SkillProvider | None = None,
    task_planner_provider: TaskPlannerProvider | None = None,
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
            if engine is not None and inspect(engine).has_table("agent_runs"):
                with factory() as session:
                    stale_runs = session.query(AgentRun).filter(
                        AgentRun.status.in_(("queued", "running"))
                    )
                    for run in stale_runs:
                        run.status = "failed"
                        run.error_code = "interrupted_by_restart"
                        run.error_message = "API 服务重启，中断了任务；你可以重试。"
                        run.finished_at = utc_now()
                        run.events = [
                            *(run.events or []),
                            {
                                "id": len(run.events or []) + 1,
                                "event": "failed",
                                "message": run.error_message,
                                "code": run.error_code,
                                "created_at": utc_now().isoformat(),
                            },
                        ]
                    session.commit()
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="OfferPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.session_factory = factory
    app.state.job_extraction_provider = (
        job_extraction_provider or OpenAICompatibleJobExtractionProvider()
    )
    app.state.embedding_provider = embedding_provider or OpenAICompatibleEmbeddingProvider()
    app.state.knowledge_answer_provider = (
        knowledge_answer_provider or OpenAICompatibleKnowledgeAnswerProvider()
    )
    search_provider = company_research_search_provider or TavilySearchProvider()
    app.state.company_research_search_provider = search_provider
    app.state.company_research_summarizer = (
        company_research_summarizer or OpenAICompatibleCompanyResearchSummarizer()
    )
    app.state.skill_provider = skill_provider or OpenAICompatibleSkillProvider()
    app.state.task_planner_provider = task_planner_provider or OpenAICompatibleTaskPlanner()
    app.state.skill_checkpoint_saver = in_memory_checkpointer_for(app_settings.database_url)
    app.state.company_research_mcp_server = create_company_research_mcp_server(
        app_settings, search_provider
    )

    @app.exception_handler(DBAPIError)
    async def handle_database_error(request: Request, error: DBAPIError) -> JSONResponse:
        """Translate schema failures into a controlled, actionable API response."""

        if is_missing_schema_error(error):
            logger.error(
                "Database schema is outdated for %s %s; run alembic upgrade head",
                request.method,
                request.url.path,
            )
            return _schema_outdated_response()
        logger.error(
            "Database request failed for %s %s (%s)",
            request.method,
            request.url.path,
            type(error.orig).__name__,
        )
        return JSONResponse(status_code=500, content={"detail": "Database request failed"})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(account_router, prefix="/api/v1")
    app.include_router(companies_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(resumes_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(matching_router, prefix="/api/v1")
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(reminders_router, prefix="/api/v1")
    app.include_router(notifications_router, prefix="/api/v1")
    app.include_router(skills_router, prefix="/api/v1")

    @app.get("/health", response_model=HealthRead, tags=["system"])
    def health(
        session: Session = Depends(session_dependency(factory)),
    ) -> HealthRead | JSONResponse:
        """Check database connectivity and presence of the current model schema."""

        try:
            session.execute(text("SELECT 1"))
            existing_tables = set(inspect(session.get_bind()).get_table_names())
            missing_tables = set(Base.metadata.tables) - existing_tables
            if missing_tables:
                logger.error(
                    "Database schema is missing tables: %s",
                    ", ".join(sorted(missing_tables)),
                )
                return _schema_outdated_response()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return HealthRead(status="ok", database="ok")

    return app


app = create_app()
