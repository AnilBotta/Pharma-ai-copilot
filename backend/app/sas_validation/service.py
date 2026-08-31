"""Tenant-scoped operations over packages, runs and evidence.

PREPARED FOR TENANT ISOLATION; THIS DEPLOYMENT IS SINGLE-ORGANISATION.

Say that precisely, because the two are different claims. What exists here is a
tenant-scoped DATA MODEL and a set of isolation INVARIANTS enforced by this
layer and exercised by its tests. What does not exist is runtime
multi-tenancy: there is no identity-to-organisation mapping anywhere in the
system, and `routes.resolve_tenant` returns one constant.

So these checks are real code with real tests, and they are not yet protecting
one live customer from another, because there is only one.

EVERY READ AND WRITE TAKES A TENANT, AND CHECKS IT

Not "the caller usually passes the right one" - the check happens here, on the
way out of the store, because that is the only place it cannot be forgotten. A
repository method that returned a package without knowing who asked would be
one call site away from returning another organisation's SAS configuration.

Writing the invariants now is cheap; retrofitting them onto populated tables is
not. `sas_integrations` will hold customer credentials and
`sas_validation_runs` will hold their regulatory evidence, and those are the
two tables where a missing predicate is not a bug report but an incident.

When multi-tenancy arrives, the tenant must be derived from the authenticated
server-side identity - never from a client-supplied value. No method here
accepts one from a request, and none should.

WHAT THIS LAYER WILL NOT DO

It will not change a validation status, and it has no method that could. The
furthest it goes is recording a reviewer's explicit decision on a run - which
is a fact about the review, not about the method.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from app.sas_validation.compare import ComparisonReport, compare
from app.sas_validation.config import SASIntegration
from app.sas_validation.ingest import ingest_upload
from app.sas_validation.modes import (
    OracleClosureDecision,
    SASCapability,
    SASIntegrationMode,
    SASValidationRunStatus,
    is_enabled,
)
from app.sas_validation.package import ValidationPackage, build_package, sha256_text
from app.sas_validation.targets import get_target


class TenantIsolationError(PermissionError):
    """A tenant asked for something belonging to another tenant.

    Raised rather than returning None, and never downgraded to "not found":
    the two are different failures and conflating them makes the isolation
    breach the quieter of the two in a log.
    """


class SASValidationDisabled(RuntimeError):
    """The capability behind this operation is switched off."""


@dataclass(frozen=True, slots=True)
class ValidationRun:
    run_id: str
    tenant_id: str
    package_id: str
    case_id: str
    sas_mode: SASIntegrationMode
    status: SASValidationRunStatus
    uploaded_at: str
    uploaded_by: str
    sas_version: str | None = None
    comparison: ComparisonReport | None = None
    review_status: OracleClosureDecision = OracleClosureDecision.NOT_ASSESSED
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_notes: str = ""
    artifact_hashes: tuple[str, ...] = ()


class SASValidationStore(Protocol):
    """Persistence, kept behind a protocol so the rules above are testable.

    The store is deliberately dumb: it returns what it holds and knows nothing
    about tenants. Every isolation decision is made in this module, where a
    test can reach it without a database.
    """

    def put_package(self, package: ValidationPackage, tenant_id: str) -> None: ...
    def get_package(self, package_id: str) -> tuple[ValidationPackage, str] | None: ...
    def put_run(self, run: ValidationRun) -> None: ...
    def get_run(self, run_id: str) -> ValidationRun | None: ...
    def list_runs(self, tenant_id: str) -> Sequence[ValidationRun]: ...
    def get_integration(self, tenant_id: str) -> SASIntegration | None: ...
    def put_artifact(
        self, run_id: str, tenant_id: str, kind: str, filename: str, content: str
    ) -> str: ...


class SASValidationService:
    def __init__(self, store: SASValidationStore) -> None:
        self._store = store

    # ------------------------------------------------------- packages ---

    def generate_package(
        self,
        *,
        tenant_id: str,
        actor_user_id: str,
        case_id: str,
        observations: Sequence[Mapping[str, object]],
        be_stats_version: str,
        git_sha: str,
    ) -> ValidationPackage:
        if not is_enabled(SASCapability.MANUAL_PACKAGE_GENERATION):
            raise SASValidationDisabled(
                "Validation package generation is not enabled."
            )

        package = build_package(
            target=get_target(case_id),
            observations=observations,
            be_stats_version=be_stats_version,
            git_sha=git_sha,
        )
        self._store.put_package(package, tenant_id)
        return package

    def get_package(self, *, tenant_id: str, package_id: str) -> ValidationPackage:
        found = self._store.get_package(package_id)
        if found is None:
            raise KeyError(f"no validation package {package_id}")
        package, owner = found
        if owner != tenant_id:
            raise TenantIsolationError(
                "this validation package belongs to another organisation"
            )
        return package

    # ------------------------------------------------------- evidence ---

    def record_upload(
        self,
        *,
        tenant_id: str,
        actor_user_id: str,
        package_id: str,
        result_content: str,
        declared_dataset_sha256: str,
        declared_program_sha256: str,
        sas_log: str | None = None,
        engine_result: dict[str, float | None] | None = None,
        run_id: str | None = None,
    ) -> ValidationRun:
        """Store the raw file, then parse it, then compare - in that order.

        The artifact is written FIRST and unconditionally, including when the
        hashes turn out not to match. A rejected upload is still evidence about
        what a customer ran, and discarding it would destroy the only record of
        a discrepancy at the moment it is most interesting.
        """
        if not is_enabled(SASCapability.MANUAL_RESULT_UPLOAD):
            raise SASValidationDisabled("Result upload is not enabled.")

        package = self.get_package(tenant_id=tenant_id, package_id=package_id)
        identifier = run_id or sha256_text(
            f"{package_id}:{actor_user_id}:{datetime.now(UTC).isoformat()}"
        )[:32]

        hashes = [
            self._store.put_artifact(
                identifier, tenant_id, "result_file", "be_result.csv", result_content
            )
        ]
        if sas_log is not None:
            hashes.append(
                self._store.put_artifact(
                    identifier, tenant_id, "sas_log", "sas.log", sas_log
                )
            )

        manifest = package.manifest
        outcome = ingest_upload(
            content=result_content,
            declared_dataset_sha256=declared_dataset_sha256,
            declared_program_sha256=declared_program_sha256,
            package_dataset_sha256=str(manifest["dataset_sha256"]),
            package_program_sha256=str(manifest["program_sha256"]),
        )

        report: ComparisonReport | None = None
        status = outcome.status
        sas_version = outcome.parsed.sas_version if outcome.parsed else None

        if outcome.parsed is not None and outcome.status in (
            SASValidationRunStatus.PARSED,
            SASValidationRunStatus.REVIEW_REQUIRED,
        ):
            report = compare(
                target=get_target(package.case_id),
                package_id=package.package_id,
                parsed=outcome.parsed,
                engine_result=engine_result,
                dataset_hash_matched=True,
                program_hash_matched=True,
            )
            status = report.status

        run = ValidationRun(
            run_id=identifier,
            tenant_id=tenant_id,
            package_id=package_id,
            case_id=package.case_id,
            sas_mode=SASIntegrationMode.MANUAL_UPLOAD,
            status=status,
            uploaded_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            uploaded_by=actor_user_id,
            sas_version=sas_version,
            comparison=report,
            artifact_hashes=tuple(hashes),
        )
        self._store.put_run(run)
        return run

    def get_run(self, *, tenant_id: str, run_id: str) -> ValidationRun:
        run = self._store.get_run(run_id)
        if run is None:
            raise KeyError(f"no validation run {run_id}")
        if run.tenant_id != tenant_id:
            raise TenantIsolationError(
                "this validation run belongs to another organisation"
            )
        return run

    def list_runs(self, *, tenant_id: str) -> Sequence[ValidationRun]:
        runs = self._store.list_runs(tenant_id)
        # Defence in depth: the store filters, and we verify. A store bug
        # should not become a disclosure.
        leaked = [r.run_id for r in runs if r.tenant_id != tenant_id]
        if leaked:
            raise TenantIsolationError(
                f"the store returned runs belonging to another organisation: {leaked}"
            )
        return runs

    # --------------------------------------------------------- review ---

    def record_review(
        self,
        *,
        tenant_id: str,
        reviewer_user_id: str,
        run_id: str,
        decision: OracleClosureDecision,
        notes: str,
    ) -> ValidationRun:
        """Record what a reviewer decided. Nothing more happens.

        In particular no method's validation status changes here, and there is
        no parameter through which one could. Acting on an accepted closure is
        a separate, governed statistical change.
        """
        if decision is OracleClosureDecision.NOT_ASSESSED:
            raise ValueError(
                "a review must record a decision; leaving it unassessed is what "
                "not reviewing already means"
            )
        if not notes.strip():
            raise ValueError(
                "a review decision needs a reason. An accepted oracle closure "
                "with no recorded rationale is not reviewable evidence."
            )

        run = self.get_run(tenant_id=tenant_id, run_id=run_id)
        reviewed = replace(
            run,
            review_status=decision,
            reviewed_by=reviewer_user_id,
            reviewed_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            review_notes=notes,
            status=(
                SASValidationRunStatus.REVIEWED_ACCEPTED
                if decision is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED
                else SASValidationRunStatus.REVIEWED_REJECTED
            ),
        )
        self._store.put_run(reviewed)
        return reviewed

    # --------------------------------------------------- integration ---

    def get_integration(self, *, tenant_id: str) -> SASIntegration | None:
        integration = self._store.get_integration(tenant_id)
        if integration is not None and integration.tenant_id != tenant_id:
            raise TenantIsolationError(
                "this integration belongs to another organisation"
            )
        return integration


__all__ = [
    "SASValidationDisabled",
    "SASValidationService",
    "SASValidationStore",
    "TenantIsolationError",
    "ValidationRun",
]
