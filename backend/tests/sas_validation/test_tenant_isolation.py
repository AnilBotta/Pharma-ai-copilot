"""Tenant A must never reach tenant B's SAS anything.

WHAT THESE TESTS DO AND DO NOT DEMONSTRATE

They demonstrate that the SERVICE LAYER enforces tenant-scoping invariants.
They do NOT demonstrate runtime multi-tenant isolation, because this deployment
has none: there is no identity-to-organisation mapping and
`routes.resolve_tenant` returns a single constant.

The honest description is "prepared for tenant isolation; current deployment is
single-organisation". Every test below runs against two tenant ids that no real
deployment produces today.

They are still the right tests to write now. `sas_integrations` will hold
customer SAS credentials and `sas_validation_runs` will hold their regulatory
evidence, and those are the two tables where a missing predicate is not a bug
report but an incident. Writing the isolation rules while the tables are empty
is cheap; retrofitting them onto populated ones is the migration nobody wants.

The store used here is deliberately naive - it does no filtering of its own -
so what is being tested is the SERVICE's predicate, not a fixture's.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.sas_validation.config import SASIntegration
from app.sas_validation.modes import OracleClosureDecision, SASIntegrationMode
from app.sas_validation.package import ValidationPackage, sha256_text
from app.sas_validation.service import (
    SASValidationService,
    TenantIsolationError,
    ValidationRun,
)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"

OBSERVATIONS = [
    {"subject": "1", "sequence": "TRR", "period": 1, "treatment": "T", "value": 100.0},
    {"subject": "1", "sequence": "TRR", "period": 2, "treatment": "R", "value": 103.0},
    {"subject": "1", "sequence": "TRR", "period": 3, "treatment": "R", "value": 99.0},
    {"subject": "2", "sequence": "RTR", "period": 1, "treatment": "R", "value": 95.0},
    {"subject": "2", "sequence": "RTR", "period": 2, "treatment": "T", "value": 98.0},
    {"subject": "2", "sequence": "RTR", "period": 3, "treatment": "R", "value": 97.0},
]

CASE = "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"


class NaiveStore:
    """Returns what it holds, filters nothing.

    A store that applied the tenant predicate itself would make these tests
    pass without the service doing anything, which is the wrong thing to prove.
    """

    def __init__(self) -> None:
        self.packages: dict[str, tuple[ValidationPackage, str]] = {}
        self.runs: dict[str, ValidationRun] = {}
        self.integrations: dict[str, SASIntegration] = {}
        self.artifacts: list[tuple[str, str, str, str, str]] = []

    def put_package(self, package: ValidationPackage, tenant_id: str) -> None:
        self.packages[package.package_id] = (package, tenant_id)

    def get_package(self, package_id: str):
        return self.packages.get(package_id)

    def put_run(self, run: ValidationRun) -> None:
        self.runs[run.run_id] = run

    def get_run(self, run_id: str):
        return self.runs.get(run_id)

    def list_runs(self, tenant_id: str) -> Sequence[ValidationRun]:
        # Deliberately ignores tenant_id - see the class docstring.
        return list(self.runs.values())

    def get_integration(self, tenant_id: str):
        return self.integrations.get(tenant_id)

    def put_artifact(self, run_id, tenant_id, kind, filename, content) -> str:
        digest = sha256_text(content)
        self.artifacts.append((run_id, tenant_id, kind, filename, digest))
        return digest


@pytest.fixture
def service() -> SASValidationService:
    return SASValidationService(NaiveStore())


def generate(service: SASValidationService, tenant: str) -> ValidationPackage:
    return service.generate_package(
        tenant_id=tenant,
        actor_user_id="user-1",
        case_id=CASE,
        observations=OBSERVATIONS,
        be_stats_version="0.7.0",
        git_sha="abc1234",
    )


# ------------------------------------------------------------ packages ---


def test_a_tenant_cannot_read_another_tenants_package(service):
    package = generate(service, TENANT_A)
    with pytest.raises(TenantIsolationError):
        service.get_package(tenant_id=TENANT_B, package_id=package.package_id)


def test_the_owning_tenant_can_read_its_own_package(service):
    package = generate(service, TENANT_A)
    assert (
        service.get_package(tenant_id=TENANT_A, package_id=package.package_id).package_id
        == package.package_id
    )


def test_isolation_is_not_reported_as_not_found(service):
    """The two failures are different and must stay different.

    Returning "not found" for a cross-tenant read would make the isolation
    breach the quieter of the two in a log - and the quiet one is the one
    nobody investigates.
    """
    package = generate(service, TENANT_A)
    with pytest.raises(TenantIsolationError):
        service.get_package(tenant_id=TENANT_B, package_id=package.package_id)
    with pytest.raises(KeyError):
        service.get_package(tenant_id=TENANT_A, package_id="0" * 64)


# ---------------------------------------------------------------- runs ---


def test_a_tenant_cannot_upload_against_another_tenants_package(service):
    """The package check happens before anything is stored.

    Otherwise tenant B could write evidence, and an artifact, against tenant
    A's package - and the first anyone would know is a run appearing under the
    wrong organisation.
    """
    package = generate(service, TENANT_A)
    with pytest.raises(TenantIsolationError):
        service.record_upload(
            tenant_id=TENANT_B,
            actor_user_id="user-2",
            package_id=package.package_id,
            result_content="section,name,value\n",
            declared_dataset_sha256=str(package.manifest["dataset_sha256"]),
            declared_program_sha256=str(package.manifest["program_sha256"]),
        )


def test_a_tenant_cannot_read_another_tenants_run(service):
    package = generate(service, TENANT_A)
    run = service.record_upload(
        tenant_id=TENANT_A,
        actor_user_id="user-1",
        package_id=package.package_id,
        result_content="section,name,value\nconvergence,status,0|ok\n",
        declared_dataset_sha256=str(package.manifest["dataset_sha256"]),
        declared_program_sha256=str(package.manifest["program_sha256"]),
    )
    with pytest.raises(TenantIsolationError):
        service.get_run(tenant_id=TENANT_B, run_id=run.run_id)


def test_a_leaking_store_is_caught_rather_than_trusted(service):
    """Defence in depth: the store filters, and the service verifies.

    `NaiveStore.list_runs` ignores its tenant argument, which is exactly the
    bug a real store could one day have. The service must not pass it on.
    """
    package = generate(service, TENANT_A)
    service.record_upload(
        tenant_id=TENANT_A,
        actor_user_id="user-1",
        package_id=package.package_id,
        result_content="section,name,value\nconvergence,status,0|ok\n",
        declared_dataset_sha256=str(package.manifest["dataset_sha256"]),
        declared_program_sha256=str(package.manifest["program_sha256"]),
    )
    with pytest.raises(TenantIsolationError):
        service.list_runs(tenant_id=TENANT_B)


def test_a_tenant_cannot_review_another_tenants_run(service):
    package = generate(service, TENANT_A)
    run = service.record_upload(
        tenant_id=TENANT_A,
        actor_user_id="user-1",
        package_id=package.package_id,
        result_content="section,name,value\nconvergence,status,0|ok\n",
        declared_dataset_sha256=str(package.manifest["dataset_sha256"]),
        declared_program_sha256=str(package.manifest["program_sha256"]),
    )
    with pytest.raises(TenantIsolationError):
        service.record_review(
            tenant_id=TENANT_B,
            reviewer_user_id="user-2",
            run_id=run.run_id,
            decision=OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
            notes="not mine to accept",
        )


def test_integrations_are_tenant_scoped(service):
    store = service._store
    store.integrations[TENANT_A] = SASIntegration(
        integration_id="i-1",
        tenant_id=TENANT_A,
        mode=SASIntegrationMode.MANUAL_UPLOAD,
    )
    assert service.get_integration(tenant_id=TENANT_A) is not None
    assert service.get_integration(tenant_id=TENANT_B) is None

    # And a store that returned the wrong one is caught rather than served.
    store.integrations[TENANT_B] = SASIntegration(
        integration_id="i-1", tenant_id=TENANT_A, mode=SASIntegrationMode.MANUAL_UPLOAD
    )
    with pytest.raises(TenantIsolationError):
        service.get_integration(tenant_id=TENANT_B)


# -------------------------------------------------------------- review ---


def test_a_review_must_carry_a_decision_and_a_reason(service):
    package = generate(service, TENANT_A)
    run = service.record_upload(
        tenant_id=TENANT_A,
        actor_user_id="user-1",
        package_id=package.package_id,
        result_content="section,name,value\nconvergence,status,0|ok\n",
        declared_dataset_sha256=str(package.manifest["dataset_sha256"]),
        declared_program_sha256=str(package.manifest["program_sha256"]),
    )
    with pytest.raises(ValueError, match="needs a reason"):
        service.record_review(
            tenant_id=TENANT_A,
            reviewer_user_id="u",
            run_id=run.run_id,
            decision=OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
            notes="   ",
        )
    with pytest.raises(ValueError, match="must record a decision"):
        service.record_review(
            tenant_id=TENANT_A,
            reviewer_user_id="u",
            run_id=run.run_id,
            decision=OracleClosureDecision.NOT_ASSESSED,
            notes="fine",
        )


def test_the_raw_upload_is_kept_even_when_the_hashes_do_not_match(service):
    """A rejected upload is still evidence about what the customer ran.

    Discarding it would destroy the only record of a discrepancy at the moment
    it is most interesting.
    """
    package = generate(service, TENANT_A)
    run = service.record_upload(
        tenant_id=TENANT_A,
        actor_user_id="user-1",
        package_id=package.package_id,
        result_content="section,name,value\nconvergence,status,0|ok\n",
        declared_dataset_sha256="f" * 64,
        declared_program_sha256="f" * 64,
        sas_log="NOTE: something happened",
    )
    assert run.status.value == "hash_mismatch"
    assert len(run.artifact_hashes) == 2
    assert len(service._store.artifacts) == 2
