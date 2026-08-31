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
#: table yet." Resolved through one function so that when there is one, exactly
#: this changes.
IMPLICIT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def resolve_tenant(user: AuthenticatedUser) -> str:
    return IMPLICIT_TENANT_ID


class UploadRequest(BaseModel):
    package_id: str = Field(min_length=64, max_length=64)
    result_content: str
    declared_dataset_sha256: str = Field(min_length=64, max_length=64)
    declared_program_sha256: str = Field(min_length=64, max_length=64)
    sas_log: str | None = None


class ReviewRequest(BaseModel):
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
    """Record a decision. Acting on it is a separate, governed change."""
    try:
        run = service.record_review(
            tenant_id=resolve_tenant(user),
            reviewer_user_id=user.id,
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
