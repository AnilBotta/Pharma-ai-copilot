"""Persistence for SAS validation, and the audit trail that goes with it.

HOUSE CONVENTIONS THIS FOLLOWS RATHER THAN REINVENTS

The backend connects with the service role, so RLS does not restrict it and
every query filters explicitly - `db.py` says so and `repository.py` repeats
it. Audit events go through `private.record_audit_event`, the same function the
stage-gate and notification modules use, with the same parameter shape.

WHAT IS AUDITED, AND WHAT IS NEVER AUDITED

Audited: who did it, when, which package and run, which case, the artifact
hashes, and the resulting status.

Never audited: file contents, SAS credentials, secrets. A hash identifies
evidence without reproducing it, which is the whole reason the audit rows carry
hashes rather than payloads.

ORDER OF OPERATIONS ON UPLOAD

The raw artifact is stored and hashed BEFORE anything is parsed or compared,
and it is kept even when the hashes turn out not to match. A rejected upload is
the record of a discrepancy at the moment it is most interesting, and a
pipeline that discarded it would destroy the evidence that something went
wrong.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

ENTITY_PACKAGE = "sas_validation_package"
ENTITY_RUN = "sas_validation_run"

#: Every audit action this module can emit. Named as constants so a typo
#: produces an import error rather than an unqueryable audit row.
ACTION_PACKAGE_GENERATED = "SAS_VALIDATION_PACKAGE_GENERATED"
ACTION_PACKAGE_DOWNLOADED = "SAS_VALIDATION_PACKAGE_DOWNLOADED"
ACTION_RESULT_UPLOADED = "SAS_VALIDATION_RESULT_UPLOADED"
ACTION_LOG_UPLOADED = "SAS_VALIDATION_LOG_UPLOADED"
ACTION_HASH_MISMATCH = "SAS_VALIDATION_HASH_MISMATCH"
ACTION_PARSED = "SAS_VALIDATION_PARSED"
ACTION_COMPARISON_CREATED = "SAS_VALIDATION_COMPARISON_CREATED"
ACTION_REVIEW_BLOCKED = "SAS_VALIDATION_REVIEW_ATTEMPT_BLOCKED"

#: Active as of PR #66, now that `private.user_has_global_role` lets the
#: backend identify an authorised human. Both carry actor_type = HUMAN.
ACTION_REVIEW_ACCEPTED = "SAS_VALIDATION_REVIEW_ACCEPTED"
ACTION_REVIEW_REJECTED = "SAS_VALIDATION_REVIEW_REJECTED"

#: The assistant's activity, kept separate from the human's so a query for
#: "who approved what" cannot pick up an AI row.
ACTION_AI_REVIEW_GENERATED = "SAS_VALIDATION_AI_REVIEW_GENERATED"
ACTION_AI_REVIEW_FAILED = "SAS_VALIDATION_AI_REVIEW_FAILED"

ENTITY_AI_REVIEW = "sas_ai_review"
ENTITY_HUMAN_REVIEW = "sas_human_review"

AUDIT_ACTIONS = (
    ACTION_PACKAGE_GENERATED,
    ACTION_PACKAGE_DOWNLOADED,
    ACTION_RESULT_UPLOADED,
    ACTION_LOG_UPLOADED,
    ACTION_HASH_MISMATCH,
    ACTION_PARSED,
    ACTION_COMPARISON_CREATED,
    ACTION_REVIEW_BLOCKED,
    ACTION_REVIEW_ACCEPTED,
    ACTION_REVIEW_REJECTED,
    ACTION_AI_REVIEW_GENERATED,
    ACTION_AI_REVIEW_FAILED,
)


class PackageNotFound(Exception):
    """No such package for this tenant.

    Following `repository.NotFound`, this deliberately does not distinguish
    "absent" from "belongs to someone else" at the persistence layer: telling a
    caller that a package exists but is not theirs leaks its existence.
    """


class SASValidationRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ----------------------------------------------------------- auditing ---

    async def _audit(
        self,
        conn: Any,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        new: dict | None = None,
        reason: str | None = None,
    ) -> None:
        await conn.fetchval(
            """
            select private.record_audit_event(
                p_action        => $1,
                p_entity_type   => $2,
                p_entity_id     => $3,
                p_actor_user_id => $4,
                p_new           => $5,
                p_reason        => $6,
                p_actor_agent   => nullif(current_setting('app.acting_agent', true), ''),
                p_source        => 'api'
            )
            """,
            action,
            entity_type,
            str(entity_id),
            actor,
            json.dumps(new) if new is not None else None,
            reason,
        )

    # ----------------------------------------------------------- packages ---

    async def insert_package(
        self,
        *,
        tenant_id: str,
        actor: str,
        package: Any,
        archive_storage_path: str,
        archive_sha256: str,
        archive_bytes: int,
    ) -> None:
        """Write the package row and attach its archive, in one transaction.

        The row is inserted first so the storage path is owned by a database
        row from the outset - the same reasoning `documents/repository.py`
        gives. An object in the bucket with no row is unreferenced litter; a
        row with no object is a package that cannot be downloaded, and the
        0033 check constraint refuses that state.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                insert into public.sas_validation_packages
                    (id, tenant_id, case_id, regulatory_method,
                     dataset_sha256, program_sha256, model_specification_sha256,
                     manifest, files, be_stats_version, git_sha,
                     generated_at, generated_by,
                     archive_storage_path, archive_sha256, archive_bytes)
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                        $12::timestamptz, $13, $14, $15, $16)
                """,
                package.package_id,
                tenant_id,
                package.case_id,
                package.regulatory_method,
                str(package.manifest["dataset_sha256"]),
                str(package.manifest["program_sha256"]),
                str(package.manifest["model_specification_sha256"]),
                json.dumps(dict(package.manifest)),
                json.dumps(
                    [{"name": f.name, "sha256": f.sha256} for f in package.files]
                ),
                package.be_stats_version,
                package.git_sha,
                package.generated_at,
                actor,
                archive_storage_path,
                archive_sha256,
                archive_bytes,
            )
            await self._audit(
                conn,
                actor=actor,
                action=ACTION_PACKAGE_GENERATED,
                entity_type=ENTITY_PACKAGE,
                entity_id=package.package_id,
                new={
                    "case_id": package.case_id,
                    "dataset_sha256": package.manifest["dataset_sha256"],
                    "program_sha256": package.manifest["program_sha256"],
                    "archive_sha256": archive_sha256,
                    "be_stats_version": package.be_stats_version,
                    "git_sha": package.git_sha,
                    "n_observations": package.manifest["n_observations"],
                },
            )

    async def get_package(self, *, tenant_id: str, package_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                select * from public.sas_validation_packages
                 where id = $1 and tenant_id = $2
                """,
                package_id,
                tenant_id,
            )
        if row is None:
            raise PackageNotFound(package_id)
        return dict(row)

    async def list_packages(self, *, tenant_id: str, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, case_id, generated_at, generated_by,
                       archive_sha256, archive_bytes, be_stats_version, git_sha
                  from public.sas_validation_packages
                 where tenant_id = $1
                 order by generated_at desc
                 limit $2
                """,
                tenant_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def record_download(
        self, *, tenant_id: str, actor: str, package_id: str, archive_sha256: str
    ) -> None:
        """A download is an event, not a change to the package.

        The package row is untouched - historical bytes stay exactly as
        generated - and the fact that somebody took a copy lives in the audit
        trail where it belongs.
        """
        async with self._pool.acquire() as conn:
            await self._audit(
                conn,
                actor=actor,
                action=ACTION_PACKAGE_DOWNLOADED,
                entity_type=ENTITY_PACKAGE,
                entity_id=package_id,
                new={"archive_sha256": archive_sha256, "tenant_id": tenant_id},
            )

    # --------------------------------------------------------------- runs ---

    async def upsert_run(self, *, run: dict, actor: str, action: str,
                         reason: str | None = None) -> str:
        """Insert or update a run, and audit the transition that caused it."""
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into public.sas_validation_runs
                    (id, tenant_id, package_id, case_id, sas_mode,
                     sas_environment_name, sas_version, execution_timestamp,
                     uploaded_by, declared_dataset_sha256, declared_program_sha256,
                     estimate_log, estimate_ratio, standard_error, denominator_df,
                     ci_lower_log, ci_upper_log, ci_lower_ratio, ci_upper_ratio,
                     covariance_parameters, convergence_status, warnings,
                     status, comparison)
                values (coalesce($1::uuid, gen_random_uuid()), $2, $3, $4, $5,
                        $6, $7, $8::timestamptz, $9, $10, $11,
                        $12, $13, $14, $15, $16, $17, $18, $19,
                        $20, $21, $22, $23, $24)
                on conflict (id) do update set
                    sas_version           = excluded.sas_version,
                    estimate_log          = excluded.estimate_log,
                    estimate_ratio        = excluded.estimate_ratio,
                    standard_error        = excluded.standard_error,
                    denominator_df        = excluded.denominator_df,
                    ci_lower_log          = excluded.ci_lower_log,
                    ci_upper_log          = excluded.ci_upper_log,
                    ci_lower_ratio        = excluded.ci_lower_ratio,
                    ci_upper_ratio        = excluded.ci_upper_ratio,
                    covariance_parameters = excluded.covariance_parameters,
                    convergence_status    = excluded.convergence_status,
                    warnings              = excluded.warnings,
                    status                = excluded.status,
                    comparison            = excluded.comparison
                returning id
                """,
                run.get("id"),
                run["tenant_id"],
                run["package_id"],
                run["case_id"],
                run["sas_mode"],
                run.get("sas_environment_name"),
                run.get("sas_version"),
                run.get("execution_timestamp"),
                actor,
                run.get("declared_dataset_sha256"),
                run.get("declared_program_sha256"),
                run.get("estimate_log"),
                run.get("estimate_ratio"),
                run.get("standard_error"),
                run.get("denominator_df"),
                run.get("ci_lower_log"),
                run.get("ci_upper_log"),
                run.get("ci_lower_ratio"),
                run.get("ci_upper_ratio"),
                json.dumps(run.get("covariance_parameters") or {}),
                run.get("convergence_status"),
                json.dumps(run.get("warnings") or []),
                run["status"],
                json.dumps(run.get("comparison")) if run.get("comparison") else None,
            )
            run_id = str(row["id"])
            await self._audit(
                conn,
                actor=actor,
                action=action,
                entity_type=ENTITY_RUN,
                entity_id=run_id,
                new={
                    "package_id": run["package_id"],
                    "case_id": run["case_id"],
                    "status": run["status"],
                    "sas_version": run.get("sas_version"),
                },
                reason=reason,
            )
        return run_id

    async def get_run(self, *, tenant_id: str, run_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.sas_validation_runs "
                " where id = $1::uuid and tenant_id = $2",
                run_id,
                tenant_id,
            )
        if row is None:
            raise PackageNotFound(run_id)
        return dict(row)

    async def list_runs(self, *, tenant_id: str, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, package_id, case_id, status, review_status,
                       sas_version, uploaded_at, uploaded_by
                  from public.sas_validation_runs
                 where tenant_id = $1
                 order by uploaded_at desc
                 limit $2
                """,
                tenant_id,
                limit,
            )
        return [dict(row) for row in rows]

    # ---------------------------------------------------------- artifacts ---

    async def insert_artifact(
        self,
        *,
        tenant_id: str,
        actor: str,
        run_id: str,
        kind: str,
        filename: str,
        content_sha256: str,
        byte_size: int,
        storage_ref: str,
    ) -> tuple[str, bool]:
        """Record an artifact. Idempotent on (run, kind, hash).

        Returns (artifact_id, created). Re-uploading identical bytes for the
        same run and kind returns the existing row rather than creating a
        second one - the same evidence twice is not two pieces of evidence, and
        a reviewer should not have to work out whether a duplicate means
        anything.

        DIFFERENT bytes for the same run and kind DO create a new artifact.
        Evidence is never overwritten; a second attempt is a second artifact.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into public.sas_validation_artifacts
                    (tenant_id, run_id, kind, filename,
                     content_sha256, byte_size, storage_ref, uploaded_by)
                values ($1, $2::uuid, $3, $4, $5, $6, $7, $8)
                on conflict (run_id, kind, content_sha256) do nothing
                returning id
                """,
                tenant_id, run_id, kind, filename,
                content_sha256, byte_size, storage_ref, actor,
            )

            if row is not None:
                await self._audit(
                    conn,
                    actor=actor,
                    action=(
                        ACTION_LOG_UPLOADED if kind == "sas_log"
                        else ACTION_RESULT_UPLOADED
                    ),
                    entity_type=ENTITY_RUN,
                    entity_id=run_id,
                    new={
                        "kind": kind,
                        "filename": filename,
                        "content_sha256": content_sha256,
                        "byte_size": byte_size,
                    },
                )
                return str(row["id"]), True

            existing = await conn.fetchrow(
                """
                select id from public.sas_validation_artifacts
                 where run_id = $1::uuid and kind = $2 and content_sha256 = $3
                """,
                run_id, kind, content_sha256,
            )
            return str(existing["id"]), False

    async def list_artifacts(self, *, tenant_id: str, run_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, kind, filename, content_sha256, byte_size,
                       storage_ref, uploaded_at, uploaded_by
                  from public.sas_validation_artifacts
                 where run_id = $1::uuid and tenant_id = $2
                 order by uploaded_at
                """,
                run_id,
                tenant_id,
            )
        return [dict(row) for row in rows]

    # ------------------------------------------------------- AI reviews ---

    async def insert_ai_review(
        self, *, tenant_id: str, run_id: str, requested_by: str, outcome: Any
    ) -> str:
        """Append an AI analysis. Never replaces an earlier one.

        Model output is non-deterministic and model versions change, so a
        re-run is a genuinely different artefact. Overwriting would destroy the
        record of what a human reviewer actually read.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into public.sas_ai_reviews
                    (tenant_id, run_id, actor_type, model_provider, model_name,
                     prompt_version, evidence_snapshot_hash, response,
                     response_hash, recommendation, confidence, succeeded,
                     failure_reason, requested_by)
                values ($1, $2::uuid, 'ai_system', $3, $4, $5, $6, $7, $8,
                        $9::public.ai_review_recommendation,
                        $10::public.ai_review_confidence, $11, $12, $13)
                returning id
                """,
                tenant_id, run_id,
                outcome.model_provider, outcome.model_name,
                outcome.prompt_version, outcome.evidence_snapshot_hash,
                json.dumps(outcome.response.model_dump(mode="json"))
                if outcome.response else None,
                outcome.response_hash(),
                outcome.recommendation.value if outcome.recommendation else None,
                outcome.response.confidence.value if outcome.response else None,
                outcome.succeeded,
                outcome.failure_reason,
                requested_by,
            )
            review_id = str(row["id"])
            await self._audit(
                conn,
                actor=requested_by,
                action=(
                    ACTION_AI_REVIEW_GENERATED if outcome.succeeded
                    else ACTION_AI_REVIEW_FAILED
                ),
                entity_type=ENTITY_AI_REVIEW,
                entity_id=review_id,
                new={
                    "run_id": run_id,
                    "actor_type": "ai_system",
                    "prompt_version": outcome.prompt_version,
                    "model_provider": outcome.model_provider,
                    "evidence_snapshot_hash": outcome.evidence_snapshot_hash,
                    "response_hash": outcome.response_hash(),
                    "recommendation": (
                        outcome.recommendation.value
                        if outcome.recommendation else None
                    ),
                },
                reason=outcome.failure_reason,
            )
        return review_id

    async def latest_ai_review(self, *, tenant_id: str, run_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                select * from public.sas_ai_reviews
                 where run_id = $1::uuid and tenant_id = $2
                 order by generated_at desc
                 limit 1
                """,
                run_id, tenant_id,
            )
        return dict(row) if row else None

    # ---------------------------------------------------- human reviews ---

    async def insert_human_review(self, *, record: Any) -> str:
        """Append a governed decision.

        A later review by another authorised reviewer is a NEW record: two
        people disagreeing is information, and overwriting the first opinion
        destroys it.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into public.sas_human_reviews
                    (tenant_id, run_id, actor_type, reviewer_user_id,
                     reviewer_role_key, decision, notes,
                     acknowledgement_version, acknowledgement_text,
                     acknowledgement_hash, evidence_snapshot,
                     evidence_snapshot_hash, ai_review_id,
                     ai_recommendation_at_time)
                values ($1, $2::uuid, 'human', $3, $4,
                        $5::public.oracle_closure_decision, $6, $7, $8, $9,
                        $10, $11, $12::uuid,
                        $13::public.ai_review_recommendation)
                returning id
                """,
                record.tenant_id, record.run_id, record.reviewer_user_id,
                record.reviewer_role_key, record.decision.value, record.notes,
                record.acknowledgement_version, record.acknowledgement_text,
                record.acknowledgement_hash,
                json.dumps(record.evidence_snapshot, default=str),
                record.evidence_snapshot_hash,
                record.ai_review_id,
                record.ai_recommendation_at_time.value
                if record.ai_recommendation_at_time else None,
            )
            review_id = str(row["id"])
            await self._audit(
                conn,
                actor=record.reviewer_user_id,
                action=(
                    ACTION_REVIEW_ACCEPTED
                    if record.decision.value == "oracle_closure_accepted"
                    else ACTION_REVIEW_REJECTED
                ),
                entity_type=ENTITY_HUMAN_REVIEW,
                entity_id=review_id,
                new={
                    "run_id": record.run_id,
                    # Recorded, not inferred: "was this approved by a person"
                    # must be answerable from the audit row alone.
                    "actor_type": "human",
                    "reviewer_role_key": record.reviewer_role_key,
                    "decision": record.decision.value,
                    "evidence_snapshot_hash": record.evidence_snapshot_hash,
                    "acknowledgement_hash": record.acknowledgement_hash,
                    "ai_review_id": record.ai_review_id,
                    "ai_recommendation_at_time": (
                        record.ai_recommendation_at_time.value
                        if record.ai_recommendation_at_time else None
                    ),
                },
                reason=record.notes[:500],
            )
        return review_id

    async def list_human_reviews(
        self, *, tenant_id: str, run_id: str
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, reviewer_user_id, reviewer_role_key, decision,
                       notes, decided_at, evidence_snapshot_hash,
                       ai_review_id, ai_recommendation_at_time
                  from public.sas_human_reviews
                 where run_id = $1::uuid and tenant_id = $2
                 order by decided_at
                """,
                run_id, tenant_id,
            )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------- events ---

    async def record_event(
        self, *, actor: str, action: str, entity_type: str, entity_id: str,
        detail: dict | None = None, reason: str | None = None,
    ) -> None:
        """Audit something that changed no row - a blocked review, a mismatch."""
        async with self._pool.acquire() as conn:
            await self._audit(
                conn,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                new=detail,
                reason=reason,
            )


__all__ = [
    "ACTION_AI_REVIEW_FAILED",
    "ACTION_AI_REVIEW_GENERATED",
    "ACTION_COMPARISON_CREATED",
    "ACTION_HASH_MISMATCH",
    "ACTION_LOG_UPLOADED",
    "ACTION_PACKAGE_DOWNLOADED",
    "ACTION_PACKAGE_GENERATED",
    "ACTION_PARSED",
    "ACTION_RESULT_UPLOADED",
    "ACTION_REVIEW_ACCEPTED",
    "ACTION_REVIEW_BLOCKED",
    "ACTION_REVIEW_REJECTED",
    "AUDIT_ACTIONS",
    "ENTITY_AI_REVIEW",
    "ENTITY_HUMAN_REVIEW",
    "ENTITY_PACKAGE",
    "ENTITY_RUN",
    "PackageNotFound",
    "SASValidationRepository",
]
