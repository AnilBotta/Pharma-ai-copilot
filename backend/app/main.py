"""FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.api.routes import router
from app.config import get_settings
from app.documents.repository import DocumentRepository
from app.documents.routes import router as documents_router
from app.llm.provider import ModelProvider
from app.manager.repository import ManagerRepository
from app.manager.routes import router as manager_router
from app.pdp.repository import PdpRepository
from app.pdp.routes import router as pdp_router
from app.repository import Repository
from app.sas_validation.ai_reviewer import (
    ModelProviderReviewAdapter,
    SASValidationAIReviewer,
)
from app.sas_validation.authorization import ReviewerAuthorizationService
from app.sas_validation.repository import SASValidationRepository
from app.sas_validation.routes import router as sas_validation_router
from app.sas_validation.storage import SASValidationStorage
from app.sas_validation.workflow import ManualValidationWorkflow
from app.settings_module.repository import RecipientRepository
from app.settings_module.routes import router as settings_router
from app.statistics.routes import router as statistics_router

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, which would put API keys carried as
    # query parameters (NCBI does this) into the logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from be_stats import __version__ as be_stats_version

    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Pharma R&D Copilot API")
    logger.info("Configuration: %s", settings.safe_summary())

    try:
        pool = await db.create_pool(settings)
        app.state.repository = Repository(pool)
        app.state.pdp_repository = PdpRepository(pool)
        app.state.manager_repository = ManagerRepository(pool)
        app.state.document_repository = DocumentRepository(pool)
        app.state.recipient_repository = RecipientRepository(pool)

        # SAS validation is an OPTIONAL service beside the engine, never in
        # front of it. It is assembled here so the routes have a collaborator;
        # no ordinary calculation path reads it, and a deployment where
        # Supabase Storage is unavailable still serves every bioequivalence
        # calculation.
        app.state.sas_validation_workflow = ManualValidationWorkflow(
            repository=SASValidationRepository(pool),
            storage=SASValidationStorage(settings),
            # Recorded in every package manifest, so "which engine version
            # produced this" is answerable years later without archaeology.
            be_stats_version=be_stats_version,
            git_sha=os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown"),
            # ADVISORY ONLY. This assistant reads evidence and recommends; it
            # cannot approve anything, and a deployment without a model is a
            # supported state rather than a degraded one - the human review
            # runs on the deterministic evidence either way.
            ai_reviewer=SASValidationAIReviewer(
                provider=ModelProviderReviewAdapter(ModelProvider(settings))
            ),
        )

        # Who may record an oracle closure. Separate from the workflow because
        # it answers a different question - "may this person decide" rather
        # than "what does the evidence say" - and because the route must be
        # able to refuse before the workflow is ever consulted.
        app.state.sas_reviewer_authorization = ReviewerAuthorizationService(pool)
    except Exception:
        # Start anyway so /health can report the problem rather than the whole
        # service being unreachable.
        logger.exception("Database unavailable at startup; API starts degraded")
        app.state.repository = None
        app.state.pdp_repository = None
        app.state.manager_repository = None
        app.state.document_repository = None
        app.state.recipient_repository = None
        # None rather than a half-built workflow: the SAS routes then answer
        # 503 with an explanation instead of failing somewhere less legible.
        app.state.sas_validation_workflow = None
        # And no authorization service, so the review endpoint refuses rather
        # than reaching a pool that does not exist. FAILING CLOSED IS THE ONLY
        # ACCEPTABLE DIRECTION for a governed decision: a degraded start must
        # never be the reason an unauthorised user records an oracle closure.
        app.state.sas_reviewer_authorization = None

    yield

    await db.close_pool()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Pharma R&D Copilot API",
        version="0.1.0",
        description=(
            "Research-support API. Provides decision support only; it does not "
            "provide medical, regulatory, toxicological, clinical or legal decisions."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(router, prefix="/api")
    app.include_router(pdp_router, prefix="/api")
    app.include_router(manager_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(sas_validation_router, prefix="/api")
    # Reads no database: the capability surface is code, so it stays available
    # in exactly the degraded deployment where somebody most needs to ask what
    # still works.
    app.include_router(statistics_router, prefix="/api")

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        # Log the detail, return a generic message: stack traces and driver
        # errors leak schema and configuration.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred."},
        )

    return app


app = create_app()
