"""The manual validation workflow, end to end.

    select case -> generate package -> store archive -> download
                -> customer runs SAS in their own environment
                -> upload result -> store artifact -> verify hashes
                -> parse -> compare -> review pending

WHAT THIS ORCHESTRATES, AND THE ORDER IT INSISTS ON

Bytes are stored and hashed BEFORE they are trusted. On upload the artifact is
written to private storage first, its SHA-256 computed by us over the bytes we
stored, and only then are the declared package hashes checked. If they fail the
run is HASH_MISMATCH and nothing is parsed - but the artifact stays, because a
rejected upload is the record of a discrepancy at the moment it is most
interesting.

Nothing here promotes a validation status, and there is no argument through
which it could. The furthest the workflow goes is producing a comparison and
leaving the run awaiting a human.

FAILURE MUST NOT LOOK LIKE SUCCESS

Package generation writes to storage and then to the database. If the database
write fails, the archive is orphaned in the bucket - unreferenced litter, which
is the safe direction. The unsafe direction would be a package row pointing at
an object that was never stored, and migration 0033's check constraint refuses
that state outright.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.sas_validation.ai_reviewer import AIRecommendation, SASValidationAIReviewer
from app.sas_validation.archive import archive_filename, build_archive
from app.sas_validation.attestation import (
    EvidenceOrigin,
    OperatorAttestation,
    build_attestation,
)
from app.sas_validation.authorization import REVIEWER_ROLE_KEYS, ReviewerIdentity
from app.sas_validation.canonical_data import load_canonical_observations
from app.sas_validation.compare import ComparisonReport, compare
from app.sas_validation.evidence_report import build_evidence_report
from app.sas_validation.human_review import (
    AcceptancePreconditions,
    OracleClosureDecision,
    build_evidence_snapshot,
    prepare_review,
)
from app.sas_validation.ingest import (
    IngestOutcome,
    ParsedSASResult,
    ResultParseError,
    parse_result_csv,
)
from app.sas_validation.integrity import (
    DatasetProvenance,
    EvidenceIntegrity,
    PackageIntegrity,
    ProgramExecutionIntegrity,
    manual_execution_integrity,
)
from app.sas_validation.logscan import contradicts_convergence, scan_log
from app.sas_validation.modes import SASIntegrationMode, SASValidationRunStatus
from app.sas_validation.package import ValidationPackage, build_package
from app.sas_validation.repository import (
    ACTION_COMPARISON_CREATED,
    ACTION_HASH_MISMATCH,
    ACTION_PARSED,
    ACTION_REVIEW_BLOCKED,
    ENTITY_RUN,
    SASValidationRepository,
)
from app.sas_validation.storage import (
    MAX_LOG_BYTES,
    MAX_RESULT_BYTES,
    SASValidationStorage,
    StorageError,
    sha256_bytes,
)
from app.sas_validation.targets import get_target

logger = logging.getLogger(__name__)

#: Only these may be uploaded, and only as text. No ZIP, no PDF, no binary:
#: the supported evidence path is the structured file our own program writes,
#: plus the log, and widening it would mean parsing formats nobody designed.
RESULT_CONTENT_TYPES = ("text/csv", "application/csv", "text/plain")
LOG_CONTENT_TYPES = ("text/plain", "text/x-log", "application/octet-stream")

RESULT_EXTENSIONS = (".csv",)
LOG_EXTENSIONS = (".log", ".txt")


class UploadRejected(ValueError):
    """The upload was refused before any byte reached storage."""


#: Statuses from which a comparison is meaningful. INCOMPLETE and
#: HASH_MISMATCH are deliberately absent: one has missing fields, the other is
#: evidence about a different question.
_COMPARABLE = frozenset(
    {SASValidationRunStatus.PARSED, SASValidationRunStatus.REVIEW_REQUIRED}
)


class DeterministicEvidenceNotReady(RuntimeError):
    """The assistant was asked to analyse a run whose facts do not exist yet."""


def require_deterministic_evidence(run: Mapping[str, Any]) -> None:
    """The deterministic layer owns the facts, and it goes first.

    ORDER, NOT POLITENESS

    Parsing, hashing, numerical extraction, provenance and comparison are
    deterministic code's job, and the assistant's input is their OUTPUT. A run
    that failed its hash check, or that SAS left incomplete, has no assembled
    facts - only raw files and an explanation.

    Handing that to a model produces a confident paragraph about nothing, and
    a reviewer skimming Section B would read it as analysis. So this refuses,
    and the refusal names the state rather than failing vaguely.
    """
    comparison = run.get("comparison") or {}
    status = str(run.get("status") or "unknown")

    if not comparison:
        raise DeterministicEvidenceNotReady(
            f"This run is {status.replace('_', ' ')} and has no comparison "
            "report. The deterministic checks - parsing, provenance and "
            "comparison - produce the facts the assistant reads, so there is "
            "nothing for it to analyse yet."
        )

    if not comparison.get("integrity"):
        raise DeterministicEvidenceNotReady(
            "This run has a comparison but no recorded integrity statuses. "
            "The assistant must not be asked to infer provenance."
        )


def build_preconditions(
    *, run: Mapping[str, Any], acknowledged: bool
) -> AcceptancePreconditions:
    """Read the deterministic evidence into the acceptance gate.

    Everything here comes from stored facts, never from an opinion: the
    integrity states the comparison recorded, whether SAS reported each field,
    and whether the fit converged.
    """
    comparison = run.get("comparison") or {}
    integrity = comparison.get("integrity") or {}

    return AcceptancePreconditions(
        package_integrity=PackageIntegrity(
            integrity.get("package_integrity", PackageIntegrity.ABSENT.value)
        ),
        dataset_provenance=DatasetProvenance(
            integrity.get("dataset_provenance", DatasetProvenance.MISSING.value)
        ),
        case_stamp=DatasetProvenance(
            integrity.get("validation_case_stamp", DatasetProvenance.MISSING.value)
        ),
        program_execution=ProgramExecutionIntegrity(
            integrity.get(
                "program_execution_integrity",
                ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION.value,
            )
        ),
        result_complete=run.get("estimate_log") is not None,
        sas_version_present=bool(run.get("sas_version")),
        denominator_df_present=run.get("denominator_df") is not None,
        confidence_interval_present=(
            run.get("ci_lower_ratio") is not None
            and run.get("ci_upper_ratio") is not None
        ),
        # Only an explicit failure blocks. An unreported status is "not known",
        # which the reviewer can weigh; treating it as failure would refuse
        # runs SAS simply did not comment on.
        convergence_failed=(
            run.get("convergence_status") is not None
            and str(run["convergence_status"]).strip() != "0"
        ),
        comparison_available=bool(comparison),
        acknowledged=acknowledged,
    )


def build_ai_evidence(
    *, run: Mapping[str, Any], package: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble the FACTS the assistant is shown.

    Reference values carry their evidence status inline rather than in a
    legend, because a model - like a reader - attaches whatever label sits
    nearest the number. `19.8906` unlabelled would be read as authoritative.
    """
    comparison = run.get("comparison") or {}
    integrity = comparison.get("integrity") or {}

    return {
        "validation_case": run.get("case_id"),
        "package_id": package.get("id"),
        "integrity": {
            "package_archive": integrity.get("package_integrity"),
            "dataset_provenance_stamp": integrity.get("dataset_provenance"),
            "validation_case_stamp": integrity.get("validation_case_stamp"),
            "program_execution": integrity.get("program_execution_integrity"),
            "program_execution_meaning": integrity.get("qualification"),
        },
        "sas_reported": {
            "sas_version": run.get("sas_version"),
            "estimate_percent": run.get("estimate_ratio"),
            "standard_error": run.get("standard_error"),
            "denominator_df": run.get("denominator_df"),
            "ci_lower_percent": run.get("ci_lower_ratio"),
            "ci_upper_percent": run.get("ci_upper_ratio"),
            "convergence_status": run.get("convergence_status"),
        },
        "log_signals": run.get("warnings") or [],
        "reference_values": [
            f"{reference['quantity']} = {reference['value']} "
            f"[{str(reference['evidence_status']).upper()}] "
            f"source: {reference['source']}"
            for reference in comparison.get("reference_context", [])
        ],
        "method_validation_status": (
            "FDA_REPLICATE_STANDARD_ABE_PARTIAL is NOT_IMPLEMENTED and "
            "partial_oracle_ready is false. The engine does not compute this "
            "case, so there is no in-house number to compare against."
        ),
        "known_limitations": [
            "SAS executed in a customer-controlled environment; the exact "
            "program bytes cannot be cryptographically verified.",
            "EMA published no standard error and no denominator df for this "
            "dataset, which is why the df is the open question.",
        ],
    }


def _manual_integrity(
    parsed: ParsedSASResult, package_row: Mapping[str, Any]
) -> EvidenceIntegrity:
    """What we actually checked, for a customer-run upload.

    PACKAGE INTEGRITY is ours: we hashed the archive when we built it and
    stored both. It is VERIFIED whenever the row has an archive hash, and that
    conclusion depends on nothing the customer did.

    DATASET PROVENANCE and the CASE STAMP come from values the generated
    program wrote into its own output. Self-reported, checked against the
    package we own - which catches the realistic failure of a result uploaded
    against the wrong package, and is not attestation.

    PROGRAM EXECUTION INTEGRITY is not a parameter. `manual_execution_integrity`
    fixes it at UNVERIFIED_MANUAL_EXECUTION so this function cannot claim
    otherwise even by mistake.
    """
    package = (
        PackageIntegrity.VERIFIED
        if package_row.get("archive_sha256")
        else PackageIntegrity.ABSENT
    )

    if not parsed.emitted_dataset_sha256:
        dataset = DatasetProvenance.MISSING
    elif parsed.emitted_dataset_sha256 == str(package_row["dataset_sha256"]):
        dataset = DatasetProvenance.MATCH
    else:
        dataset = DatasetProvenance.MISMATCH

    if not parsed.emitted_case_id:
        case_stamp = DatasetProvenance.MISSING
    elif parsed.emitted_case_id == str(package_row["case_id"]):
        case_stamp = DatasetProvenance.MATCH
    else:
        case_stamp = DatasetProvenance.MISMATCH

    return manual_execution_integrity(
        package=package, dataset_provenance=dataset, case_stamp=case_stamp
    )


def _verify_and_parse(text: str, package_row: Mapping[str, Any]) -> IngestOutcome:
    """Parse, then check the result identifies THIS package, then report.

    THE ORDER HERE IS NOT THE ORDER IN `ingest_upload`, AND THAT IS DELIBERATE.

    `ingest_upload` checks declared hashes before parsing, which is right when
    the hashes arrive alongside the file. In this workflow they arrive INSIDE
    it: the generated program stamps the dataset hash and case id into its own
    output, so the evidence identifies its own package and nothing has to be
    taken on the uploader's word.

    That inverts the order. The stamps cannot be read without parsing, so:

        cannot parse at all         -> INCOMPLETE, and say so. Reporting
                                       HASH_MISMATCH for a SAS log would blame
                                       the wrong thing.
        parses, carries no stamps   -> HASH_MISMATCH. Either it came from a
                                       package generated before stamping, or it
                                       was not produced by our program.
        parses, stamps disagree     -> HASH_MISMATCH. It is a real result about
                                       a different dataset.
        parses, stamps agree        -> continue to completeness and convergence.

    An earlier version of this function passed the package row's own hashes as
    both the declared and the expected value, which made the check a tautology
    that could never fail. A test that corrupted the stored package and still
    got a pass is what found it.
    """
    try:
        parsed = parse_result_csv(text)
    except ResultParseError as error:
        return IngestOutcome(
            SASValidationRunStatus.INCOMPLETE, None, f"could not parse: {error}"
        )

    expected_dataset = str(package_row["dataset_sha256"])
    expected_case = str(package_row["case_id"])

    if not parsed.emitted_dataset_sha256:
        return IngestOutcome(
            SASValidationRunStatus.HASH_MISMATCH,
            parsed,
            "the result does not identify the package that produced it. The "
            "program supplied with this package stamps its dataset hash into "
            "the output; a result without one was not produced by it.",
        )

    if parsed.emitted_dataset_sha256 != expected_dataset:
        return IngestOutcome(
            SASValidationRunStatus.HASH_MISMATCH,
            parsed,
            "this output was produced from a different dataset: it reports "
            f"{parsed.emitted_dataset_sha256[:16]}..., and this package's data "
            f"is {expected_dataset[:16]}...",
        )

    if parsed.emitted_case_id and parsed.emitted_case_id != expected_case:
        return IngestOutcome(
            SASValidationRunStatus.HASH_MISMATCH,
            parsed,
            f"this output is for validation case {parsed.emitted_case_id}, not "
            f"{expected_case}",
        )

    if not parsed.is_complete:
        missing = [
            name
            for name, value in (
                ("estimate", parsed.estimate_log),
                ("standard error", parsed.standard_error),
                ("denominator df", parsed.denominator_df),
                ("lower limit", parsed.ci_lower_log),
                ("upper limit", parsed.ci_upper_log),
            )
            if value is None
        ]
        return IngestOutcome(
            SASValidationRunStatus.INCOMPLETE,
            parsed,
            "SAS did not report: " + ", ".join(missing),
        )

    if parsed.converged is False:
        return IngestOutcome(
            SASValidationRunStatus.REVIEW_REQUIRED,
            parsed,
            "SAS reported a non-converged fit "
            f"({parsed.convergence_reason or 'no reason given'}). The numbers "
            "are retained as evidence but must not be compared as if the model "
            "had fitted.",
        )

    return IngestOutcome(
        SASValidationRunStatus.PARSED, parsed, "parsed and ready for comparison"
    )


@dataclass(frozen=True, slots=True)
class GeneratedPackage:
    package: ValidationPackage
    archive_sha256: str
    archive_bytes: int
    archive_storage_path: str
    filename: str


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    run_id: str
    status: SASValidationRunStatus
    detail: str
    comparison: ComparisonReport | None
    artifact_sha256: str
    artifact_created: bool


def _reject_unless(condition: bool, message: str) -> None:
    if not condition:
        raise UploadRejected(message)


def check_upload(
    *,
    filename: str,
    content_type: str | None,
    payload: bytes,
    kind: str,
) -> None:
    """Size and type gates, applied before storage.

    Rejecting after storing would leave refused bytes in the bucket for every
    mistyped upload. Rejecting before means an oversized or wrong-typed file
    never becomes an object at all.
    """
    limits = {
        "result_file": (MAX_RESULT_BYTES, RESULT_CONTENT_TYPES, RESULT_EXTENSIONS),
        "sas_log": (MAX_LOG_BYTES, LOG_CONTENT_TYPES, LOG_EXTENSIONS),
    }
    max_bytes, types, extensions = limits[kind]

    _reject_unless(len(payload) > 0, "the uploaded file is empty")
    _reject_unless(
        len(payload) <= max_bytes,
        f"the file is {len(payload)} bytes; the limit for this kind of "
        f"evidence is {max_bytes}",
    )

    lowered = filename.lower()
    _reject_unless(
        lowered.endswith(extensions),
        f"expected a file ending in {' or '.join(extensions)}, got {filename!r}",
    )
    # A path separator in a filename is either a mistake or an attempt; either
    # way the name is only ever used as a label, never as a path.
    _reject_unless(
        "/" not in filename and "\\" not in filename and ".." not in filename,
        "the filename must not contain a path",
    )
    if content_type:
        base = content_type.split(";", 1)[0].strip().lower()
        _reject_unless(
            base in types,
            f"content type {base!r} is not accepted for this evidence; "
            f"expected one of {', '.join(types)}",
        )

    # Uploads are untrusted bytes and are never executed - but a file that is
    # not text at all cannot be the structured result or a SAS log, and saying
    # so early is clearer than a parse error later.
    _reject_unless(
        b"\x00" not in payload[:4096],
        "this looks like a binary file. The supported evidence is the "
        "structured result file written by validate.sas, and the SAS log.",
    )


class ManualValidationWorkflow:
    def __init__(
        self,
        *,
        repository: SASValidationRepository,
        storage: SASValidationStorage,
        be_stats_version: str,
        git_sha: str,
        ai_reviewer: SASValidationAIReviewer | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._be_stats_version = be_stats_version
        self._git_sha = git_sha
        # No provider configured is a SUPPORTED STATE, not a failure. The
        # assistant is advisory, so its absence must not block a human review -
        # a reviewer with no AI analysis is exactly a reviewer working from
        # deterministic evidence, which is the authoritative evidence anyway.
        self._ai_reviewer = ai_reviewer or SASValidationAIReviewer(provider=None)

    # ------------------------------------------------------- generation ---

    async def generate(
        self, *, tenant_id: str, actor: str, case_id: str
    ) -> GeneratedPackage:
        """Build, archive, store, record. The dataset comes from the server.

        The caller supplies a case id and nothing else - no observations, no
        SAS, no expected answer, no package hash. A browser cannot submit a
        modified version of the regulatory dataset for a predefined oracle
        case, because there is no parameter through which to try.
        """
        target = get_target(case_id)
        observations = load_canonical_observations(case_id)

        package = build_package(
            target=target,
            observations=observations,
            be_stats_version=self._be_stats_version,
            git_sha=self._git_sha,
        )
        archive = build_archive(package)
        filename = archive_filename(package)
        path = f"{tenant_id}/packages/{package.package_id}/{filename}"

        # Storage first, database second. An orphaned object is litter; a row
        # pointing at an object that does not exist is a package that cannot be
        # downloaded, and 0033 refuses that state anyway.
        archive_sha256 = await self._storage.upload(
            path, archive, content_type="application/zip"
        )
        await self._repository.insert_package(
            tenant_id=tenant_id,
            actor=actor,
            package=package,
            archive_storage_path=path,
            archive_sha256=archive_sha256,
            archive_bytes=len(archive),
        )
        return GeneratedPackage(
            package=package,
            archive_sha256=archive_sha256,
            archive_bytes=len(archive),
            archive_storage_path=path,
            filename=filename,
        )

    async def download_url(
        self, *, tenant_id: str, actor: str, package_id: str
    ) -> tuple[str, dict]:
        """A short-lived signed link to the EXACT stored bytes.

        Nothing is rebuilt. `build_package` is deterministic, but a be-stats
        version bump would change what it produces - and a package id that is
        supposed to be immutable must not quietly start yielding different
        bytes.
        """
        row = await self._repository.get_package(
            tenant_id=tenant_id, package_id=package_id
        )
        path = row.get("archive_storage_path")
        if not path:
            raise FileNotFoundError(
                f"package {package_id} has no stored archive; it was not "
                "generated completely and cannot be downloaded"
            )

        url = await self._storage.create_signed_download_url(
            path, filename=path.rsplit("/", 1)[-1]
        )
        await self._repository.record_download(
            tenant_id=tenant_id,
            actor=actor,
            package_id=package_id,
            archive_sha256=str(row["archive_sha256"]),
        )
        return url, row

    # ----------------------------------------------------------- uploads ---

    async def upload_result(
        self,
        *,
        tenant_id: str,
        actor: str,
        package_id: str,
        filename: str,
        content_type: str | None,
        payload: bytes,
        evidence_origin: EvidenceOrigin,
        run_id: str | None = None,
    ) -> UploadOutcome:
        """Store, hash, verify, parse, compare - strictly in that order.

        `evidence_origin` HAS NO DEFAULT, deliberately. A fixture CSV and a
        real SAS CSV are the same shape, so nothing here could derive the
        honest answer from the bytes; the caller has to say. A default would
        make the safe answer implicit and the wrong one silent.
        """
        check_upload(
            filename=filename,
            content_type=content_type,
            payload=payload,
            kind="result_file",
        )
        package_row = await self._repository.get_package(
            tenant_id=tenant_id, package_id=package_id
        )
        identifier = run_id or str(uuid.uuid4())

        artifact_sha256, storage_path = await self._store_artifact(
            tenant_id=tenant_id,
            run_id=identifier,
            kind="result_file",
            filename=filename,
            payload=payload,
            content_type="text/csv",
        )
        _, created = await self._repository.insert_artifact(
            tenant_id=tenant_id,
            actor=actor,
            run_id=identifier,
            kind="result_file",
            filename=filename,
            content_sha256=artifact_sha256,
            byte_size=len(payload),
            storage_ref=storage_path,
        )

        text = payload.decode("utf-8", errors="replace")
        outcome = _verify_and_parse(text, package_row)

        run: dict[str, Any] = {
            "id": identifier,
            "tenant_id": tenant_id,
            "package_id": package_id,
            "case_id": str(package_row["case_id"]),
            "sas_mode": SASIntegrationMode.MANUAL_UPLOAD.value,
            "status": outcome.status.value,
            "evidence_origin": EvidenceOrigin(evidence_origin).value,
            "declared_dataset_sha256": str(package_row["dataset_sha256"]),
            "declared_program_sha256": str(package_row["program_sha256"]),
        }

        report: ComparisonReport | None = None
        parsed = outcome.parsed

        if parsed is not None:
            run.update(
                sas_version=parsed.sas_version,
                estimate_log=parsed.estimate_log,
                estimate_ratio=parsed.estimate_ratio_percent,
                standard_error=parsed.standard_error,
                denominator_df=parsed.denominator_df,
                ci_lower_log=parsed.ci_lower_log,
                ci_upper_log=parsed.ci_upper_log,
                ci_lower_ratio=parsed.ci_lower_percent,
                ci_upper_ratio=parsed.ci_upper_percent,
                covariance_parameters=parsed.covariance_parameters,
                convergence_status=parsed.convergence_status,
                warnings=list(parsed.problems),
            )

        # Compare ONLY a result that parsed completely. An INCOMPLETE upload
        # has a `parsed` object with holes in it, and running the comparison
        # over those holes produced REVIEW_REQUIRED where the honest answer was
        # "SAS did not report the fields this needs".
        if outcome.status in _COMPARABLE and parsed:
            report = compare(
                target=get_target(str(package_row["case_id"])),
                package_id=package_id,
                parsed=parsed,
                # The engine declines to compute the partial-replicate case:
                # that capability is NOT_IMPLEMENTED and refuses rather than
                # producing an unvalidated number.
                engine_result=None,
                # Computed from what we actually checked. The earlier version
                # passed `program_hash_matched=True` here, which asserted
                # something the manual workflow cannot establish.
                integrity=_manual_integrity(parsed, package_row),
            )
            run["status"] = report.status.value
            run["comparison"] = _serialise_report(report)

        stored_run_id = await self._repository.upsert_run(
            run=run,
            actor=actor,
            action=(
                ACTION_HASH_MISMATCH
                if outcome.status is SASValidationRunStatus.HASH_MISMATCH
                else (ACTION_COMPARISON_CREATED if report else ACTION_PARSED)
            ),
            reason=outcome.detail,
        )

        return UploadOutcome(
            run_id=stored_run_id,
            status=SASValidationRunStatus(run["status"]),
            detail=outcome.detail,
            comparison=report,
            artifact_sha256=artifact_sha256,
            artifact_created=created,
        )

    async def upload_log(
        self,
        *,
        tenant_id: str,
        actor: str,
        run_id: str,
        filename: str,
        content_type: str | None,
        payload: bytes,
    ) -> UploadOutcome:
        """Archive the log, scan it for signals, never read numbers from it."""
        check_upload(
            filename=filename,
            content_type=content_type,
            payload=payload,
            kind="sas_log",
        )
        run_row = await self._repository.get_run(tenant_id=tenant_id, run_id=run_id)

        artifact_sha256, storage_path = await self._store_artifact(
            tenant_id=tenant_id,
            run_id=run_id,
            kind="sas_log",
            filename=filename,
            payload=payload,
            content_type="text/plain",
        )
        _, created = await self._repository.insert_artifact(
            tenant_id=tenant_id,
            actor=actor,
            run_id=run_id,
            kind="sas_log",
            filename=filename,
            content_sha256=artifact_sha256,
            byte_size=len(payload),
            storage_ref=storage_path,
        )

        scan = scan_log(payload.decode("utf-8", errors="replace"))
        converged = (
            None
            if run_row.get("convergence_status") is None
            else str(run_row["convergence_status"]).strip() == "0"
        )

        status = SASValidationRunStatus(str(run_row["status"]))
        detail = "log archived"

        if contradicts_convergence(scan, converged=converged):
            status = SASValidationRunStatus.REVIEW_REQUIRED
            detail = (
                "The structured result reports a converged fit, but the SAS log "
                "contains ERROR lines. That contradiction is for a reviewer: it "
                "is not enough on its own to accept or reject the run."
            )
            run = dict(run_row)
            run["status"] = status.value
            run["warnings"] = list(scan.error_lines)
            run["tenant_id"] = tenant_id
            run["sas_mode"] = str(run_row["sas_mode"])
            await self._repository.upsert_run(
                run={**run, "id": run_id},
                actor=actor,
                action=ACTION_PARSED,
                reason=detail,
            )

        return UploadOutcome(
            run_id=run_id,
            status=status,
            detail=detail,
            comparison=None,
            artifact_sha256=artifact_sha256,
            artifact_created=created,
        )

    async def record_attestation(
        self,
        *,
        tenant_id: str,
        actor: str,
        run_id: str,
        operator_name: str,
        operator_organization: str,
        confirmed: bool,
        operator_email: str | None = None,
        sas_version: str | None = None,
        operating_environment: str | None = None,
        executed_at: Any = None,
    ) -> OperatorAttestation:
        """Store what the operator declares about one execution.

        `actor` is the SUBMITTER - whoever is signed in here - and is recorded
        separately from the declared operator. An account manager entering a
        client's details is the ordinary case, and merging the two would
        attribute the claim to the wrong person.

        This adds provenance and changes no integrity state. The run's
        `program_execution_integrity` was, is and remains
        UNVERIFIED_MANUAL_EXECUTION.
        """
        run = await self._repository.get_run(tenant_id=tenant_id, run_id=run_id)
        package = await self._repository.get_package(
            tenant_id=tenant_id, package_id=str(run["package_id"])
        )

        attestation = build_attestation(
            package_id=str(package["id"]),
            # From the STORED package, never from the request. An operator who
            # could supply the archive hash could attest to a package other
            # than the one we generated.
            archive_sha256=str(package["archive_sha256"]),
            operator_name=operator_name,
            operator_organization=operator_organization,
            confirmed=confirmed,
            operator_email=operator_email,
            sas_version=sas_version,
            operating_environment=operating_environment,
            executed_at=executed_at,
            submitted_by=actor,
        )
        await self._repository.insert_attestation(
            tenant_id=tenant_id,
            run_id=run_id,
            attestation=attestation,
            actor=actor,
        )
        return attestation

    async def generate_ai_review(
        self, *, tenant_id: str, actor: str, run_id: str
    ) -> dict[str, Any]:
        """Run the assistant over this run's evidence and store the analysis.

        THE ASSISTANT RUNS LAST, AND ONLY ON ASSEMBLED FACTS.

        `require_deterministic_evidence` below refuses to proceed until the
        result has been parsed, provenance evaluated and the comparison built.
        Without that guard the model would be handed a dict of nulls for a
        run that failed its hash check, and would interpret the absence of
        evidence as evidence - the one failure mode a language model reliably
        has here.

        Appends a new version rather than replacing any earlier one: model
        output is non-deterministic, so a re-run is a genuinely different
        artefact and overwriting would destroy what a reviewer already read.
        """
        run = await self._repository.get_run(tenant_id=tenant_id, run_id=run_id)
        require_deterministic_evidence(run)
        package = await self._repository.get_package(
            tenant_id=tenant_id, package_id=str(run["package_id"])
        )
        evidence = build_ai_evidence(run=run, package=package)

        outcome = await self._ai_reviewer.review(evidence)
        review_id = await self._repository.insert_ai_review(
            tenant_id=tenant_id, run_id=run_id, requested_by=actor,
            outcome=outcome,
        )
        return {
            "ai_review_id": review_id,
            "succeeded": outcome.succeeded,
            "recommendation": (
                outcome.recommendation.value if outcome.recommendation else None
            ),
            "response": (
                outcome.response.model_dump(mode="json")
                if outcome.response else None
            ),
            "failure_reason": outcome.failure_reason,
        }

    async def review_context(
        self, *, tenant_id: str, run_id: str
    ) -> dict[str, Any]:
        """Everything the review screen renders, decided server-side.

        The three sections a reviewer sees are three different KINDS of thing,
        and the API keeps them apart so the interface cannot blend them:

            deterministic   what the system checked. Authoritative.
            ai_review       what an assistant thinks. Advisory, and absent
                            whenever no analysis has been requested or the
                            provider was unavailable.
            preconditions   what would block an acceptance right now.

        Preconditions are returned BEFORE a decision is attempted rather than
        only as a 422 afterwards, so a reviewer sees what is missing while they
        can still fix it instead of discovering it on submit.
        """
        run = await self._repository.get_run(tenant_id=tenant_id, run_id=run_id)
        package = await self._repository.get_package(
            tenant_id=tenant_id, package_id=str(run["package_id"])
        )
        ai_review = await self._repository.latest_ai_review(
            tenant_id=tenant_id, run_id=run_id
        )
        reviews = await self._repository.list_human_reviews(
            tenant_id=tenant_id, run_id=run_id
        )
        attestations = await self._repository.list_attestations(
            tenant_id=tenant_id, run_id=run_id
        )

        # `acknowledged=True` here asks "what BESIDES the acknowledgement is
        # unmet", because the acknowledgement is a checkbox the reviewer has
        # not reached yet. Listing it as a failure before they see the form
        # would read as a fault in the evidence.
        preconditions = build_preconditions(run=run, acknowledged=True)

        report = build_evidence_report(
            run={**run, "id": run_id},
            package=package,
            attestations=attestations,
            human_reviews=reviews,
        )

        return {
            "run_id": run_id,
            "status": run.get("status"),
            # The seven labelled sections, assembled once. The screen renders
            # from this rather than deciding for itself which numbers are
            # authoritative.
            "evidence_report": report.as_dict(),
            "evidence_origin": report.evidence_origin.value,
            "is_regulatory_evidence": report.is_regulatory_evidence,
            "deterministic": {
                "comparison": run.get("comparison"),
                "sas_version": run.get("sas_version"),
                "convergence_status": run.get("convergence_status"),
                "warnings": run.get("warnings") or [],
            },
            "ai_review": ai_review,
            "preconditions": {
                "acceptable": preconditions.acceptable,
                "blocking": preconditions.failures(),
            },
            "human_reviews": reviews,
        }

    async def record_human_review(
        self,
        *,
        tenant_id: str,
        reviewer: ReviewerIdentity,
        run_id: str,
        decision: OracleClosureDecision,
        notes: str,
        acknowledged: bool,
    ) -> dict[str, Any]:
        """Freeze the evidence, check the preconditions, store the decision."""
        run = await self._repository.get_run(tenant_id=tenant_id, run_id=run_id)
        package = await self._repository.get_package(
            tenant_id=tenant_id, package_id=str(run["package_id"])
        )
        artifacts = await self._repository.list_artifacts(
            tenant_id=tenant_id, run_id=run_id
        )
        ai_review = await self._repository.latest_ai_review(
            tenant_id=tenant_id, run_id=run_id
        )

        snapshot, snapshot_hash = build_evidence_snapshot(
            run=run,
            package=package,
            artifacts=artifacts,
            ai_review_id=str(ai_review["id"]) if ai_review else None,
            ai_review_hash=(
                str(ai_review.get("response_hash")) if ai_review else None
            ),
        )

        record = prepare_review(
            reviewer=reviewer,
            run_id=run_id,
            tenant_id=tenant_id,
            decision=decision,
            notes=notes,
            acknowledged=acknowledged,
            preconditions=build_preconditions(run=run, acknowledged=acknowledged),
            evidence_snapshot=snapshot,
            evidence_snapshot_hash=snapshot_hash,
            ai_review_id=str(ai_review["id"]) if ai_review else None,
            ai_recommendation=(
                AIRecommendation(ai_review["recommendation"])
                if ai_review and ai_review.get("recommendation")
                else None
            ),
        )
        review_id = await self._repository.insert_human_review(record=record)
        return {
            "review_id": review_id,
            "decision": record.decision.value,
            "evidence_snapshot_hash": record.evidence_snapshot_hash,
        }

    async def record_blocked_review(
        self, *, tenant_id: str, actor: str, run_id: str
    ) -> None:
        """Audit an attempt to record an oracle closure, before refusing it.

        "Who tried to accept an oracle closure" is a question worth being able
        to answer, and it is only answerable if the attempt is recorded rather
        than only the refusal being returned.

        The refusal is now about the CALLER, not the deployment: migration 0034
        gives the backend a working global-role check, so an unauthorised
        attempt means a signed-in user genuinely lacks the role.
        """
        await self._repository.record_event(
            actor=actor,
            action=ACTION_REVIEW_BLOCKED,
            entity_type=ENTITY_RUN,
            entity_id=run_id,
            detail={"tenant_id": tenant_id},
            reason=(
                "the authenticated user holds none of the reviewer roles "
                f"({', '.join(REVIEWER_ROLE_KEYS)})"
            ),
        )

    # ------------------------------------------------------------ helpers ---

    async def _store_artifact(
        self,
        *,
        tenant_id: str,
        run_id: str,
        kind: str,
        filename: str,
        payload: bytes,
        content_type: str,
    ) -> tuple[str, str]:
        """Store first, hash from what we stored.

        The object key is composed entirely of values this application
        generated - tenant, run, kind and a hash - never the uploader's
        filename, which is kept only as a label.
        """
        content_sha256 = sha256_bytes(payload)

        # CONTENT-ADDRESSED, so re-uploading identical bytes is idempotent.
        #
        # The first version put a timestamp in the key. Identical bytes then
        # landed at two different paths a second apart - and collided outright
        # within the same second, because storage refuses to overwrite
        # evidence. Both are wrong: the same bytes for the same run are the
        # same artifact and should resolve to the same object.
        path = f"{tenant_id}/runs/{run_id}/{kind}/{content_sha256}"

        try:
            return await self._storage.upload(
                path, payload, content_type=content_type
            ), path
        except StorageError:
            # Already there. For a content-addressed key that can only mean
            # these exact bytes were stored before, so the upload has already
            # succeeded and the artifact row will be deduplicated too.
            if await self._storage.exists(path):
                return content_sha256, path
            raise


def _serialise_report(report: ComparisonReport) -> dict[str, Any]:
    """The comparison, as a jsonb payload a reviewer's UI can render."""
    return {
        "case_id": report.case_id,
        "package_id": report.package_id,
        "status": report.status.value,
        "sas_version": report.sas_version,
        "convergence_status": report.convergence_status,
        # The three integrity answers, stored separately so a reviewer reading
        # a persisted run months later sees the same qualification the report
        # showed at the time.
        "integrity": report.integrity.as_dict(),
        "quantities": [
            {
                "quantity": q.quantity,
                "sas_value": q.sas_value,
                "engine_value": q.engine_value,
                "agreement": q.agreement.value,
                "relative_difference": q.relative_difference,
                "tolerance": q.tolerance,
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


__all__ = [
    "LOG_CONTENT_TYPES",
    "RESULT_CONTENT_TYPES",
    "GeneratedPackage",
    "ManualValidationWorkflow",
    "UploadOutcome",
    "UploadRejected",
    "check_upload",
]
