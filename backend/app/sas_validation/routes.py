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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, current_user
from app.sas_validation.modes import (
    ACKNOWLEDGEMENT_TEXT,
    CUSTOMER_CONTROL_NOTICE,
    MANAGED_AVAILABILITY_NOTICE,
    UNAVAILABLE_REASON,
    OracleClosureDecision,
    SASIntegrationMode,
    mode_is_available,
)
from app.sas_validation.service import (
    SASValidationDisabled,
    SASValidationService,
    TenantIsolationError,
)
from app.sas_validation.targets import TARGETS

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


class UploadRequest(BaseModel):
    package_id: str = Field(min_length=64, max_length=64)
    result_content: str
    declared_dataset_sha256: str = Field(min_length=64, max_length=64)
    declared_program_sha256: str = Field(min_length=64, max_length=64)
    sas_log: str | None = None


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


def _service() -> SASValidationService:  # pragma: no cover - wired at startup
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "SAS validation storage is not wired up in this deployment. The "
            "package generator, parser and comparison are available; "
            "persistence arrives with the store implementation."
        ),
    )


@router.get("")
def get_integration(
    user: AuthenticatedUser = Depends(current_user),
    service: SASValidationService = Depends(_service),
) -> dict[str, object]:
    """Never returns a secret - `configured: true` and nothing more."""
    integration = service.get_integration(tenant_id=resolve_tenant(user))
    if integration is None:
        return {"mode": SASIntegrationMode.NOT_CONFIGURED.value, "configured": False}
    return integration.public_view()


@router.get("/runs")
def list_runs(
    user: AuthenticatedUser = Depends(current_user),
    service: SASValidationService = Depends(_service),
) -> dict[str, object]:
    runs = service.list_runs(tenant_id=resolve_tenant(user))
    return {
        "runs": [
            {
                "run_id": run.run_id,
                "package_id": run.package_id,
                "case_id": run.case_id,
                "status": run.status.value,
                "review_status": run.review_status.value,
                "sas_version": run.sas_version,
                "uploaded_at": run.uploaded_at,
            }
            for run in runs
        ]
    }


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
def upload_result(
    request: UploadRequest,
    user: AuthenticatedUser = Depends(current_user),
    service: SASValidationService = Depends(_service),
) -> dict[str, object]:
    try:
        run = service.record_upload(
            tenant_id=resolve_tenant(user),
            actor_user_id=user.id,
            package_id=request.package_id,
            result_content=request.result_content,
            declared_dataset_sha256=request.declared_dataset_sha256,
            declared_program_sha256=request.declared_program_sha256,
            sas_log=request.sas_log,
            # The engine declines to compute the partial-replicate case: the
            # capability is NOT_IMPLEMENTED and refuses rather than producing
            # an unvalidated number. The SAS result is still recorded.
            engine_result=None,
        )
    except TenantIsolationError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except SASValidationDisabled as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "note": (
            "Recorded as external validation evidence. This does not change "
            "any method's validation status."
        ),
    }


@router.post("/runs/{run_id}/review")
def review_run(
    run_id: str,
    request: ReviewRequest,
    user: AuthenticatedUser = Depends(current_user),
    service: SASValidationService = Depends(_service),
) -> dict[str, object]:
    """Record a decision. Acting on it is a separate, governed change.

    Closed in this release - see `require_reviewer`. The domain service is
    complete and tested; only the HTTP door is shut, because there is no way
    yet to tell a reviewer from any other signed-in user.
    """
    reviewer = require_reviewer(user)
    try:
        run = service.record_review(
            tenant_id=resolve_tenant(reviewer),
            # From the authenticated context, never from the request body.
            reviewer_user_id=reviewer.id,
            run_id=run_id,
            decision=request.decision,
            notes=request.notes,
        )
    except TenantIsolationError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    return {
        "run_id": run.run_id,
        "review_status": run.review_status.value,
        "status": run.status.value,
        "note": (
            "The decision is recorded. Changing FDA_REPLICATE_STANDARD_ABE_"
            "PARTIAL remains a separate statistical change that only a "
            "governed implementation PR may make."
        ),
    }


__all__ = ["IMPLICIT_TENANT_ID", "resolve_tenant", "router"]
