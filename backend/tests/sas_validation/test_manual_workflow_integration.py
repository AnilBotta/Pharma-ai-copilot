"""WORKFLOW INTEGRATION TEST - not a SAS validation test.

WHAT THIS DOES AND DOES NOT DEMONSTRATE

It exercises the plumbing: generate a package, persist it, retrieve the exact
archive bytes back, upload a synthetic structured result, verify hashes, parse,
compare, and land in a review-required state.

It does NOT execute SAS, and it does not validate anything statistical. The
uploaded result is a fixture this repository wrote, so the numbers coming out
are the numbers we put in. Calling this a "SAS validation test" would suggest a
regulatory question had been answered by running the suite, which is exactly
the confusion the naming here avoids.

The fakes are deliberately thin. `FakeStorage` keeps bytes in a dict and hashes
what it was given; `FakeRepository` keeps rows in dicts and records the audit
actions it was asked to emit. What is being tested is the workflow's ORDER and
its refusals, not a database.
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest

from app.sas_validation.modes import SASValidationRunStatus
from app.sas_validation.repository import (
    ACTION_COMPARISON_CREATED,
    ACTION_HASH_MISMATCH,
    ACTION_PACKAGE_DOWNLOADED,
    ACTION_PACKAGE_GENERATED,
    ACTION_RESULT_UPLOADED,
    PackageNotFound,
)
from app.sas_validation.storage import StorageError
from app.sas_validation.workflow import ManualValidationWorkflow, UploadRejected

CASE = "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "00000000-0000-0000-0000-0000000000ff"
ACTOR = "user-1"

def synthetic_result(
    *,
    dataset_sha256: str,
    case_id: str = CASE,
    df: str = "19.8906",
    convergence: str = "0|Convergence criteria met.",
    include_stamps: bool = True,
) -> bytes:
    """A structured result shaped exactly as validate.sas writes one.

    The dataset hash is passed in rather than hard-coded, because a real
    result carries the hash of the package that produced it - that is what
    makes the upload self-identifying. A fixture with a fixed hash would only
    ever match a fixed package, and would stop matching the moment the
    generator changed.

    The df is the independent candidate's, because that is what a real run
    might plausibly return. Nothing here expects or requires it.
    """
    rows = [
        "section,name,value",
        f"estimate,T vs. R,0.0223913|0.0303172|{df}|-0.0299207|0.0747033",
        "covparm,FA(1_1) ,0.2654",
        "covparm,Residual TRT R,0.0132",
        f"convergence,status,{convergence}",
        "environment,sas_version,9.04.01M8P011823",
    ]
    if include_stamps:
        rows += [
            f"environment,case_id,{case_id}",
            f"environment,dataset_sha256,{dataset_sha256}",
        ]
    return ("\n".join(rows) + "\n").encode()


def result_for(generated) -> bytes:
    return synthetic_result(
        dataset_sha256=str(generated.package.manifest["dataset_sha256"])
    )


class FakeStorage:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_on = fail_on

    async def upload(self, path: str, payload: bytes, *, content_type: str) -> str:
        if self.fail_on and self.fail_on in path:
            raise StorageError(f"synthetic storage failure for {path}")
        if path in self.objects:
            raise StorageError(f"{path} already exists")
        self.objects[path] = payload
        return hashlib.sha256(payload).hexdigest()

    async def exists(self, path: str) -> bool:
        return path in self.objects

    async def download(self, path: str) -> bytes:
        return self.objects[path]

    async def create_signed_download_url(self, path: str, *, filename: str) -> str:
        if path not in self.objects:
            raise StorageError(f"{path} not found")
        return f"https://storage.example/{path}?token=fake&download={filename}"


class FakeRepository:
    def __init__(self, *, fail_insert: bool = False) -> None:
        self.packages: dict[tuple[str, str], dict] = {}
        self.runs: dict[tuple[str, str], dict] = {}
        self.artifacts: list[dict] = []
        self.audit: list[tuple[str, str]] = []
        self.fail_insert = fail_insert

    async def insert_package(self, *, tenant_id, actor, package,
                             archive_storage_path, archive_sha256, archive_bytes):
        if self.fail_insert:
            raise RuntimeError("synthetic database failure")
        self.packages[(tenant_id, package.package_id)] = {
            "id": package.package_id,
            "tenant_id": tenant_id,
            "case_id": package.case_id,
            "dataset_sha256": package.manifest["dataset_sha256"],
            "program_sha256": package.manifest["program_sha256"],
            "archive_storage_path": archive_storage_path,
            "archive_sha256": archive_sha256,
            "archive_bytes": archive_bytes,
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
        run_id = run.get("id") or "run-1"
        self.runs[(run["tenant_id"], run_id)] = {**run, "id": run_id}
        self.audit.append((action, run_id))
        return run_id

    async def get_run(self, *, tenant_id, run_id):
        try:
            return self.runs[(tenant_id, run_id)]
        except KeyError:
            raise PackageNotFound(run_id) from None

    async def insert_artifact(self, *, tenant_id, actor, run_id, kind, filename,
                              content_sha256, byte_size, storage_ref):
        for existing in self.artifacts:
            if (existing["run_id"], existing["kind"], existing["sha"]) == (
                run_id, kind, content_sha256
            ):
                return existing["id"], False
        artifact = {
            "id": f"artifact-{len(self.artifacts) + 1}",
            "run_id": run_id, "kind": kind, "sha": content_sha256,
            "filename": filename, "bytes": byte_size, "ref": storage_ref,
        }
        self.artifacts.append(artifact)
        self.audit.append((
            ACTION_RESULT_UPLOADED if kind == "result_file" else "LOG", run_id
        ))
        return artifact["id"], True


def make_workflow(**kwargs) -> tuple[ManualValidationWorkflow, FakeRepository, FakeStorage]:
    repository = FakeRepository(fail_insert=kwargs.pop("fail_insert", False))
    storage = FakeStorage(fail_on=kwargs.pop("fail_on", None))
    workflow = ManualValidationWorkflow(
        repository=repository,
        storage=storage,
        be_stats_version="0.7.0",
        git_sha="abc1234",
    )
    return workflow, repository, storage


# ------------------------------------------------------- the happy path ---


@pytest.mark.asyncio
async def test_the_whole_manual_workflow_from_generation_to_review_required():
    workflow, repository, storage = make_workflow()

    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    # The archive is real, and contains what the package said it would.
    assert generated.archive_bytes > 0
    with zipfile.ZipFile(BytesIO(storage.objects[generated.archive_storage_path])) as z:
        assert set(z.namelist()) == {
            "README.md", "validate.sas", "dataset.csv",
            "model_specification.json", "manifest.json",
        }
        # And it is the canonical dataset - 72 rows plus a header.
        assert len(z.read("dataset.csv").decode().strip().splitlines()) == 73

    # Download returns a signed link to the EXACT stored bytes; nothing rebuilt.
    url, row = await workflow.download_url(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id
    )
    assert url.startswith("https://storage.example/")
    assert row["archive_sha256"] == generated.archive_sha256

    outcome = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR,
        package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
    )

    # The engine declines to compute this case, so nothing is comparable and a
    # human is required. That is the correct end state today.
    assert outcome.status is SASValidationRunStatus.REVIEW_REQUIRED
    assert outcome.comparison is not None
    assert outcome.artifact_created is True

    actions = [action for action, _ in repository.audit]
    assert ACTION_PACKAGE_GENERATED in actions
    assert ACTION_PACKAGE_DOWNLOADED in actions
    assert ACTION_RESULT_UPLOADED in actions
    assert ACTION_COMPARISON_CREATED in actions


@pytest.mark.asyncio
async def test_the_stored_archive_is_never_rebuilt_on_download():
    """Byte-for-byte the same object, however many times it is fetched."""
    workflow, _, storage = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)
    first = storage.objects[generated.archive_storage_path]

    for _ in range(3):
        await workflow.download_url(
            tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id
        )
    assert storage.objects[generated.archive_storage_path] == first


@pytest.mark.asyncio
async def test_the_archive_is_deterministic_across_builds():
    """Two packages of the same case produce identical archive bytes.

    The archive hash is what a customer checks their download against, so a
    ZIP that varied with the clock would make that check meaningless.
    """
    first, _, storage_a = make_workflow()
    second, _, storage_b = make_workflow()
    a = await first.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)
    b = await second.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    assert storage_a.objects[a.archive_storage_path] == (
        storage_b.objects[b.archive_storage_path]
    )
    assert a.archive_sha256 == b.archive_sha256


# ----------------------------------------------------------- refusals ---


@pytest.mark.asyncio
async def test_a_result_for_a_different_package_is_hash_mismatch_and_kept():
    """Rejected evidence is still stored. It is the record of a discrepancy."""
    workflow, repository, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    # Corrupt the stored package's hashes, so the uploaded result no longer
    # corresponds to the data and program we generated.
    row = repository.packages[(TENANT, generated.package.package_id)]
    row["dataset_sha256"] = "f" * 64

    outcome = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR,
        package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
    )

    assert outcome.status is SASValidationRunStatus.HASH_MISMATCH
    assert outcome.comparison is None
    assert len(repository.artifacts) == 1  # kept
    assert ACTION_HASH_MISMATCH in [action for action, _ in repository.audit]


@pytest.mark.asyncio
async def test_another_tenants_package_cannot_be_read_or_uploaded_against():
    workflow, _, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    with pytest.raises(PackageNotFound):
        await workflow.download_url(
            tenant_id=OTHER_TENANT, actor=ACTOR,
            package_id=generated.package.package_id,
        )
    with pytest.raises(PackageNotFound):
        await workflow.upload_result(
            tenant_id=OTHER_TENANT, actor=ACTOR,
            package_id=generated.package.package_id,
            filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
        )


@pytest.mark.asyncio
async def test_an_unknown_package_is_not_found():
    workflow, _, _ = make_workflow()
    with pytest.raises(PackageNotFound):
        await workflow.download_url(
            tenant_id=TENANT, actor=ACTOR, package_id="0" * 64
        )


@pytest.mark.asyncio
async def test_a_duplicate_upload_is_idempotent():
    """The same bytes twice is the same evidence, not two pieces of it."""
    workflow, repository, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    first = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
        run_id="run-fixed",
    )
    second = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
        run_id="run-fixed",
    )

    assert first.artifact_created is True
    assert second.artifact_created is False
    assert len(repository.artifacts) == 1
    assert first.artifact_sha256 == second.artifact_sha256


@pytest.mark.asyncio
async def test_different_bytes_for_the_same_run_are_a_second_artifact():
    """Evidence is never overwritten - a second attempt is a second artifact."""
    workflow, repository, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
        run_id="run-fixed",
    )
    await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv",
        payload=synthetic_result(
            dataset_sha256=str(generated.package.manifest['dataset_sha256']),
            df='22.5403',
        ),
        run_id="run-fixed",
    )
    assert len(repository.artifacts) == 2


@pytest.mark.asyncio
async def test_a_malformed_result_is_incomplete_and_not_compared():
    workflow, _, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    outcome = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv",
        payload=b"NOTE: PROCEDURE MIXED used (Total process time):\n",
    )
    assert outcome.status is SASValidationRunStatus.INCOMPLETE
    assert outcome.comparison is None


@pytest.mark.asyncio
async def test_a_result_missing_fields_is_incomplete():
    workflow, _, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    outcome = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv",
        payload=synthetic_result(
            dataset_sha256=str(generated.package.manifest['dataset_sha256']),
            df='.',
        ),
    )
    assert outcome.status is SASValidationRunStatus.INCOMPLETE


# ------------------------------------------------- storage / db failures ---


@pytest.mark.asyncio
async def test_a_storage_failure_during_generation_creates_no_package_row():
    """No partial state that could masquerade as a usable package."""
    workflow, repository, _ = make_workflow(fail_on="packages")

    with pytest.raises(StorageError):
        await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    assert repository.packages == {}
    assert repository.audit == []


@pytest.mark.asyncio
async def test_a_database_failure_during_generation_leaves_no_usable_package():
    """The archive is orphaned in the bucket - litter, and the safe direction.

    The unsafe direction would be a package row pointing at an object that was
    never stored, which migration 0033's check constraint refuses outright.
    """
    workflow, repository, storage = make_workflow(fail_insert=True)

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)

    assert repository.packages == {}
    assert len(storage.objects) == 1  # orphaned, unreferenced


@pytest.mark.asyncio
async def test_a_log_contradicting_convergence_raises_review_required():
    """A text match is a signal for a human, not a verdict."""
    workflow, _, _ = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)
    result = await workflow.upload_result(
        tenant_id=TENANT, actor=ACTOR, package_id=generated.package.package_id,
        filename="be_result.csv", content_type="text/csv", payload=result_for(generated),
        run_id="run-fixed",
    )

    outcome = await workflow.upload_log(
        tenant_id=TENANT, actor=ACTOR, run_id=result.run_id,
        filename="sas.log", content_type="text/plain",
        payload=b"NOTE: starting\nERROR: Insufficient memory.\nNOTE: done\n",
    )
    assert outcome.status is SASValidationRunStatus.REVIEW_REQUIRED
    assert "contradiction" in outcome.detail


# -------------------------------------------------- upload type and size ---


#: `payload` is a callable so an oversized case does not put two megabytes of
#: "x" into the test id, which made the failure output unreadable.
@pytest.mark.parametrize(
    "filename,content_type,payload,expected",
    [
        pytest.param("be_result.csv", "text/csv", lambda: b"", "empty", id="empty"),
        pytest.param("be_result.zip", "application/zip", lambda: b"PK\x03\x04",
                     "ending in .csv", id="wrong-extension"),
        pytest.param("be_result.csv", "application/zip",
                     lambda: b"section,name,value\n", "not accepted",
                     id="wrong-content-type"),
        pytest.param("../etc/passwd.csv", "text/csv",
                     lambda: b"section,name,value\n", "path", id="path-in-filename"),
        pytest.param("be_result.csv", "text/csv", lambda: b"\x00\x01\x02binary",
                     "binary", id="binary"),
        pytest.param("be_result.csv", "text/csv",
                     lambda: b"x" * (2 * 1024 * 1024 + 1), "limit", id="oversized"),
    ],
)
@pytest.mark.asyncio
async def test_unacceptable_uploads_are_refused_before_storage(
    filename, content_type, payload, expected
):
    payload = payload()
    workflow, _, storage = make_workflow()
    generated = await workflow.generate(tenant_id=TENANT, actor=ACTOR, case_id=CASE)
    before = len(storage.objects)

    with pytest.raises(UploadRejected, match=expected):
        await workflow.upload_result(
            tenant_id=TENANT, actor=ACTOR,
            package_id=generated.package.package_id,
            filename=filename, content_type=content_type, payload=payload,
        )
    assert len(storage.objects) == before, "a refused upload became an object"
