"""HTTP surface for SAS validation.

WHAT THE ENDPOINTS DELIBERATELY CANNOT DO

There is no endpoint that changes a method's validation status, and no
parameter that could be bent into one. The furthest any route goes is
recording a reviewer's decision about a run.

There is also no endpoint that returns a secret. `GET /sas-validation` returns
`configured: true` and the non-secret configuration, which is everything the
interface needs to show an operator which environment they set up.

TENANT SCOPING

Every route resolves a tenant and passes it to the service, which checks it.
Today that tenant is the single implicit organisation migration 0001 describes;
the resolution lives in one function so there is one place to change when there
are really several.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, current_user
from app.sas_validation.canonical_data import CanonicalDatasetUnavailable
from app.sas_validation.compare import ComparisonReport
from app.sas_validation.modes import (
    ACKNOWLEDGEMENT_TEXT,
    CUSTOMER_CONTROL_NOTICE,
    MANAGED_AVAILABILITY_NOTICE,
    UNAVAILABLE_REASON,
    OracleClosureDecision,
    SASIntegrationMode,
    mode_is_available,
)
from app.sas_validation.repository import PackageNotFound
from app.sas_validation.storage import StorageError
from app.sas_validation.targets import TARGETS
from app.sas_validation.workflow import ManualValidationWorkflow, UploadRejected

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sas-validation", tags=["sas-validation"])

#: The single implicit organisation. Migration 0001: "Single-organisation MVP:
#: every profile belongs to the same implicit org, so there is no organisations
#: table yet."
IMPLICIT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def resolve_tenant(user: AuthenticatedUser) -> str:
    """The caller's organisation.

    PREPARED FOR TENANT ISOLATION; THIS DEPLOYMENT IS SINGLE-ORGANISATION.

    There is no identity-to-organisation mapping in this system, so this
    returns one constant and the data model's isolation invariants are
    exercised only by the service-layer tests. This is not runtime
    multi-tenancy and must not be described as such.

    When multi-tenancy arrives, this function derives membership from the
    AUTHENTICATED SERVER-SIDE IDENTITY - never from a client-supplied
    tenant_id, which would let a caller choose whose data to read. No route
    below accepts one, and none should.
    """
    return IMPLICIT_TENANT_ID


# --------------------------------------------------- reviewer authorization ---

#: Roles that could govern a validation review, in the vocabulary migration
#: 0007 already seeds. Listed rather than invented: a duplicate role system
#: would be a second answer to "who may decide", and nothing would say which
#: one won.
REVIEWER_ROLE_KEYS = ("system_administrator", "executive")

#: WHY REVIEW RECORDING IS CLOSED AT THE HTTP BOUNDARY.
#:
#: The roles exist. What does not exist is any way for THIS BACKEND to check
#: them:
#:
#:   private.has_role(role_key, project_id)  reads auth.uid(), which is NULL
#:                                           when the backend connects as the
#:                                           service role
#:   private.user_capabilities(user, project) is project-scoped by signature
#:                                            and cannot answer "is this user
#:                                            an executive" globally
#:
#: and there is no `user_has_global_role(user_id, role_key)` twin. On top of
#: that, `settings_module/routes.py` records that nobody currently holds either
#: org-level role.
#:
#: So the honest options were: let every signed-in user record an oracle
#: closure, invent a parallel permission system, or refuse. Recording a
#: governed validation decision is not something to leave open by default, and
#: a second role system would be worse than the gap it filled.
REVIEWER_AUTHORIZATION_CONFIGURED = False

REVIEWER_AUTHORIZATION_NOT_CONFIGURED = "REVIEWER_AUTHORIZATION_NOT_CONFIGURED"


def require_reviewer(user: AuthenticatedUser) -> AuthenticatedUser:
    """Refuse until privileged reviewer authorization exists.

    Returns 501 rather than 403: 403 would tell an operator they lack a
    permission, when the truth is that the permission cannot yet be checked by
    anyone. The distinction matters to whoever reads the log.
    """
    if not REVIEWER_AUTHORIZATION_CONFIGURED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": REVIEWER_AUTHORIZATION_NOT_CONFIGURED,
                "message": (
                    "Recording a validation review requires a privileged "
                    "reviewer role, and this deployment cannot yet check one. "
                    "The roles exist, but the backend connects as the service "
                    "role, where private.has_role() reads a null auth.uid(), "
                    "and no global-role check for an explicit user id exists."
                ),
                "required_roles": list(REVIEWER_ROLE_KEYS),
                "what_would_enable_it": (
                    "A private.user_has_global_role(p_user_id, p_role_key) "
                    "function, of the explicit-user shape migration 0016 "
                    "already established, plus at least one holder of a "
                    "reviewer role granted through the CLI."
                ),
            },
        )
    return user  # pragma: no cover - unreachable until the flag flips


def _serialise(report: ComparisonReport) -> dict[str, object]:
    """The comparison as the interface renders it.

    Every reference value carries its evidence status, so a reader can see
    which numbers a regulator published and which came from software - without
    that, `19.8906` and `102.26` look equally authoritative on a screen.
    """
    return {
        "status": report.status.value,
        "sas_version": report.sas_version,
        "convergence_status": report.convergence_status,
        # Three answers, never one. In particular the API must not imply that
        # the executed program was verified: for a customer-run upload it
        # cannot be. See integrity.py.
        "integrity": report.integrity.as_dict(),
        "quantities": [
            {
                "quantity": q.quantity,
                "sas_value": q.sas_value,
                "engine_value": q.engine_value,
                "agreement": q.agreement.value,
            }
            for q in report.quantities
        ],
        "reference_context": [
            {
                "quantity": r.quantity,
                "value": r.value,
                "evidence_status": r.status.value,
                "regulator_confirmed": r.is_regulator_confirmed,
                "source": r.source,
                "note": r.note,
            }
            for r in report.reference_context
        ],
        "reviewer_question": report.reviewer_question,
        "notes": list(report.notes),
    }


class ReviewRequest(BaseModel):
    """Note what is absent: any field naming the reviewer.

    The reviewer's identity comes from the authenticated server context. A
    request-body user id would let a caller attribute a governed validation
    decision to somebody else, which is the one thing an audit trail exists to
    prevent.
    """

    decision: OracleClosureDecision
    notes: str = Field(min_length=1)


@router.get("/options")
def list_options() -> dict[str, object]:
    """What this organisation may actually do, and honest text for the rest.

    The interface renders from this rather than deciding for itself, so the
    API and the screen cannot drift into promising different things.
    """
    options = []
    for mode, title, description in (
        (
            SASIntegrationMode.MANAGED,
            "Managed SAS",
            "Use our managed SAS validation service.",
        ),
        (
            SASIntegrationMode.CUSTOMER_VIYA,
            "Connect my SAS",
            "Use your organisation's SAS environment.",
        ),
        (
            SASIntegrationMode.MANUAL_UPLOAD,
            "Manual validation",
            "Generate a SAS package, run it internally, and upload the results.",
        ),
    ):
        available = mode_is_available(mode)
        options.append(
            {
                "mode": mode.value,
                "title": title,
                "description": description,
                "available": available,
                "unavailable_reason": (
                    None if available else UNAVAILABLE_REASON.get(mode)
                ),
                "notice": (
                    MANAGED_AVAILABILITY_NOTICE
                    if mode is SASIntegrationMode.MANAGED
                    else CUSTOMER_CONTROL_NOTICE
                ),
            }
        )
    return {
        "options": options,
        "acknowledgement_text": ACKNOWLEDGEMENT_TEXT,
        "cases": [
            {
                "case_id": target.case_id,
                "title": target.title,
                "design": target.design,
                "purpose": target.purpose,
                "reviewer_question": target.reviewer_question,
                "references": [
                    {
                        "quantity": r.quantity,
                        "value": r.value,
                        "evidence_status": r.status.value,
                        "regulator_confirmed": r.is_regulator_confirmed,
                        "source": r.source,
                        "note": r.note,
                    }
                    for r in target.references
                ],
            }
            for target in TARGETS.values()
        ],
    }


def get_workflow(request: Request) -> ManualValidationWorkflow:
    """The workflow, assembled at startup and hung off app state.

    The same shape as `documents/routes.py::get_document_repository`, so there
    is one way this application resolves a per-request collaborator rather than
    two.
    """
    workflow = getattr(request.app.state, "sas_validation_workflow", None)
    if workflow is None:  # pragma: no cover - misconfiguration, not a path
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "SAS validation is not configured in this deployment. The "
                "package generator, parser and comparison are available; "
                "storage and persistence are not."
            ),
        )
    return workflow


class GeneratePackageRequest(BaseModel):
    """A case id, and deliberately nothing else.

    No observations, no SAS code, no model text, no expected denominator df, no
    package hash. The server loads the approved dataset for a predefined case
    itself, so a browser cannot submit a modified version of the regulatory
    data under a case id that claims to be about EMA Data set II.
    """

    validation_case_id: str = Field(min_length=1, max_length=128)


@router.post("/packages", status_code=status.HTTP_201_CREATED)
async def generate_package(
    request: GeneratePackageRequest,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Generate an immutable package for a predefined case."""
    try:
        generated = await workflow.generate(
            tenant_id=resolve_tenant(user),
            actor=user.id,
            case_id=request.validation_case_id,
        )
    except (KeyError, CanonicalDatasetUnavailable) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except StorageError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    manifest = generated.package.manifest
    return {
        "package_id": generated.package.package_id,
        "case_id": generated.package.case_id,
        "filename": generated.filename,
        "archive_sha256": generated.archive_sha256,
        "archive_bytes": generated.archive_bytes,
        "dataset_sha256": manifest["dataset_sha256"],
        "program_sha256": manifest["program_sha256"],
        "n_observations": manifest["n_observations"],
        "generated_at": generated.package.generated_at,
        "be_stats_version": generated.package.be_stats_version,
        "note": (
            "Run this package in your organisation's SAS environment. The "
            "application does not need your SAS username, password or licence "
            "key."
        ),
    }


@router.get("/packages/{package_id}/download")
async def download_package(
    package_id: str,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """A short-lived signed link to the exact stored bytes.

    Returns the URL rather than redirecting, so the client can show the archive
    hash beside the link and a customer can check what they downloaded.
    """
    try:
        url, row = await workflow.download_url(
            tenant_id=resolve_tenant(user), actor=user.id, package_id=package_id
        )
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such package") from error
    except FileNotFoundError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except StorageError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    return {
        "download_url": url,
        "archive_sha256": row["archive_sha256"],
        "archive_bytes": row["archive_bytes"],
        "expires_in_seconds": 300,
    }


@router.post("/packages/{package_id}/result", status_code=status.HTTP_201_CREATED)
async def upload_result(
    package_id: str,
    file: UploadFile = File(...),
    run_id: str | None = Form(default=None),
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Upload the structured result validate.sas wrote."""
    payload = await file.read()
    try:
        outcome = await workflow.upload_result(
            tenant_id=resolve_tenant(user),
            actor=user.id,
            package_id=package_id,
            filename=file.filename or "be_result.csv",
            content_type=file.content_type,
            payload=payload,
            run_id=run_id,
        )
    except UploadRejected as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)
        ) from error
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such package") from error
    except StorageError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    return {
        "run_id": outcome.run_id,
        "status": outcome.status.value,
        "detail": outcome.detail,
        "artifact_sha256": outcome.artifact_sha256,
        "duplicate": not outcome.artifact_created,
        "comparison": (
            _serialise(outcome.comparison) if outcome.comparison else None
        ),
        "note": (
            "Recorded as external validation evidence. Uploading a SAS result "
            "does not automatically validate or approve a statistical method."
        ),
    }


@router.post("/runs/{run_id}/log", status_code=status.HTTP_201_CREATED)
async def upload_log(
    run_id: str,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Archive the SAS log. It is never parsed for regulatory numbers."""
    payload = await file.read()
    try:
        outcome = await workflow.upload_log(
            tenant_id=resolve_tenant(user),
            actor=user.id,
            run_id=run_id,
            filename=file.filename or "sas.log",
            content_type=file.content_type,
            payload=payload,
        )
    except UploadRejected as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)
        ) from error
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from error
    except StorageError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

    return {
        "run_id": outcome.run_id,
        "status": outcome.status.value,
        "detail": outcome.detail,
        "artifact_sha256": outcome.artifact_sha256,
        "duplicate": not outcome.artifact_created,
    }


@router.post("/runs/{run_id}/review")
async def review_run(
    run_id: str,
    request: ReviewRequest,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Record a decision. Acting on it is a separate, governed change.

    STILL CLOSED - see `require_reviewer`. PR #64 established that there is no
    backend-safe global reviewer-role check, and PR #65 did not weaken that.

    The attempt is audited before it is refused, because "who tried to accept
    an oracle closure" is a question worth being able to answer.
    """
    await workflow.record_blocked_review(
        tenant_id=resolve_tenant(user), actor=user.id, run_id=run_id
    )
    require_reviewer(user)
    raise AssertionError(  # pragma: no cover - require_reviewer always raises
        "require_reviewer must refuse while authorization is unconfigured"
    )


__all__ = ["IMPLICIT_TENANT_ID", "resolve_tenant", "router"]
