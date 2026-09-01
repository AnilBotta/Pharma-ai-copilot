"""OPERATIONAL DRY RUN - NOT SAS VALIDATION EVIDENCE.

WHAT THIS IS

A walk through every step the first real SAS run will take, using a controlled
fixture in place of the SAS output, so that the OPERATIONAL path can be
exercised before a client is asked to spend time in their licensed
environment. It answers "does the machinery work end to end", which is a
different question from "what does SAS say", and only the second one matters
statistically.

WHAT THIS IS NOT

It is not evidence. Every artefact it produces is declared
`evidence_origin = test_fixture`, and the fixture result is a CSV this script
writes - a shape, not a measurement. Its denominator df is deliberately an
implausible round number so that no reader could mistake the output for a real
SAS answer, and so that a value copied out of this script's output could never
be quietly cited later.

    The real question this milestone leaves OPEN is what SAS reports for the
    partial-replicate denominator df on EMA Data Set II. Nothing here answers
    it, and nothing here should be read as suggesting an answer.

WHY IT RUNS AGAINST IN-MEMORY DOUBLES

The SAS validation migrations are not applied in the target deployment (see
`sas_readiness_audit.py`), and applying them is a decision for a person, not a
side effect of a rehearsal. So this exercises the workflow, comparison,
integrity, attestation and report layers directly. The persistence contract has
its own test against the real schema:
`tests/db/test_human_review_persistence.py`.

    python scripts/sas_operational_dry_run.py
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.sas_validation.attestation import EvidenceOrigin, build_attestation
from app.sas_validation.evidence_report import build_evidence_report
from app.sas_validation.integrity import ProgramExecutionIntegrity
from app.sas_validation.repository import (
    ACTION_PACKAGE_DOWNLOADED,
    ACTION_PACKAGE_GENERATED,
    PackageNotFound,
)
from app.sas_validation.workflow import (
    DeterministicEvidenceNotReady,
    ManualValidationWorkflow,
    require_deterministic_evidence,
)

BANNER = "OPERATIONAL DRY RUN - NOT SAS VALIDATION EVIDENCE"
CASE = "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
TENANT = "00000000-0000-0000-0000-000000000001"
ACTOR = "dry-run-operator"

#: Deliberately implausible. A fixture carrying 19.8906 or 22.5403 would be one
#: copy-paste away from being cited as a SAS result for the very question this
#: milestone leaves open.
FIXTURE_DF = "1.0000"


def step(number: int, title: str) -> None:
    print(f"\n  {number:>2}. {title}")


def note(text: str) -> None:
    print(f"      {text}")


# ------------------------------------------------------------ the doubles ---


class MemoryStorage:
    """Matches `SASValidationStorage`'s surface, nothing more."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, path: str, payload: bytes, *, content_type: str) -> str:
        self.objects[path] = payload
        return hashlib.sha256(payload).hexdigest()

    async def exists(self, path: str) -> bool:
        return path in self.objects

    async def download(self, path: str) -> bytes:
        return self.objects[path]

    async def create_signed_download_url(self, path: str, *, filename: str) -> str:
        if path not in self.objects:
            raise FileNotFoundError(path)
        return f"https://storage.invalid/{path}?token=dry-run&name={filename}"


class MemoryRepository:
    def __init__(self) -> None:
        self.packages: dict[tuple[str, str], dict] = {}
        self.runs: dict[tuple[str, str], dict] = {}
        self.artifacts: list[dict] = []
        self.attestations: list[dict] = []
        self.audit: list[tuple[str, str]] = []

    async def insert_package(self, *, tenant_id, actor, package,
                             archive_storage_path, archive_sha256, archive_bytes):
        self.packages[(tenant_id, package.package_id)] = {
            "id": package.package_id,
            "tenant_id": tenant_id,
            "case_id": package.case_id,
            "regulatory_method": "FDA_REPLICATE_STANDARD_ABE_PARTIAL",
            "dataset_sha256": package.manifest["dataset_sha256"],
            "program_sha256": package.manifest["program_sha256"],
            "archive_storage_path": archive_storage_path,
            "archive_sha256": archive_sha256,
            "archive_bytes": archive_bytes,
            "be_stats_version": package.be_stats_version,
            "git_sha": "dry-run",
        }
        self.audit.append((ACTION_PACKAGE_GENERATED, package.package_id))

    async def get_package(self, *, tenant_id, package_id):
        try:
            return self.packages[(tenant_id, package_id)]
        except KeyError:
            raise PackageNotFound(package_id) from None

    async def record_download(self, *, tenant_id, actor, package_id, archive_sha256):
        self.audit.append((ACTION_PACKAGE_DOWNLOADED, package_id))

    async def upsert_run(self, *, run, actor, action, reason=None):
        run_id = run.get("id") or "dry-run-1"
        stored = self.runs.get((run["tenant_id"], run_id), {})
        self.runs[(run["tenant_id"], run_id)] = {
            **stored,
            **run,
            "id": run_id,
            # Mirrors the schema: declared once, never updated.
            "evidence_origin": stored.get("evidence_origin")
            or run.get("evidence_origin"),
        }
        self.audit.append((action, run_id))
        return run_id

    async def get_run(self, *, tenant_id, run_id):
        try:
            return self.runs[(tenant_id, run_id)]
        except KeyError:
            raise PackageNotFound(run_id) from None

    async def insert_artifact(self, *, tenant_id, actor, run_id, kind,
                              filename, content_sha256, byte_size, storage_ref):
        for existing in self.artifacts:
            if (existing["run_id"], existing["kind"], existing["sha"]) == (
                run_id, kind, content_sha256
            ):
                return existing["id"], False
        artifact = {
            "id": f"artifact-{len(self.artifacts) + 1}", "run_id": run_id,
            "kind": kind, "sha": content_sha256, "filename": filename,
            "content_sha256": content_sha256,
        }
        self.artifacts.append(artifact)
        return artifact["id"], True

    async def list_artifacts(self, *, tenant_id, run_id):
        return [a for a in self.artifacts if a["run_id"] == run_id]

    async def insert_attestation(self, *, tenant_id, run_id, attestation, actor):
        row = {**attestation.as_dict(), "run_id": run_id, "id": "attestation-1"}
        self.attestations.append(row)
        return row["id"]

    async def list_attestations(self, *, tenant_id, run_id):
        return [a for a in self.attestations if a["run_id"] == run_id]

    async def latest_ai_review(self, *, tenant_id, run_id):
        return None

    async def list_human_reviews(self, *, tenant_id, run_id):
        return []

    async def insert_ai_review(self, *, tenant_id, run_id, requested_by, outcome):
        return "ai-review-1"

    async def record_event(self, **kwargs):
        self.audit.append((kwargs.get("action", "EVENT"), kwargs.get("entity_id", "")))


def fixture_result(dataset_sha256: str, case_id: str) -> bytes:
    """A CSV in the shape validate.sas writes. NOT a SAS result.

    It stamps the dataset hash and case id the way the real program does, so
    the provenance checks have something real to check - that mechanism is
    exactly what this rehearsal exists to exercise.

    The SAS version reads DRY-RUN-NOT-SAS, and the denominator df is 1.0000, so
    that a line copied out of this output cannot be mistaken for a measurement.
    """
    return (
        "\n".join(
            [
                "section,name,value",
                f"estimate,T vs. R,0.0000|0.0500|{FIXTURE_DF}|-0.1000|0.1000",
                "covparm,FA(1_1) ,0.0000",
                "covparm,Residual TRT R,0.0000",
                "convergence,status,0|DRY RUN FIXTURE - not a SAS message.",
                "environment,sas_version,DRY-RUN-NOT-SAS",
                f"environment,case_id,{case_id}",
                f"environment,dataset_sha256,{dataset_sha256}",
            ]
        )
        + "\n"
    ).encode("utf-8")


async def main() -> int:
    print("=" * 72)
    print(BANNER)
    print("=" * 72)
    print(
        "\n  Exercises the operational path with a controlled fixture. Nothing\n"
        "  below is a SAS result, and no value in it may be cited as one."
    )

    repository = MemoryRepository()
    storage = MemoryStorage()
    workflow = ManualValidationWorkflow(
        repository=repository,
        storage=storage,
        be_stats_version="dry-run",
        git_sha="dry-run",
    )

    # A. package generation ---------------------------------------------------
    step(1, "Generate the approved validation package")
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)
    package_id = generated.package.package_id
    note(f"case            {CASE}")
    note(f"package_id      {package_id[:32]}...")
    note(f"archive_sha256  {generated.archive_sha256}")
    note(f"archive bytes   {generated.archive_bytes}")

    # B. immutable archive storage --------------------------------------------
    step(2, "Confirm the archive was stored before the row referencing it")
    stored = list(storage.objects)
    note(f"objects stored  {len(stored)}")
    recomputed = hashlib.sha256(storage.objects[stored[0]]).hexdigest()
    note(
        "stored bytes rehash matches manifest: "
        f"{recomputed == generated.archive_sha256}"
    )

    # C. package download ------------------------------------------------------
    step(3, "Issue a short-lived signed link to the exact stored bytes")
    url, row = await workflow.download_url(
        tenant_id=TENANT, actor=ACTOR, package_id=package_id
    )
    note(f"signed url      {url[:56]}...")
    note(f"hash on the row {row['archive_sha256'][:32]}...")

    # G/F. the AI must not run yet --------------------------------------------
    step(4, "Confirm the assistant is refused before deterministic evidence")
    try:
        require_deterministic_evidence({"status": "uploaded"})
    except DeterministicEvidenceNotReady as error:
        note(f"refused, correctly: {str(error)[:60]}...")
    else:  # pragma: no cover - would be a regression
        note("NOT REFUSED - this is a defect")
        return 1

    # D/F/G/H. upload, provenance, parse, compare ------------------------------
    step(5, "Upload the FIXTURE result and run the deterministic checks")
    outcome = await workflow.upload_result(
        tenant_id=TENANT,
        actor=ACTOR,
        package_id=package_id,
        filename="be_result.csv",
        content_type="text/csv",
        payload=fixture_result(
            str(generated.package.manifest["dataset_sha256"]), CASE
        ),
        # DECLARED. The whole point of the flag.
        evidence_origin=EvidenceOrigin.TEST_FIXTURE,
        run_id="dry-run-1",
    )
    note(f"run status      {outcome.status.value}")
    note(f"artifact sha    {outcome.artifact_sha256[:32]}...")
    comparison = outcome.comparison
    if comparison is None:
        note("no comparison produced - the fixture did not parse")
        return 1
    integrity = comparison.integrity.as_dict()
    for label, key in (
        ("package archive ", "package_integrity"),
        ("dataset stamp   ", "dataset_provenance"),
        ("case stamp      ", "validation_case_stamp"),
        ("program exec    ", "program_execution_integrity"),
    ):
        note(f"{label}{integrity.get(key)}")

    # E. log upload ------------------------------------------------------------
    step(6, "Upload a FIXTURE log and archive it unparsed")
    log_outcome = await workflow.upload_log(
        tenant_id=TENANT,
        actor=ACTOR,
        run_id=outcome.run_id,
        filename="sas.log",
        content_type="text/plain",
        payload=b"NOTE: DRY RUN FIXTURE. This is not a SAS log.\n",
    )
    note(f"status          {log_outcome.status.value}")
    note(f"detail          {log_outcome.detail}")

    # The operator attestation -------------------------------------------------
    step(7, "Record a FIXTURE operator attestation")
    attestation = build_attestation(
        package_id=package_id,
        archive_sha256=generated.archive_sha256,
        operator_name="Dry Run (not a real operator)",
        operator_organization="Dry Run (not a real organisation)",
        confirmed=True,
        sas_version="DRY-RUN-NOT-SAS",
        executed_at=datetime.now(UTC),
        submitted_by=ACTOR,
    )
    await repository.insert_attestation(
        tenant_id=TENANT, run_id=outcome.run_id,
        attestation=attestation, actor=ACTOR,
    )
    note(f"attestation v   {attestation.attestation_version}")
    note(f"hash            {attestation.attestation_hash[:32]}...")
    note(
        "program execution integrity after attesting: "
        f"{attestation.as_dict()['program_execution_integrity']}"
    )
    assert (
        attestation.as_dict()["program_execution_integrity"]
        == ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION.value
    ), "an attestation must never upgrade execution integrity"

    # J. AI advisory (only now that the facts exist) ---------------------------
    step(8, "The assistant is now permitted - the facts exist")
    run = await repository.get_run(tenant_id=TENANT, run_id=outcome.run_id)
    try:
        require_deterministic_evidence(run)
        note("permitted: comparison and integrity statuses are recorded")
    except DeterministicEvidenceNotReady as error:  # pragma: no cover
        note(f"still refused: {error}")
    note(
        "not invoked here: a model call on fixture numbers would produce prose "
        "about nothing"
    )

    # I/M. the reviewer's report ----------------------------------------------
    step(9, "Assemble the reviewer evidence report")
    package_row = await repository.get_package(
        tenant_id=TENANT, package_id=package_id
    )
    report = build_evidence_report(
        run={**run, "id": outcome.run_id},
        package=package_row,
        attestations=await repository.list_attestations(
            tenant_id=TENANT, run_id=outcome.run_id
        ),
    )
    note(f"evidence origin {report.evidence_origin.value}")
    note(f"regulatory      {report.is_regulatory_evidence}")
    note(f"banner          {report.banner}")

    # N. audit trail ----------------------------------------------------------
    step(10, "Audit trail")
    for action, entity in repository.audit:
        note(f"{action:<44} {str(entity)[:24]}")

    print("\n" + "=" * 72)
    print("DRY RUN COMPLETE")
    print("=" * 72)
    print(
        f"""
  Every step of the operational path executed.

  What this DOES show
      package generation, immutable storage, signed download, upload,
      provenance checking, parsing, comparison, integrity reporting,
      attestation, ordering of the AI step, report assembly, audit trail

  What this does NOT show
      anything whatever about the partial-replicate denominator df. The
      fixture's value is {FIXTURE_DF}, chosen to be obviously not a SAS
      answer.

  {BANNER}

  The remaining input is a real result from a licensed SAS environment. No
  substitute - PowerTOST, Julia, Python or a model - can stand in for it.
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
