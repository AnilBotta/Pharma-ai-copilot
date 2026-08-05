"""HTTP API.

Run creation returns immediately with a run id; the research itself is executed
by a separate worker process. That is not an optimisation - a research run makes
dozens of external calls and takes minutes, which no HTTP request should hold
open.

Progress is delivered by server-sent events tailing the run_events table, so the
client renders what the worker actually recorded.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    CreateProjectRequest,
    CreateRunRequest,
    DashboardResponse,
    EventResponse,
    EvidenceResponse,
    HealthResponse,
    IntegrationStatus,
    ProjectResponse,
    ReportSectionResponse,
    RunCreatedResponse,
    RunDetail,
    RunErrorResponse,
    RunSummary,
    SearchQueryResponse,
)
from app.auth import AuthenticatedUser, current_user, get_repository
from app.config import Settings, get_settings
from app.repository import NotFound, Repository

logger = logging.getLogger(__name__)

router = APIRouter()

#: How often the SSE stream polls for new events. Fast enough to feel live,
#: slow enough not to hammer the database for a run that emits an event every
#: few seconds.
SSE_POLL_SECONDS = 1.0
SSE_IDLE_TIMEOUT_SECONDS = 1800


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request, settings: Settings = Depends(get_settings)):
    """Unauthenticated liveness and integration status.

    Reports which integrations are configured so an operator can see at a
    glance why a run might degrade. It exposes no secret values.
    """
    from app import db
    from app.auth import describe_jwt_verification

    db_ok, db_detail = (
        await db.health_check()
        if getattr(request.app.state, "repository", None)
        else (False, "Not initialised.")
    )
    auth_ok, auth_detail = await describe_jwt_verification(settings)

    return HealthResponse(
        status="ok" if (db_ok and auth_ok) else "degraded",
        database=db_detail,
        auth=auth_detail,
        integrations=[
            IntegrationStatus(
                name=name,
                state=str(cfg["state"]),
                required=bool(cfg["required"]),
                detail=str(cfg["detail"]),
            )
            for name, cfg in settings.integration_status().items()
        ],
    )


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


@router.get("/projects", response_model=list[ProjectResponse], tags=["projects"])
async def list_projects(
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    return [_serialise(p) for p in await repository.list_projects(user.id)]


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
)
async def create_project(
    payload: CreateProjectRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    project = await repository.create_project(
        user.id,
        name=payload.name,
        description=payload.description,
        code=payload.code,
        molecule=payload.molecule,
        indication=payload.indication,
    )
    return _serialise({**project, "run_count": 0})


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


@router.post(
    "/runs",
    response_model=RunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
)
async def create_run(
    payload: CreateRunRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    """Queue a research run and return its id immediately."""
    try:
        run = await repository.create_run(
            user.id, payload.project_id, payload.model_dump()
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return RunCreatedResponse(
        run_id=str(run["id"]),
        status=run["status"],
        message="Run queued. Subscribe to /runs/{run_id}/events for progress.",
    )


@router.get("/runs", response_model=list[RunSummary], tags=["runs"])
async def list_runs(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    runs = await repository.list_runs(user.id, project_id=project_id, limit=limit)
    return [_serialise(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    try:
        return _serialise(await repository.get_run(user.id, run_id))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=list[EventResponse], tags=["runs"])
async def get_events(
    run_id: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    """Progress events after `after_id`, as JSON.

    This is what the frontend polls. It polls rather than using EventSource
    because EventSource cannot send an Authorization header, and putting an
    access token in a query string would place it in server logs and browser
    history. The SSE variant below is kept for clients that prefer streaming.
    """
    try:
        events = await repository.get_events(
            user.id, run_id, after_id=after_id, limit=limit
        )
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [_serialise(e) for e in events]


@router.get("/runs/{run_id}/events/stream", tags=["runs"])
async def stream_events(
    run_id: str,
    after_id: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    """Server-sent events tailing this run's progress.

    Closes once the run reaches a terminal state, so a finished run does not
    leave a connection open indefinitely.
    """
    try:
        await repository.get_run(user.id, run_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    async def event_stream():
        last_id = after_id
        elapsed = 0.0
        try:
            while elapsed < SSE_IDLE_TIMEOUT_SECONDS:
                events = await repository.get_events(user.id, run_id, after_id=last_id)
                for event in events:
                    last_id = event["id"]
                    yield f"event: progress\ndata: {json.dumps(_serialise(event), default=str)}\n\n"

                run = await repository.get_run(user.id, run_id)
                if run["status"] in ("completed", "failed", "cancelled"):
                    yield (
                        "event: done\n"
                        f"data: {json.dumps({'status': run['status']})}\n\n"
                    )
                    return

                if not events:
                    # Comment frame keeps proxies from closing an idle stream.
                    yield ": keepalive\n\n"

                await asyncio.sleep(SSE_POLL_SECONDS)
                elapsed += SSE_POLL_SECONDS
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SSE stream failed for run %s", run_id)
            yield (
                "event: error\n"
                'data: {"message": "Progress stream failed. Reload to reconnect."}\n\n'
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT, tags=["runs"])
async def cancel_run(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    """Request cancellation. The worker stops at the next node boundary."""
    try:
        await repository.request_cancel(user.id, run_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED, tags=["runs"])
async def retry_run(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    """Re-queue a failed run. It resumes from its last checkpoint."""
    try:
        await repository.retry_run(user.id, run_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"run_id": run_id, "status": "queued"}


# --------------------------------------------------------------------------- #
# Run artefacts
# --------------------------------------------------------------------------- #


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceResponse], tags=["runs"])
async def get_evidence(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    try:
        return [_serialise(e) for e in await repository.get_evidence(user.id, run_id)]
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get(
    "/runs/{run_id}/report", response_model=list[ReportSectionResponse], tags=["runs"]
)
async def get_report(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    try:
        return [_serialise(s) for s in await repository.get_report(user.id, run_id)]
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get(
    "/runs/{run_id}/queries", response_model=list[SearchQueryResponse], tags=["runs"]
)
async def get_queries(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    try:
        return [_serialise(q) for q in await repository.get_search_queries(user.id, run_id)]
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/runs/{run_id}/errors", response_model=list[RunErrorResponse], tags=["runs"])
async def get_errors(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    try:
        return [_serialise(e) for e in await repository.get_run_errors(user.id, run_id)]
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


@router.get("/dashboard", response_model=DashboardResponse, tags=["dashboard"])
async def dashboard(
    user: AuthenticatedUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
):
    summary = await repository.dashboard_summary(user.id)
    return DashboardResponse(**{k: _numeric(v) for k, v in summary.items()})


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def _serialise(row: Any) -> dict:
    """Convert asyncpg row types into JSON-friendly Python values."""
    import uuid
    from decimal import Decimal

    result = {}
    for key, value in dict(row).items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, str) and key in {
            "structured_objective", "research_plan", "contradictions",
            "evidence_gaps", "warnings", "section_confidence", "data",
        }:
            try:
                result[key] = json.loads(value)
            except (ValueError, TypeError):
                result[key] = value
        else:
            result[key] = value
    return result


def _numeric(value: Any) -> Any:
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _numeric(v) for k, v in value.items()}
    return value
