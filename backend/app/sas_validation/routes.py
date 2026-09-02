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
from datetime import datetime

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
from app.sas_validation.attestation import (
    ATTESTATION_LIMITATION,
    AttestationRejected,
    EvidenceOrigin,
)
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
from app.sas_validation.integrity import ProgramExecutionIntegrity
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
from app.sas_validation.workflow import (
    DeterministicEvidenceNotReady,
    ManualValidationWorkflow,
    UploadRejected,
)

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


@router.get("/packages")
async def list_packages(
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """The packages this organisation has generated, newest first.

    WHY THIS EXISTS

    Without it the interface could only ever reach a package it had generated
    in the current browser tab. A reload lost the reference, and a package
    generated anywhere else - another session, another operator, a script - was
    unreachable entirely: the Download and Upload controls stayed disabled with
    no way to re-enable them short of generating a second package.

    That is worse than an inconvenience. Generating again to get a download
    button back produces a DIFFERENT package id and archive hash, so a customer
    could end up running one package while we hold the record of another.

    Returns metadata only. No signed URL is minted here - that is
    `/packages/{id}/download`, which audits each issue - and no archive bytes
    cross this endpoint.
    """
    rows = await workflow.list_packages(tenant_id=resolve_tenant(user))
    return {
        "packages": [
            {
                "package_id": row["id"],
                "case_id": row["case_id"],
                "archive_sha256": row["archive_sha256"],
                "archive_bytes": row["archive_bytes"],
                "be_stats_version": row["be_stats_version"],
                "git_sha": row["git_sha"],
                "generated_at": row["generated_at"],
            }
            for row in rows
        ]
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
    evidence_origin: str = Form(default=EvidenceOrigin.TEST_FIXTURE.value),
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Upload the structured result validate.sas wrote.

    `evidence_origin` DEFAULTS TO TEST_FIXTURE, and that direction is the whole
    point. A fixture CSV and a real SAS CSV are the same shape, so an omitted
    field cannot be resolved from the file - and of the two possible mistakes,
    "real evidence recorded as a fixture" is recoverable by re-declaring it,
    while "a dry-run artefact recorded as regulatory evidence" is the failure
    that puts fiction in a submission.
    """
    payload = await file.read()
    try:
        origin = EvidenceOrigin(evidence_origin)
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown evidence origin '{evidence_origin}'; expected one of "
            + ", ".join(member.value for member in EvidenceOrigin),
        ) from error

    if origin is EvidenceOrigin.MANAGED_SAS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "managed_sas is a reserved value with no implementation behind it. "
            "Nothing in this deployment can produce managed SAS output, so an "
            "upload claiming that origin would be describing something that "
            "did not happen.",
        )

    try:
        outcome = await workflow.upload_result(
            tenant_id=resolve_tenant(user),
            actor=user.id,
            package_id=package_id,
            filename=file.filename or "be_result.csv",
            content_type=file.content_type,
            payload=payload,
            evidence_origin=origin,
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
        "evidence_origin": origin.value,
        "is_regulatory_evidence": origin.is_regulatory_evidence,
        "note": (
            "Recorded as external validation evidence. Uploading a SAS result "
            "does not automatically validate or approve a statistical method."
            if origin.is_regulatory_evidence
            else "OPERATIONAL DRY RUN - NOT SAS VALIDATION EVIDENCE. This run "
            "is recorded as a test fixture and must never be cited as "
            "regulatory evidence, whatever the numbers in it say."
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


class AttestationRequest(BaseModel):
    """What the operator declares. Note what is absent: the archive hash.

    The hash comes from the stored package, not from the request. An operator
    who could supply it could attest to a package other than the one we
    generated, and the attestation would then name bytes nobody sent them.
    """

    operator_name: str = Field(min_length=1, max_length=200)
    operator_organization: str = Field(min_length=1, max_length=200)

    #: Must be an explicit true. An unaffirmed attestation is a skipped form,
    #: not a weaker claim, and storing one would put an unmade statement into
    #: the evidence record.
    confirmed: bool = False

    operator_email: str | None = Field(default=None, max_length=320)
    sas_version: str | None = Field(default=None, max_length=120)
    operating_environment: str | None = Field(default=None, max_length=200)
    executed_at: datetime | None = None


@router.post("/runs/{run_id}/attestation", status_code=status.HTTP_201_CREATED)
async def record_attestation(
    run_id: str,
    request: AttestationRequest,
    user: AuthenticatedUser = Depends(current_user),
    workflow: ManualValidationWorkflow = Depends(get_workflow),
) -> dict[str, object]:
    """Record the operator's declaration about one execution.

    NOT A REVIEW, AND NOT A VERIFICATION.

    Any authenticated user may submit this, because the person entering a
    client's execution details is doing clerical work, not deciding anything.
    The governed act is the human review, which is gated separately.

    And it upgrades no integrity state. The response says so explicitly rather
    than leaving the caller to infer it from an absence.
    """
    try:
        attestation = await workflow.record_attestation(
            tenant_id=resolve_tenant(user),
            actor=user.id,
            run_id=run_id,
            operator_name=request.operator_name,
            operator_organization=request.operator_organization,
            confirmed=request.confirmed,
            operator_email=request.operator_email,
            sas_version=request.sas_version,
            operating_environment=request.operating_environment,
            executed_at=request.executed_at,
        )
    except AttestationRejected as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)
        ) from error
    except PackageNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run") from error

    return {
        "attestation_version": attestation.attestation_version,
        "attestation_text": attestation.attestation_text,
        "attestation_hash": attestation.attestation_hash,
        "operator_name": attestation.operator_name,
        "operator_organization": attestation.operator_organization,
        "sas_version": attestation.sas_version,
        # Returned on every attestation, so no client can render this as a
        # green tick. It is the same string the stored row carries.
        "limitation": ATTESTATION_LIMITATION,
        "program_execution_integrity": (
            ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION.value
        ),
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
        # The reviewer's document: package, execution, integrity, statistics,
        # reference context, AI analysis, human reviews - each labelled.
        "evidence_report": context["evidence_report"],
        "evidence_origin": context["evidence_origin"],
        "is_regulatory_evidence": context["is_regulatory_evidence"],
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
    except DeterministicEvidenceNotReady as error:
        # 409, not 422: the request is well-formed and the run exists. What is
        # wrong is the ORDER - the deterministic facts the assistant reads have
        # not been assembled yet.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "DETERMINISTIC_EVIDENCE_NOT_READY", "message": str(error)},
        ) from error

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
