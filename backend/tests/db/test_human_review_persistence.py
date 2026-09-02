"""A rejection must be storable, proven against the real schema.

WHY THIS TEST EXISTS

`human_review.prepare_review` is right: an acceptance carries the versioned,
hashed acknowledgement, and a rejection carries none of it, because the
acknowledgement's wording is "I accept this SAS run as suitable oracle
evidence" and attaching that to a rejection would record someone accepting
what they rejected.

Migration 0034 originally declared those three columns NOT NULL. So the domain
layer correctly produced nulls and the database correctly refused them, and
EVERY REJECTION FAILED AT INSERT. Both halves passed their own tests. Nothing
in the pure-domain suite could see it, because the pure-domain suite never
reaches a database.

That is the whole argument for this file: the contract under test is the one
between `repository.insert_human_review` and the schema, and a mock of either
side would agree with itself.

WHAT IT DOES TO THE DATABASE

Nothing durable. Migrations 0032 and 0034 are applied inside a transaction
that is rolled back, so this also proves both files are valid SQL against the
live server. 0033 is not applied: it concerns the storage bucket and the
archive columns, and nothing here touches either.

    python tests/db/test_human_review_persistence.py
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.db import _init_connection
from app.sas_validation.attestation import EvidenceOrigin
from app.sas_validation.authorization import ReviewerIdentity
from app.sas_validation.human_review import (
    ACKNOWLEDGEMENT_HASH,
    ACKNOWLEDGEMENT_TEXT,
    ACKNOWLEDGEMENT_VERSION,
    AcceptancePreconditions,
    OracleClosureDecision,
    PreconditionFailed,
    prepare_review,
)
from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    ProgramExecutionIntegrity,
)
from app.sas_validation.repository import SASValidationRepository

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"

REVIEWER_ID = "hr000000-0000-0000-0000-000000000001".replace("hr", "fa")
TENANT = "00000000-0000-0000-0000-000000000001"
PACKAGE_ID = "a" * 64

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class PoolShim:
    """One connection, so every write lands in the rolled-back transaction."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def dsn() -> str:
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


async def refused(conn, coro):
    """Await something expected to fail, inside a savepoint.

    A failed statement aborts the enclosing transaction, so without the
    savepoint every later assertion in this file would fail for the wrong
    reason.

    Returns the CONSTRAINT NAME rather than a truncated message. "Postgres
    refused it" is a much weaker claim than "the constraint I wrote refused
    it" - a not-null violation and a check violation would look identical in
    prose, and the not-null violation is the bug this file exists to catch.
    """
    savepoint = conn.transaction()
    await savepoint.start()
    outcome = (False, "it was accepted")
    try:
        await coro
    except asyncpg.PostgresError as error:
        outcome = (
            True,
            getattr(error, "constraint_name", None) or type(error).__name__,
        )
    finally:
        await savepoint.rollback()
    return outcome


def preconditions(**overrides) -> AcceptancePreconditions:
    fields = {
        # A sound REAL run. This file is about the PERSISTENCE contract; that
        # a fixture cannot be accepted at all is asserted in
        # tests/sas_validation/test_first_live_run_readiness.py.
        "evidence_origin": EvidenceOrigin.MANUAL_EXTERNAL_SAS,
        "package_integrity": PackageIntegrity.VERIFIED,
        "dataset_provenance": DatasetProvenance.MATCH,
        "case_stamp": DatasetProvenance.MATCH,
        "program_execution": ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION,
        "result_complete": True,
        "sas_version_present": True,
        "denominator_df_present": True,
        "confidence_interval_present": True,
        "convergence_failed": False,
        "comparison_available": True,
        "acknowledged": True,
    }
    fields.update(overrides)
    return AcceptancePreconditions(**fields)


async def insert_raw(conn, *, decision: str, version, text, ack_hash) -> None:
    """Write straight to the table, bypassing the domain layer entirely.

    Cases D and B need to prove the DATABASE refuses a shape, not that Python
    declines to build it - so they must not go through `prepare_review`.
    """
    await conn.execute(
        """
        insert into public.sas_human_reviews
            (tenant_id, run_id, actor_type, reviewer_user_id, reviewer_role_key,
             decision, notes, acknowledgement_version, acknowledgement_text,
             acknowledgement_hash, evidence_snapshot, evidence_snapshot_hash)
        select $1, r.id, 'human', $2, 'system_administrator',
               $3::public.oracle_closure_decision, 'raw insert',
               $4, $5, $6, '{}'::jsonb, $7
          from public.sas_validation_runs r limit 1
        """,
        TENANT, REVIEWER_ID, decision, version, text, ack_hash, "b" * 64,
    )


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    await _init_connection(conn)

    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------- migrations ---
        # Apply only what is not already there.
        #
        # Before deployment this file created the whole schema inside the
        # transaction, which also proved the migration files were valid SQL.
        # Now that 0032-0036 are deployed for real, re-applying them raises
        # DuplicateObject - so the schema is used where it exists and built
        # where it does not, and the file works either way.
        for name, sentinel in (
            ("0032_sas_validation.sql", "public.sas_validation_packages"),
            ("0034_sas_validation_review.sql", "public.sas_human_reviews"),
            ("0035_sas_operator_attestation.sql", "public.sas_operator_attestations"),
        ):
            if await conn.fetchval("select to_regclass($1) is not null", sentinel):
                print(f"    {name:<38} already deployed; using it")
                continue
            await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
            print(f"    {name:<38} applied inside the transaction")

        # ------------------------------------------------------------ setup ---
        await conn.execute(
            """
            insert into auth.users (id, instance_id, aud, role, email,
                encrypted_password, email_confirmed_at, created_at, updated_at)
            values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                    'authenticated','hr-reviewer@test.local','x',now(),now(),now())
            on conflict (id) do nothing
            """,
            REVIEWER_ID,
        )
        await conn.execute(
            "insert into public.profiles (id, email) values ($1, $2) "
            "on conflict (id) do nothing",
            REVIEWER_ID, "hr-reviewer@test.local",
        )
        await conn.execute(
            """
            insert into public.sas_validation_packages
                (id, tenant_id, case_id, regulatory_method, dataset_sha256,
                 program_sha256, model_specification_sha256, manifest, files,
                 be_stats_version, git_sha, generated_at)
            values ($1,$2,'FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II',
                    'FDA_REPLICATE_STANDARD_ABE_PARTIAL',$3,$3,$3,
                    '{}'::jsonb,'[]'::jsonb,'0.0.0','test',now())
            """,
            PACKAGE_ID, TENANT, "c" * 64,
        )
        run_id = await conn.fetchval(
            """
            insert into public.sas_validation_runs
                (tenant_id, package_id, case_id, sas_mode, status)
            values ($1,$2,'FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II',
                    'manual_upload','review_required')
            returning id
            """,
            TENANT, PACKAGE_ID,
        )

        repository = SASValidationRepository(PoolShim(conn))
        reviewer = ReviewerIdentity.for_human(
            user_id=REVIEWER_ID, role_key="system_administrator"
        )

        def record(decision: OracleClosureDecision, **overrides):
            kwargs = {
                "reviewer": reviewer,
                "run_id": str(run_id),
                "tenant_id": TENANT,
                "decision": decision,
                "notes": "Recorded by the persistence regression test.",
                "acknowledged": decision
                is OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
                "preconditions": preconditions(),
                "evidence_snapshot": {"case": "test"},
                "evidence_snapshot_hash": "b" * 64,
            }
            kwargs.update(overrides)
            return prepare_review(**kwargs)

        # --- A. an accepted review with a valid acknowledgement persists -----
        print("\n  A. accepted + acknowledgement -> persists")
        accepted = record(OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED)
        check(
            "the domain layer attaches the acknowledgement",
            accepted.acknowledgement_hash == ACKNOWLEDGEMENT_HASH
            and accepted.acknowledgement_version == ACKNOWLEDGEMENT_VERSION
            and accepted.acknowledgement_text == ACKNOWLEDGEMENT_TEXT,
        )
        accepted_id = await repository.insert_human_review(record=accepted)
        stored = await conn.fetchrow(
            "select * from public.sas_human_reviews where id = $1::uuid", accepted_id
        )
        check("the row exists", stored is not None)
        check(
            "it stores the acknowledgement, not a placeholder",
            stored["acknowledgement_hash"] == ACKNOWLEDGEMENT_HASH
            and stored["acknowledgement_text"] == ACKNOWLEDGEMENT_TEXT,
        )

        # --- B. an acceptance with no acknowledgement is refused twice -------
        print("\n  B. accepted without acknowledgement -> refused")
        domain_refused = False
        try:
            record(
                OracleClosureDecision.ORACLE_CLOSURE_ACCEPTED,
                acknowledged=False,
                preconditions=preconditions(acknowledged=False),
            )
        except PreconditionFailed as error:
            domain_refused = "acknowledgement" in str(error)
        check("the domain layer refuses it before any insert", domain_refused)

        ok, detail = await refused(
            conn,
            insert_raw(
                conn,
                decision="oracle_closure_accepted",
                version=None,
                text=None,
                ack_hash=None,
            ),
        )
        check(
            "and the database refuses it too, on a raw insert",
            ok and detail == "sas_human_reviews_acknowledgement_matches_decision",
            detail,
        )

        # --- C. a rejection with null acknowledgement persists ---------------
        # THE BUG THIS FILE WAS WRITTEN FOR. Before the fix, this insert failed
        # with a not-null violation on acknowledgement_version.
        print("\n  C. rejected + null acknowledgement -> persists")
        rejected = record(
            OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
            notes="The dataset provenance does not identify this package.",
        )
        check(
            "the domain layer attaches no acknowledgement",
            rejected.acknowledgement_version is None
            and rejected.acknowledgement_text is None
            and rejected.acknowledgement_hash is None,
        )
        rejected_id = await repository.insert_human_review(record=rejected)
        stored = await conn.fetchrow(
            "select * from public.sas_human_reviews where id = $1::uuid", rejected_id
        )
        check("the row exists", stored is not None)
        check(
            "and its acknowledgement columns are NULL, not empty strings",
            stored["acknowledgement_version"] is None
            and stored["acknowledgement_text"] is None
            and stored["acknowledgement_hash"] is None,
        )

        # --- D. a rejection carrying an acknowledgement is refused -----------
        print("\n  D. rejected + acknowledgement -> refused by the database")
        ok, detail = await refused(
            conn,
            insert_raw(
                conn,
                decision="oracle_closure_rejected",
                version=ACKNOWLEDGEMENT_VERSION,
                text=ACKNOWLEDGEMENT_TEXT,
                ack_hash=ACKNOWLEDGEMENT_HASH,
            ),
        )
        check("a rejection cannot claim the reviewer accepted anything", ok, detail)
        check(
            "and it is the decision-dependent constraint that says so",
            detail == "sas_human_reviews_acknowledgement_matches_decision",
            detail,
        )

        # --- E. a rejection still requires notes -----------------------------
        print("\n  E. rejected without notes -> refused")
        notes_refused = False
        try:
            record(OracleClosureDecision.ORACLE_CLOSURE_REJECTED, notes="   ")
        except ValueError as error:
            notes_refused = "notes are required" in str(error)
        check("the domain layer refuses empty notes", notes_refused)

        ok, detail = await refused(
            conn,
            conn.execute(
                """
                insert into public.sas_human_reviews
                    (tenant_id, run_id, reviewer_user_id, reviewer_role_key,
                     decision, notes, evidence_snapshot, evidence_snapshot_hash)
                values ($1,$2::uuid,$3,'system_administrator',
                        'oracle_closure_rejected','   ','{}'::jsonb,$4)
                """,
                TENANT, str(run_id), REVIEWER_ID, "b" * 64,
            ),
        )
        check(
            "and so does the database",
            ok and detail == "sas_human_reviews_notes_not_empty",
            detail,
        )

        # --- F. a rejection needs none of the acceptance preconditions -------
        # Otherwise a broken run could never be closed out - which is exactly
        # when a reviewer most needs to record what is wrong with it.
        print("\n  F. rejected against unusable evidence -> still persists")
        for label, override in (
            ("mismatched dataset provenance", {"dataset_provenance": DatasetProvenance.MISMATCH}),
            ("an incomplete result", {"result_complete": False}),
            ("a non-converged fit", {"convergence_failed": True}),
            ("no comparison at all", {"comparison_available": False}),
        ):
            written = await repository.insert_human_review(
                record=record(
                    OracleClosureDecision.ORACLE_CLOSURE_REJECTED,
                    notes=f"Rejected: {label}.",
                    acknowledged=False,
                    preconditions=preconditions(**override),
                )
            )
            check(f"rejection persists with {label}", bool(written))

        # --- G. the attestation and evidence origin (migration 0035) --------
        print("\n  G. operator attestation and evidence origin")
        origin = await conn.fetchval(
            "select evidence_origin from public.sas_validation_runs where id = $1",
            run_id,
        )
        check(
            "a run defaults to test_fixture, the safe answer",
            origin == "test_fixture",
            str(origin),
        )

        attestation_id = await conn.fetchval(
            """
            insert into public.sas_operator_attestations
                (tenant_id, run_id, package_id, archive_sha256, operator_name,
                 operator_organization, sas_version, attestation_version,
                 attestation_text, attestation_hash, submitted_by)
            values ($1,$2::uuid,$3,$4,'A. Operator','Client Pharma Ltd',
                    '9.04.01M8','sas-operator-attestation/1',
                    'I confirm that I executed ...',$5,$6)
            returning id
            """,
            TENANT, str(run_id), PACKAGE_ID, "d" * 64, "e" * 64, REVIEWER_ID,
        )
        check("an attestation persists", bool(attestation_id))

        ok, detail = await refused(
            conn,
            conn.execute(
                "update public.sas_operator_attestations "
                "   set operator_name = 'Somebody Else' where id = $1::uuid",
                attestation_id,
            ),
        )
        check("and it cannot be edited afterwards", ok, detail)

        ok, detail = await refused(
            conn,
            conn.execute(
                """
                insert into public.sas_operator_attestations
                    (tenant_id, run_id, package_id, archive_sha256,
                     operator_name, operator_organization,
                     attestation_version, attestation_text, attestation_hash)
                values ($1,$2::uuid,$3,$4,'   ','   ','v','t',$5)
                """,
                TENANT, str(run_id), PACKAGE_ID, "d" * 64, "e" * 64,
            ),
        )
        check(
            "an attestation with no named operator is refused",
            ok and detail == "sas_operator_attestations_operator_named",
            detail,
        )

        # --- H. the package insert accepts what the package model holds -----
        #
        # THE BUG THIS CATCHES, WHICH ONLY A REAL POSTGRES CAN SEE.
        #
        # `ValidationPackage.generated_at` is an ISO string, because it is part
        # of the manifest and therefore of the package hash. asyncpg binds a
        # `$n::timestamptz` parameter in binary and demanded a datetime, so
        # EVERY real package generation failed at the insert - while the
        # workflow tests passed, because their in-memory repository accepts any
        # Python object. Deployment was the first thing with an opinion.
        print("\n  H. a real package row round-trips through the real schema")
        from app.sas_validation.package import build_package
        from app.sas_validation.targets import get_target

        package = build_package(
            target=get_target("FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"),
            observations=[
                {"subject": 1, "sequence": "TRR", "period": 1,
                 "treatment": "T", "value": 100.0},
            ],
            be_stats_version="0.0.0-test",
            git_sha="deadbeef",
        )
        check(
            "generated_at is a string, as the manifest requires",
            isinstance(package.generated_at, str),
            type(package.generated_at).__name__,
        )
        await repository.insert_package(
            tenant_id=TENANT,
            actor=REVIEWER_ID,
            package=package,
            archive_storage_path=f"{TENANT}/{package.package_id}.zip",
            archive_sha256="1" * 64,
            archive_bytes=1234,
        )
        stored_at = await conn.fetchval(
            "select generated_at from public.sas_validation_packages where id = $1",
            package.package_id,
        )
        check("the row exists and its timestamp parsed", stored_at is not None,
              str(stored_at))

        # ------------------------------------------------ nothing promoted ---
        print("\n  and the run's own status was not promoted by any of it")
        status = await conn.fetchval(
            "select review_status from public.sas_validation_runs where id = $1",
            run_id,
        )
        check("review_status is still not_assessed", status == "not_assessed", str(status))

    finally:
        await tx.rollback()
        await conn.close()

    print(f"\n  {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
