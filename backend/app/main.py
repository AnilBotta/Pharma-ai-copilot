"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app.api.routes import router
from app.config import get_settings
from app.repository import Repository

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
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Pharma R&D Copilot API")
    logger.info("Configuration: %s", settings.safe_summary())

    try:
        pool = await db.create_pool(settings)
        app.state.repository = Repository(pool)
    except Exception:
        # Start anyway so /health can report the problem rather than the whole
        # service being unreachable.
        logger.exception("Database unavailable at startup; API starts degraded")
        app.state.repository = None

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
