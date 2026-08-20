"""HTTP API for the PDP Operations & Stage-Gate Guardian module.

Note what has no endpoint. There is no `PATCH /requirements/{id}` accepting a
status, no `POST /requirements/{id}/complete`, and no way to write a readiness
percentage. Progress is expressed by attaching evidence, confirming acceptance
and obtaining an approval from someone else; everything else is derived. When
the PDP Operations Agent arrives in Phase G it calls exactly these endpoints,
which is why the authority limit is enforced here rather than in a prompt.
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.serialise import serialise
from app.auth import AuthenticatedUser, current_user
from app.config import Settings, get_settings
from app.pdp import schemas as s
from app.pdp.repository import Conflict, Forbidden, NotFound, PdpRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pdp", tags=["pdp"])


def get_pdp_repository(request: Request) -> PdpRepository:
    repository = getattr(request.app.state, "pdp_repository", None)
    if repository is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not available."
        )
    return repository


def _translate(exc: Exception) -> HTTPException:
    """Map repository failures onto status codes.

    Forbidden is distinct from NotFound on purpose: the caller can already see
    the project, so 403 leaks nothing, and 'you may not approve this' is the
    only message that tells them what to do about it.
    """
    if isinstance(exc, NotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, Forbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, Conflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    raise exc


# --------------------------------------------------------------- templates ---


@router.get("/templates", response_model=list[s.TemplateResponse])
async def list_templates(
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Stage-gate templates available to instantiate.

    Draft templates are listed so an administrator can see what exists, but only
    an active - meaning organisationally approved - template can be instantiated.
    """
    return [serialise(t) for t in await repository.list_templates()]


# --------------------------------------------------------------- programmes ---


@router.get("/programmes", response_model=list[s.ProgrammeSummary])
async def list_programmes(
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    return [serialise(p) for p in await repository.list_programmes(user.id)]


@router.post(
    "/projects/{project_id}/instantiate",
    response_model=s.InstantiateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def instantiate(
    project_id: str,
    payload: s.InstantiateRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Copy an approved template version into this project.

    The copy is what makes later template edits safe: this project's
    requirements are its own from now on.
    """
    try:
        return await repository.instantiate(
            user.id,
            project_id,
            template_id=payload.template_id,
            start_date=payload.start_date,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}", response_model=s.ProgrammeDetail)
async def get_programme(
    project_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        result = await repository.get_programme(user.id, project_id)
    except NotFound as exc:
        raise _translate(exc) from exc

    return {
        "project": serialise(result["project"]),
        "stages": [serialise(st) for st in result["stages"]],
        "capabilities": result["capabilities"],
    }


@router.get("/projects/{project_id}/attachable-runs", response_model=list[s.AttachableRun])
async def attachable_runs(
    project_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Completed research runs on this project that may be cited as evidence."""
    try:
        return [serialise(r) for r in await repository.list_attachable_runs(user.id, project_id)]
    except NotFound as exc:
        raise _translate(exc) from exc


@router.get("/projects/{project_id}/audit", response_model=list[s.AuditEntry])
async def project_audit(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        return [serialise(e) for e in await repository.project_audit(user.id, project_id, limit)]
    except NotFound as exc:
        raise _translate(exc) from exc


# --------------------------------------------------------------- agents ---


@router.post("/stages/{stage_id}/assess", response_model=s.GateAssessmentResponse)
async def assess_gate(
    stage_id: str,
    user: AuthenticatedUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Ask the PDP Operations Agent what is actually holding this gate up.

    Advisory only, and not by convention: while the agent is acting, the
    database refuses to approve a requirement, decide a gate or set a baseline
    even if the agent is holding a fully authorised user's session. See
    migration 0022 and tests/db/test_agent_authority.py.

    It runs with the caller's identity, so it can never read a project the
    caller could not.
    """
    from app import db
    from app.llm.provider import ModelProvider
    from app.pdp.agent import assess_gate as run_assessment

    # Access is checked before anything is spent on a model call.
    try:
        project_id, _caps = await repository.capabilities_for_stage(user.id, stage_id)
    except NotFound as exc:
        raise _translate(exc) from exc

    pool = db.get_pool()
    session_id = await repository.start_agent_session(
        user.id,
        agent="pdp_operations",
        project_id=project_id,
        objective=f"Assess gate {stage_id}",
    )

    models = ModelProvider(settings)
    try:
        result = await run_assessment(
            pool=pool, models=models, user_id=user.id, stage_id=stage_id
        )
    except Exception as exc:
        await repository.finish_agent_session(session_id, error=str(exc)[:1000])
        logger.exception("Gate assessment failed for stage %s", stage_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The assessment could not be produced. The gate's own readiness and "
            "blocker list are unaffected and remain authoritative.",
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            await models.aclose()

    await repository.finish_agent_session(
        session_id,
        findings={"blocker_analysis": result["blocker_analysis"]},
        recommendations=result["recommended_actions"],
        handoff_question=result["handoff_question"],
        usage=result.get("usage"),
    )

    return {
        "session_id": session_id,
        "summary": result["summary"],
        "blocker_analysis": result["blocker_analysis"],
        "recommended_actions": result["recommended_actions"],
        "handoff_question": result["handoff_question"],
    }


@router.post("/portfolio/summary", response_model=s.PortfolioSummaryResponse)
async def portfolio_summary(
    user: AuthenticatedUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Manager Agent: what across the portfolio needs a decision.

    Scoped to programmes the caller can already see.
    """
    from app import db
    from app.llm.provider import ModelProvider
    from app.pdp.agent import summarise_portfolio

    session_id = await repository.start_agent_session(
        user.id, agent="manager", project_id=None, objective="Portfolio summary"
    )

    models = ModelProvider(settings)
    try:
        result = await summarise_portfolio(
            pool=db.get_pool(), models=models, user_id=user.id
        )
    except Exception as exc:
        await repository.finish_agent_session(session_id, error=str(exc)[:1000])
        logger.exception("Portfolio summary failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The summary could not be produced. Each programme's own readiness "
            "remains authoritative.",
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            await models.aclose()

    await repository.finish_agent_session(
        session_id,
        findings={"items": result["items"]},
        usage=result.get("usage"),
    )

    return {
        "session_id": session_id,
        "headline": result["headline"],
        "items": result["items"],
    }


# ---------------------------------------------------------- notifications ---


@router.get("/projects/{project_id}/notifications", response_model=list[s.Notification])
async def list_notifications(
    project_id: str,
    include_resolved: bool = Query(default=False),
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Open alerts for this project, most severe first.

    Recomputed from the record on every sweep, so this list reflects what is
    currently wrong rather than a log of things that once were.
    """
    try:
        rows = await repository.list_notifications(
            user.id, project_id, include_resolved=include_resolved
        )
    except NotFound as exc:
        raise _translate(exc) from exc
    return [serialise(r) for r in rows]


@router.post("/notifications/{event_id}/acknowledge", response_model=s.Notification)
async def acknowledge_notification(
    event_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Take ownership of an alert, stopping it escalating.

    It does not close the alert. Only the condition ceasing to be true does
    that — otherwise acknowledging would be a way to clear a problem from the
    list without fixing it.
    """
    try:
        row = await repository.acknowledge_notification(user.id, event_id)
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


# ----------------------------------------------------- tasks and schedule ---


@router.get("/projects/{project_id}/schedule", response_model=s.ScheduleResponse)
async def get_schedule(
    project_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Tasks, milestones and baselines, with status, variance and float derived.

    Variance is returned alongside every task rather than on request, for the
    same reason gate readiness ships with its blockers: a plan shown without its
    slip against the commitment is the comfortable half of the picture.
    """
    try:
        result = await repository.get_schedule(user.id, project_id)
    except NotFound as exc:
        raise _translate(exc) from exc

    return {
        "tasks": [serialise(t) for t in result["tasks"]],
        "milestones": [serialise(m) for m in result["milestones"]],
        "baselines": [serialise(b) for b in result["baselines"]],
        "capabilities": result["capabilities"],
    }


@router.post(
    "/projects/{project_id}/tasks",
    response_model=s.TaskSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: str,
    payload: s.CreateTaskRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        row = await repository.create_task(
            user.id, project_id, **payload.model_dump()
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise({**row, "status": "not_started", "is_critical": False})


@router.post("/tasks/{task_id}", response_model=s.TaskSummary)
async def update_task(
    task_id: str,
    payload: s.UpdateTaskRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Move forecast and actual dates.

    Baseline dates are absent from the request model on purpose, and the
    database refuses them once a baseline exists. Re-baselining is a separate,
    approved act.
    """
    try:
        row = await repository.update_task(user.id, task_id, **payload.model_dump())
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise({**row, "status": "unknown", "is_critical": False})


@router.post(
    "/tasks/{task_id}/dependencies", status_code=status.HTTP_204_NO_CONTENT
)
async def add_task_dependency(
    task_id: str,
    payload: s.AddTaskDependencyRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Make this task depend on another. Cycles are refused."""
    try:
        await repository.add_task_dependency(
            user.id,
            task_id,
            predecessor_id=payload.predecessor_id,
            dependency_type=payload.dependency_type,
            lag_days=payload.lag_days,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc


@router.post(
    "/projects/{project_id}/milestones",
    response_model=s.MilestoneSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
    project_id: str,
    payload: s.CreateMilestoneRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        row = await repository.create_milestone(
            user.id, project_id, **payload.model_dump()
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.post(
    "/projects/{project_id}/baseline",
    response_model=s.BaselineSummary,
    status_code=status.HTTP_201_CREATED,
)
async def rebaseline(
    project_id: str,
    payload: s.RebaselineRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Freeze the current forecast as the new commitment.

    Requires approval authority and a stated reason. Every previous baseline is
    kept with a snapshot of the dates it replaced.
    """
    try:
        row = await repository.rebaseline(
            user.id, project_id, name=payload.name, reason=payload.reason
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


# --------------------------------------------------- controlled documents ---


@router.get("/projects/{project_id}/documents", response_model=list[s.DocumentSummary])
async def list_documents(
    project_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """The register for this project, plus organisation-wide documents.

    Files live wherever the organisation already controls them; each version
    carries a link, not a copy.
    """
    try:
        return [serialise(d) for d in await repository.list_documents(user.id, project_id)]
    except NotFound as exc:
        raise _translate(exc) from exc


@router.post(
    "/projects/{project_id}/documents",
    response_model=s.DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    project_id: str,
    payload: s.CreateDocumentRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        row = await repository.create_document(
            user.id,
            project_id,
            document_number=payload.document_number,
            title=payload.title,
            document_type=payload.document_type,
            discipline=payload.discipline,
            description=payload.description,
            owner_user_id=payload.owner_user_id,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.get("/documents/{document_id}", response_model=s.DocumentDetail)
async def get_document(
    document_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        result = await repository.get_document(user.id, document_id)
    except NotFound as exc:
        raise _translate(exc) from exc

    item = serialise(result)
    item["versions"] = [serialise(v) for v in result.get("versions", [])]
    return item


@router.post(
    "/documents/{document_id}/versions",
    response_model=s.DocumentVersion,
    status_code=status.HTTP_201_CREATED,
)
async def add_document_version(
    document_id: str,
    payload: s.AddDocumentVersionRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Record a new version, optionally superseding the one it replaces.

    Superseding happens in the same call so the register never briefly shows
    two effective versions of one document. Any approval resting on the
    superseded version is invalidated by a database trigger.
    """
    try:
        row = await repository.add_document_version(
            user.id,
            document_id,
            version_label=payload.version_label,
            storage_url=payload.storage_url,
            status=payload.status,
            checksum=payload.checksum,
            effective_date=payload.effective_date,
            expiry_date=payload.expiry_date,
            supersedes_version_id=payload.supersedes_version_id,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.post("/document-versions/{version_id}/status", response_model=s.DocumentVersion)
async def set_document_version_status(
    version_id: str,
    payload: s.SetVersionStatusRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Move a version through its lifecycle.

    `approved` and `effective` require approval authority: they assert that
    review happened.
    """
    try:
        row = await repository.set_document_version_status(
            user.id, version_id, status=payload.status, reason=payload.reason
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


# --------------------------------------------------------------- the gate ---


@router.get("/stages/{stage_id}", response_model=s.GateWorkspace)
async def get_gate(
    stage_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """The gate workspace.

    Readiness and blockers ship together in one payload, so a client cannot
    obtain the percentage without also receiving the reasons it is not 100.
    """
    try:
        result = await repository.get_gate(user.id, stage_id)
    except NotFound as exc:
        raise _translate(exc) from exc

    return {
        "project_id": result["project_id"],
        "stage": serialise(result["stage"]),
        "readiness": serialise(result["readiness"]),
        "blockers": [serialise(b) for b in result["blockers"]],
        "requirements": [_serialise_requirement(r) for r in result["requirements"]],
        "capabilities": result["capabilities"],
    }


@router.post("/stages/{stage_id}/gate-decision", response_model=s.StageSummary)
async def decide_gate(
    stage_id: str,
    payload: s.GateDecisionRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Record a human gate decision.

    Approval is refused while any mandatory requirement is unsatisfied, and the
    refusal names the blockers. Conditional approval stays available and writes
    the outstanding blocker list into the audit record.
    """
    try:
        row = await repository.decide_gate(
            user.id,
            stage_id,
            decision=payload.decision,
            note=payload.note,
            conditions=payload.conditions,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.post("/stages/{stage_id}/unattended-threshold", response_model=s.GateWorkspace)
async def set_unattended_threshold(
    stage_id: str,
    payload: s.UnattendedThresholdRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """How long this gate may sit untouched before an alert is raised.

    Null clears the override so the gate inherits the system default set on the
    notifications settings page.
    """
    try:
        return serialise(
            await repository.set_unattended_threshold(
                user.id, stage_id, payload.days, reason=payload.reason
            )
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc


# ------------------------------------------------------------ requirements ---


@router.get("/requirements/{requirement_id}", response_model=s.RequirementDetail)
async def get_requirement(
    requirement_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """One requirement in full.

    The repository has had this since Phase C; nothing exposed it, because the
    gate workspace always arrived as a whole. The proposal confirmation card
    needs one requirement on its own - it must read the current record itself
    rather than trust what an agent said about it - so it gets a route.

    `_serialise_requirement`, not `serialise`: the latter is shallow, and a
    requirement carries nested evidence and approvals whose UUIDs would reach
    the response model unconverted. Every other requirement-returning route
    already uses this helper; writing the route without it was the omission.
    """
    try:
        row = await repository.get_requirement(user.id, requirement_id)
    except (NotFound, Forbidden) as exc:
        raise _translate(exc) from exc
    return _serialise_requirement(row)


@router.post(
    "/requirements/{requirement_id}/evidence",
    response_model=s.EvidenceLink,
    status_code=status.HTTP_201_CREATED,
)
async def attach_evidence(
    requirement_id: str,
    payload: s.AttachEvidenceRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Attach evidence. Any existing approval is superseded by this change."""
    try:
        row = await repository.attach_evidence(
            user.id,
            requirement_id,
            evidence_type=payload.evidence_type,
            research_run_id=payload.research_run_id,
            document_version_id=payload.document_version_id,
            external_url=payload.external_url,
            note=payload.note,
            title=payload.title,
            description=payload.description,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_evidence(
    evidence_id: str,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        await repository.detach_evidence(user.id, evidence_id)
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc


@router.post("/requirements/{requirement_id}/acceptance", response_model=s.RequirementDetail)
async def set_acceptance(
    requirement_id: str,
    payload: s.AcceptanceRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Confirm or withdraw that the acceptance criteria are met.

    Confirming is not approving. It records that the person doing the work
    states the criteria are satisfied; a different person must then agree.
    """
    try:
        row = await repository.set_acceptance(
            user.id, requirement_id, confirmed=payload.confirmed
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return _serialise_requirement(row)


@router.post("/requirements/{requirement_id}/decision", response_model=s.Approval)
async def decide_requirement(
    requirement_id: str,
    payload: s.DecisionRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Approve or reject a requirement.

    Refused for the owner and for whoever confirmed the acceptance criteria -
    by a database trigger, so no code path here or in a future agent can route
    around it.
    """
    try:
        row = await repository.decide_requirement(
            user.id, requirement_id, decision=payload.decision, comments=payload.comments
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.post("/requirements/{requirement_id}/review", status_code=status.HTTP_201_CREATED)
async def record_review(
    requirement_id: str,
    payload: s.ReviewRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Record an independent review. A recommendation, never an approval."""
    try:
        row = await repository.record_review(
            user.id, requirement_id, outcome=payload.outcome, comments=payload.comments
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return serialise(row)


@router.post("/requirements/{requirement_id}/assignment", response_model=s.RequirementDetail)
async def set_assignment(
    requirement_id: str,
    payload: s.AssignmentRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        row = await repository.set_assignment(
            user.id,
            requirement_id,
            owner_user_id=payload.owner_user_id,
            reviewer_user_id=payload.reviewer_user_id,
            due_date=payload.due_date,
            priority=payload.priority,
            clear_owner=payload.clear_owner,
            clear_due_date=payload.clear_due_date,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return _serialise_requirement(row)


@router.post("/requirements/{requirement_id}/block", response_model=s.RequirementDetail)
async def set_blocked(
    requirement_id: str,
    payload: s.BlockRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    try:
        row = await repository.set_blocked(
            user.id, requirement_id, blocked=payload.blocked, reason=payload.reason
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return _serialise_requirement(row)


@router.post("/requirements/{requirement_id}/not-applicable", response_model=s.RequirementDetail)
async def set_not_applicable(
    requirement_id: str,
    payload: s.NotApplicableRequest,
    user: AuthenticatedUser = Depends(current_user),
    repository: PdpRepository = Depends(get_pdp_repository),
):
    """Scope a requirement out with a justification.

    A mandatory requirement cannot be scoped out; the database refuses it.
    """
    try:
        row = await repository.set_not_applicable(
            user.id,
            requirement_id,
            not_applicable=payload.not_applicable,
            reason=payload.reason,
        )
    except (NotFound, Forbidden, Conflict) as exc:
        raise _translate(exc) from exc
    return _serialise_requirement(row)


# ------------------------------------------------------------ serialisation ---


def _serialise_requirement(row: dict) -> dict:
    """Flatten a requirement and its nested evidence and approvals."""
    item = serialise(row)
    item["evidence"] = [serialise(e) for e in row.get("evidence", [])]
    item["approvals"] = [serialise(a) for a in row.get("approvals", [])]
    current = row.get("current_approval")
    item["current_approval"] = serialise(current) if current else None
    return item


#: The mutating endpoints return `repository`'s recomputed view of the
#: requirement, not the row they wrote. See PdpRepository._requirement_view.
