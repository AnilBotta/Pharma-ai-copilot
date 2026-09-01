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
from app.sas_validation.ai_reviewer import ADVISORY_LABEL
from app.sas_validation.authorization import (
    GRANT_INSTRUCTIONS,
    REVIEWER_ROLE_KEYS,
    ReviewerAuthorizationService,
    ReviewerIdentity,
)
from app.sas_validation.canonical_data import CanonicalDatasetUnavailable
from app.sas_validation.compare import ComparisonReport
from app.sas_validation.human_review import (
    ACCEPTANCE_MEANING,
    ACKNOWLEDGEMENT_TEXT,
    ACKNOWLEDGEMENT_VERSION,
    OracleClosureDecision,
    PreconditionFailed,
)
from app.sas_validation.modes import (
    CUSTOMER_CONTROL_NOTICE,
    ENVIRONMENT_ACKNOWLEDGEMENT_TEXT,
    MANAGED_AVAILABILITY_NOTICE,
    UNAVAILABLE_REASON,
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

#: `REVIEWER_ROLE_KEYS` is imported, not restated. A second copy here would be
#: a second answer to "who may decide", and the endpoint could go on reporting
#: required roles the authorization layer no longer asks about.
#:
#: PR #64 closed this endpoint because the backend could not identify an
#: authorised human. Migration 0034 supplies `private.user_has_global_role`,
#: the explicit-user twin 0016 established the precedent for, so the check is
#: now a real question with a real answer.
#:
#: The refusal below is therefore about the CALLER, not about the deployment:
#: 403, because a signed-in user genuinely lacks a permission that exists.
NOT_AN_AUTHORIZED_REVIEWER = "NOT_AN_AUTHORIZED_REVIEWER"


async def require_reviewer(
    user: AuthenticatedUser, authorization: ReviewerAuthorizationService
) -> ReviewerIdentity:
    """Resolve an authorised HUMAN, or refuse with a next step.

    The identity is built from the authenticated context only. There is no
    parameter through which a caller could name someone else, and
    `ReviewerIdentity.for_human` refuses any non-human actor type.
    """
    result = await authorization.can_review_sas_validation(user.id)
    if not result.authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": NOT_AN_AUTHORIZED_REVIEWER,
                "message": result.reason,
                "required_roles": list(REVIEWER_ROLE_KEYS),
                # A refusal with no path forward is a dead end somebody has to
                # re-derive. `requirement-labels.tsx` records what happens when
                # a control is merely greyed out.
                "how_to_grant": GRANT_INSTRUCTIONS,
            },
        )

    role = result.primary_role
    assert role is not None  # authorized implies a matched role
    return ReviewerIdentity.for_human(user_id=user.id, role_key=role)


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

    #: Required for acceptance. A checkbox a person ticks - there is no code
    #: path that sets it, and an AI has no way to reach this endpoint at all.
    acknowledged: bool = False


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
        # The ENVIRONMENT acknowledgement - "we are authorised to use this SAS"
        # - not the oracle-closure one the review screen shows.
        "acknowledgement_text": ENVIRONMENT_ACKNOWLEDGEMENT_TEXT,
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


def get_authorization(request: Request) -> ReviewerAuthorizationService:
    workflow = getattr(request.app.state, "sas_reviewer_authorization", None)
    if workflow is None:  # pragma: no cover - misconfiguration, not a path
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reviewer authorization is not configured in this deployment.",
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


@router.get("/runs/{run_id}/review")
async def review_context(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
    authorization: ReviewerAuthorizationService = Depends(get_authorization),
) -> dict[str, object]:
    """Everything the review screen renders, in three separated parts.

    WHO MAY SEE WHAT

    Any authenticated user may READ the evidence and the advisory analysis;
    neither is a governed act, and hiding the evidence from the people who
    produced it would help nobody. What is gated is DECIDING.

    `authorization.authorized` is decided here rather than guessed in the
    browser, so the decision form is absent for a caller who could not submit
    it - and a caller who forged the flag locally would still be refused by
    `require_reviewer` on POST. The screen is a convenience; the boundary is
    the endpoint.
    """
    try:
        context = await workflow.review_context(
            tenant_id=resolve_tenant(user), run_id=run_id
        )
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from error

    permission = await authorization.can_review_sas_validation(user.id)
    ai_review = context["ai_review"]

    return {
        "run_id": context["run_id"],
        "status": context["status"],
        # SECTION A. Authoritative.
        "deterministic": context["deterministic"],
        # SECTION B. Advisory, and projected rather than passed through: the
        # stored row carries the full prompt evidence and provider metadata,
        # none of which belongs on a screen.
        "ai_review": (
            None
            if ai_review is None
            else {
                "id": str(ai_review["id"]),
                "succeeded": ai_review["succeeded"],
                "recommendation": ai_review.get("recommendation"),
                "confidence": ai_review.get("confidence"),
                "response": ai_review.get("response"),
                "failure_reason": ai_review.get("failure_reason"),
                "generated_at": ai_review.get("generated_at"),
                "prompt_version": ai_review.get("prompt_version"),
            }
        ),
        "advisory_label": ADVISORY_LABEL,
        # SECTION C. Present for everyone as a statement of what would be
        # required; the form itself is rendered only when authorized is true.
        "authorization": {
            "authorized": permission.authorized,
            "role": permission.primary_role,
            "reason": permission.reason,
            "required_roles": list(REVIEWER_ROLE_KEYS),
            "how_to_grant": GRANT_INSTRUCTIONS,
        },
        "preconditions": context["preconditions"],
        "acknowledgement": {
            "version": ACKNOWLEDGEMENT_VERSION,
            "text": ACKNOWLEDGEMENT_TEXT,
        },
        "acceptance_meaning": ACCEPTANCE_MEANING,
        "human_reviews": context["human_reviews"],
    }


@router.post("/runs/{run_id}/review")
async def review_run(
    run_id: str,
    request: ReviewRequest,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
    authorization: ReviewerAuthorizationService = Depends(get_authorization),
) -> dict[str, object]:
    """Record a decision. Acting on it is a separate, governed change.

    The governed decision. A human, holding an approved role, recording a
    judgement against a frozen snapshot of the evidence.

    An unauthorised attempt is AUDITED before it is refused, because "who tried
    to accept an oracle closure" is worth being able to answer.

    Accepting does NOT change any method's validation status and does not set
    `partial_oracle_ready`. It records that this SAS run is suitable evidence
    for a separate, governed statistical task.
    """
    tenant_id = resolve_tenant(user)
    try:
        reviewer = await require_reviewer(user, authorization)
    except HTTPException:
        await workflow.record_blocked_review(
            tenant_id=tenant_id, actor=user.id, run_id=run_id
        )
        raise

    try:
        record = await workflow.record_human_review(
            tenant_id=tenant_id,
            reviewer=reviewer,
            run_id=run_id,
            decision=request.decision,
            notes=request.notes,
            acknowledged=request.acknowledged,
        )
    except PreconditionFailed as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "PRECONDITIONS_NOT_MET", "failures": list(error.failures)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)
        ) from error
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from error

    return {
        "review_id": record["review_id"],
        "decision": record["decision"],
        "reviewer_role": reviewer.role_key,
        "actor_type": reviewer.actor_type.value,
        "evidence_snapshot_hash": record["evidence_snapshot_hash"],
        "note": ACCEPTANCE_MEANING,
    }


@router.post("/runs/{run_id}/ai-review", status_code=status.HTTP_201_CREATED)
async def generate_ai_review(
    run_id: str,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Ask the assistant for an advisory analysis.

    Available to any authenticated user, because reading an analysis is not a
    governed act - and because a reviewer who cannot see the assistant's view
    before deciding is worse served than one who can.

    A failure here is a state, not an error: the response says the assistant
    was unavailable and the human review proceeds on deterministic evidence.
    """
    try:
        outcome = await workflow.generate_ai_review(
            tenant_id=resolve_tenant(user), actor=user.id, run_id=run_id
        )
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from error

    return {
        "ai_review_id": outcome["ai_review_id"],
        "succeeded": outcome["succeeded"],
        "advisory_label": ADVISORY_LABEL,
        "recommendation": outcome.get("recommendation"),
        "response": outcome.get("response"),
        "failure_reason": outcome.get("failure_reason"),
        "note": (
            "Advisory analysis only. It is not an approval, and a human "
            "reviewer may disagree with it in either direction."
        ),
    }




__all__ = ["IMPLICIT_TENANT_ID", "resolve_tenant", "router"]
