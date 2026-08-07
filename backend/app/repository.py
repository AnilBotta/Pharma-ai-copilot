"""Database access for runs, evidence, reports and observability.

Every method that reads user data takes a ``user_id`` and filters on it. The
backend uses the service role, which bypasses RLS, so this is the real access
control; the RLS policies are a second line of defence for anything that
reaches the database by another route.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.graph.state import ResearchState
from app.models.records import LiteratureRecord, PatentRecord

logger = logging.getLogger(__name__)


class NotFound(Exception):
    """Requested row does not exist, or is not owned by this user.

    Deliberately does not distinguish the two. Telling a caller that a run
    exists but belongs to someone else leaks its existence.
    """


class Repository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ----------------------------------------------------------- projects ---

    async def list_projects(self, user_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select p.*,
                       (select count(*) from public.research_runs r
                         where r.project_id = p.id) as run_count
                  from public.projects p
                 where p.user_id = $1
              order by p.created_at desc
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def create_project(
        self,
        user_id: str,
        *,
        name: str,
        description: str | None = None,
        code: str | None = None,
        molecule: str | None = None,
        indication: str | None = None,
        is_seed: bool = False,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into public.projects
                    (user_id, name, description, code, molecule, indication, is_seed)
                values ($1, $2, $3, $4, $5, $6, $7)
                returning *
                """,
                user_id, name, description, code, molecule, indication, is_seed,
            )
        return dict(row)

    async def get_project(self, user_id: str, project_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.projects where id = $1 and user_id = $2",
                project_id, user_id,
            )
        if row is None:
            raise NotFound(f"Project {project_id} not found.")
        return dict(row)

    # --------------------------------------------------------------- runs ---

    async def create_run(self, user_id: str, project_id: str, payload: dict) -> dict:
        """Create the run and enqueue its job in one transaction.

        Both or neither: a run with no job would sit queued forever, and a job
        with no run would fail on pickup.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            owns = await conn.fetchval(
                "select 1 from public.projects where id = $1 and user_id = $2",
                project_id, user_id,
            )
            if not owns:
                raise NotFound(f"Project {project_id} not found.")

            row = await conn.fetchrow(
                """
                insert into public.research_runs (
                    project_id, user_id, original_question, molecule, indication,
                    dosage_form, route_of_administration, delivery_technology,
                    development_stage, jurisdictions, date_from, date_to,
                    max_results, additional_instructions
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                returning *
                """,
                project_id,
                user_id,
                payload["original_question"],
                payload.get("molecule"),
                payload.get("indication"),
                payload.get("dosage_form"),
                payload.get("route_of_administration"),
                payload.get("delivery_technology"),
                payload.get("development_stage"),
                payload.get("jurisdictions") or [],
                payload.get("date_from"),
                payload.get("date_to"),
                payload.get("max_results", 50),
                payload.get("additional_instructions"),
            )
            await conn.execute(
                "insert into public.run_jobs (run_id) values ($1)", row["id"]
            )
        return dict(row)

    async def get_run(self, user_id: str, run_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
        if row is None:
            raise NotFound(f"Run {run_id} not found.")
        return dict(row)

    async def list_runs(
        self, user_id: str, *, project_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        query = """
            select r.*, p.name as project_name,
                   (select count(*) from public.evidence_records e
                     where e.run_id = r.id) as evidence_count
              from public.research_runs r
              join public.projects p on p.id = r.project_id
             where r.user_id = $1
        """
        args: list[Any] = [user_id]
        if project_id:
            args.append(project_id)
            query += f" and r.project_id = ${len(args)}"
        # Bound as a parameter rather than interpolated: even though the caller
        # is int-typed and the API layer bounds it, a query built by string
        # concatenation is one refactor away from being unsafe.
        args.append(limit)
        query += f" order by r.created_at desc limit ${len(args)}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        current_node: str | None = None,
        progress_pct: int | None = None,
        error_message: str | None = None,
    ) -> None:
        sets = ["status = $2"]
        args: list[Any] = [run_id, status]

        if current_node is not None:
            args.append(current_node)
            sets.append(f"current_node = ${len(args)}")
        if progress_pct is not None:
            args.append(progress_pct)
            sets.append(f"progress_pct = ${len(args)}")
        if error_message is not None:
            args.append(error_message)
            sets.append(f"error_message = ${len(args)}")
        if status == "running":
            sets.append("started_at = coalesce(started_at, now())")
        if status in ("completed", "failed", "cancelled"):
            sets.append("completed_at = now()")

        # `sets` contains only literals defined above; every caller-supplied
        # value is bound as a positional parameter. Interpolation here is over
        # the column list, never over data.
        statement = f"update public.research_runs set {', '.join(sets)} where id = $1"  # noqa: S608

        async with self._pool.acquire() as conn:
            await conn.execute(statement, *args)

    async def request_cancel(self, user_id: str, run_id: str) -> None:
        async with self._pool.acquire() as conn:
            updated = await conn.execute(
                """
                update public.research_runs
                   set cancel_requested = true
                 where id = $1 and user_id = $2
                   and status in ('queued', 'running')
                """,
                run_id, user_id,
            )
        if updated.endswith("0"):
            raise NotFound(f"Run {run_id} is not cancellable.")

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with self._pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    "select cancel_requested from public.research_runs where id = $1",
                    run_id,
                )
            )

    async def retry_run(self, user_id: str, run_id: str) -> None:
        """Re-enqueue a failed or cancelled run.

        Existing evidence and checkpoints are left in place: the graph resumes
        from its last checkpoint rather than repeating paid API calls.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            run = await conn.fetchrow(
                "select status from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if run is None:
                raise NotFound(f"Run {run_id} not found.")
            if run["status"] not in ("failed", "cancelled"):
                raise ValueError(f"Run is {run['status']}; only failed or cancelled runs retry.")

            await conn.execute(
                """
                update public.research_runs
                   set status = 'queued', cancel_requested = false,
                       error_message = null, completed_at = null
                 where id = $1
                """,
                run_id,
            )
            await conn.execute(
                """
                insert into public.run_jobs (run_id, status, available_at)
                values ($1, 'queued', now())
                """,
                run_id,
            )

    # ------------------------------------------------------------- events ---

    async def append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        message: str,
        node: str | None = None,
        agent_id: str | None = None,
        data: dict | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into public.run_events (run_id, node, agent_id, event_type, message, data)
                values ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                run_id, node, agent_id, event_type, message,
                json.dumps(data, default=str) if data else None,
            )

    async def get_events(
        self, user_id: str, run_id: str, *, after_id: int = 0, limit: int = 500
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            owns = await conn.fetchval(
                "select 1 from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if not owns:
                raise NotFound(f"Run {run_id} not found.")
            rows = await conn.fetch(
                """
                select * from public.run_events
                 where run_id = $1 and id > $2
              order by id asc limit $3
                """,
                run_id, after_id, limit,
            )
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- evidence ---

    async def save_run_results(self, run_id: str, state: ResearchState) -> None:
        """Persist everything a completed run produced, in one transaction.

        Written together so a partially saved run cannot appear complete: a
        report whose references are missing would be worse than no report.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await self._save_search_queries(conn, run_id, state)
            lit_ids = await self._save_literature(conn, run_id, state)
            pat_ids = await self._save_patents(conn, run_id, state)
            await self._save_evidence(conn, run_id, state, lit_ids, pat_ids)
            await self._save_report(conn, run_id, state)
            await self._save_errors(conn, run_id, state)
            await self._save_run_summary(conn, run_id, state)

    async def _save_search_queries(self, conn, run_id: str, state: ResearchState) -> None:
        for query in state.get("search_queries", []):
            await conn.execute(
                """
                insert into public.search_queries
                    (run_id, node, provider, query_text, result_count,
                     from_cache, duration_ms, status, error)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                run_id, query.get("node"), query["provider"], query["query_text"],
                query.get("result_count"), query.get("from_cache", False),
                query.get("duration_ms"), query.get("status", "ok"), query.get("error"),
            )

    async def _save_literature(
        self, conn, run_id: str, state: ResearchState
    ) -> dict[str, str]:
        """Insert publications, returning a map from identifier to row id."""
        ids: dict[str, str] = {}
        for record in state.get("literature_results", []):
            if not isinstance(record, LiteratureRecord):
                record = LiteratureRecord.model_validate(record)
            row_id = await conn.fetchval(
                """
                insert into public.literature_records (
                    run_id, provider, title, abstract, authors, journal,
                    publication_date, publication_year, doi, pmid, pmcid, url,
                    publication_types, is_preprint, is_open_access,
                    has_full_text, full_text
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                returning id
                """,
                run_id, record.provider, record.title, record.abstract,
                record.authors, record.journal, record.publication_date,
                record.publication_year, record.doi, record.pmid, record.pmcid,
                record.best_url, record.publication_types, record.is_preprint,
                record.is_open_access, record.has_full_text, record.full_text,
            )
            for key in filter(None, (record.doi, record.pmid, record.pmcid, record.best_url)):
                ids[key] = str(row_id)
        return ids

    async def _save_patents(self, conn, run_id: str, state: ResearchState) -> dict[str, str]:
        ids: dict[str, str] = {}
        for record in state.get("patent_results", []):
            if not isinstance(record, PatentRecord):
                record = PatentRecord.model_validate(record)
            row_id = await conn.fetchval(
                """
                insert into public.patent_records (
                    run_id, provider, title, abstract, publication_number,
                    application_number, family_id, kind_code, jurisdiction,
                    record_type, priority_date, filing_date, publication_date,
                    applicants, inventors, cpc_classifications,
                    ipc_classifications, legal_status, url
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                on conflict (run_id, publication_number) do update
                    set title = excluded.title
                returning id
                """,
                run_id, record.provider, record.title, record.abstract,
                record.publication_number, record.application_number,
                record.family_id, record.kind_code, record.jurisdiction,
                record.record_type.value, record.priority_date, record.filing_date,
                record.publication_date, record.applicants, record.inventors,
                record.cpc_classifications, record.ipc_classifications,
                record.legal_status, record.best_url,
            )
            ids[record.publication_number] = str(row_id)
        return ids

    async def _save_evidence(
        self,
        conn,
        run_id: str,
        state: ResearchState,
        lit_ids: dict[str, str],
        pat_ids: dict[str, str],
    ) -> None:
        for entry in state.get("evidence_records", []):
            identifier = entry.get("identifier")
            await conn.execute(
                """
                insert into public.evidence_records (
                    run_id, marker, source_type, provider, title, authors,
                    identifier_type, identifier, publication_date, url,
                    retrieved_text, access_level, evidence_category,
                    relevance_score, retrieved_by_agent,
                    literature_record_id, patent_record_id
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                on conflict (run_id, marker) do nothing
                """,
                run_id, entry["marker"], entry["source_type"], entry["provider"],
                entry["title"], entry.get("authors") or [],
                entry.get("identifier_type"), identifier,
                _as_date(entry.get("publication_date")), entry.get("url"),
                entry.get("retrieved_text"), entry["access_level"],
                entry.get("evidence_category"), entry.get("relevance_score"),
                entry["retrieved_by_agent"],
                lit_ids.get(identifier or ""), pat_ids.get(identifier or ""),
            )

    async def _save_report(self, conn, run_id: str, state: ResearchState) -> None:
        report = state.get("report")
        if report is None:
            return

        confidence = state.get("section_confidence", {})
        for position, section in enumerate(report.sections):
            section_id = await conn.fetchval(
                """
                insert into public.report_sections
                    (run_id, section_key, position, title, body_markdown, confidence)
                values ($1,$2,$3,$4,$5,$6)
                on conflict (run_id, section_key) do update
                    set body_markdown = excluded.body_markdown,
                        confidence = excluded.confidence,
                        position = excluded.position
                returning id
                """,
                run_id, section.section_key, position, section.title,
                section.body_markdown, confidence.get(section.section_key),
            )

            # Link each cited marker to its evidence row.
            from app.llm.citations import extract_markers

            for marker in extract_markers(section.body_markdown):
                evidence_id = await conn.fetchval(
                    "select id from public.evidence_records where run_id = $1 and marker = $2",
                    run_id, marker,
                )
                if evidence_id is None:
                    # Should be impossible: report_generation strips these.
                    logger.warning("Marker %s in report has no evidence row", marker)
                    continue
                await conn.execute(
                    """
                    insert into public.citations
                        (run_id, report_section_id, evidence_id, marker, verified)
                    values ($1,$2,$3,$4,true)
                    on conflict (report_section_id, evidence_id) do nothing
                    """,
                    run_id, section_id, evidence_id, marker,
                )

    async def _save_errors(self, conn, run_id: str, state: ResearchState) -> None:
        for error in state.get("errors", []):
            await conn.execute(
                """
                insert into public.run_errors
                    (run_id, node, provider, error_type, message, is_fatal)
                values ($1,$2,$3,$4,$5,$6)
                """,
                run_id, error.get("node"), error.get("provider"),
                error.get("error_type", "unknown"), error["message"],
                error.get("is_fatal", False),
            )

    async def _save_run_summary(self, conn, run_id: str, state: ResearchState) -> None:
        await conn.execute(
            """
            update public.research_runs set
                structured_objective = $2::jsonb,
                research_plan = $3::jsonb,
                contradictions = $4::jsonb,
                evidence_gaps = $5::jsonb,
                warnings = $6::jsonb,
                section_confidence = $7::jsonb
             where id = $1
            """,
            run_id,
            _dump_model(state.get("structured_objective")),
            _dump_model(state.get("research_plan")),
            json.dumps(state.get("contradictions", [])),
            json.dumps(state.get("evidence_gaps", [])),
            json.dumps(state.get("warnings", [])),
            json.dumps(state.get("section_confidence", {})),
        )

    async def get_evidence(self, user_id: str, run_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            owns = await conn.fetchval(
                "select 1 from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if not owns:
                raise NotFound(f"Run {run_id} not found.")
            rows = await conn.fetch(
                """
                select e.*,
                       coalesce(
                         array_agg(distinct s.section_key)
                           filter (where s.section_key is not null),
                         '{}'
                       ) as cited_in_sections
                  from public.evidence_records e
                  left join public.citations c on c.evidence_id = e.id
                  left join public.report_sections s on s.id = c.report_section_id
                 where e.run_id = $1
              group by e.id
              order by e.marker
                """,
                run_id,
            )
        return [dict(r) for r in rows]

    async def get_report(self, user_id: str, run_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            owns = await conn.fetchval(
                "select 1 from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if not owns:
                raise NotFound(f"Run {run_id} not found.")
            rows = await conn.fetch(
                "select * from public.report_sections where run_id = $1 order by position",
                run_id,
            )
        return [dict(r) for r in rows]

    async def get_search_queries(self, user_id: str, run_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            owns = await conn.fetchval(
                "select 1 from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if not owns:
                raise NotFound(f"Run {run_id} not found.")
            rows = await conn.fetch(
                "select * from public.search_queries where run_id = $1 order by created_at",
                run_id,
            )
        return [dict(r) for r in rows]

    async def get_run_errors(self, user_id: str, run_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            owns = await conn.fetchval(
                "select 1 from public.research_runs where id = $1 and user_id = $2",
                run_id, user_id,
            )
            if not owns:
                raise NotFound(f"Run {run_id} not found.")
            rows = await conn.fetch(
                "select * from public.run_errors where run_id = $1 order by created_at",
                run_id,
            )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------- usage ---

    async def record_usage(
        self,
        *,
        run_id: str | None,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        cached_tokens: int = 0,
        estimated_cost_usd: float | None = None,
        duration_ms: int | None = None,
        node: str | None = None,
        purpose: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                insert into public.usage_records (
                    run_id, user_id, node, purpose, model, input_tokens,
                    output_tokens, reasoning_tokens, cached_tokens,
                    estimated_cost_usd, duration_ms
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                run_id, user_id, node, purpose, model, input_tokens,
                output_tokens, reasoning_tokens, cached_tokens,
                estimated_cost_usd or 0, duration_ms,
            )
            if run_id:
                await conn.execute(
                    """
                    update public.research_runs
                       set total_input_tokens = total_input_tokens + $2,
                           total_output_tokens = total_output_tokens + $3,
                           estimated_cost_usd = estimated_cost_usd + $4
                     where id = $1
                    """,
                    run_id, input_tokens, output_tokens, estimated_cost_usd or 0,
                )

    async def dashboard_summary(self, user_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                select
                  count(*) filter (where status = 'running')   as running,
                  count(*) filter (where status = 'queued')    as queued,
                  count(*) filter (where status = 'completed') as completed,
                  count(*) filter (where status = 'failed')    as failed,
                  count(*)                                     as total_runs,
                  coalesce(sum(estimated_cost_usd), 0)         as total_cost,
                  coalesce(sum(total_input_tokens + total_output_tokens), 0) as total_tokens
                  from public.research_runs where user_id = $1
                """,
                user_id,
            )
            sources = await conn.fetchrow(
                """
                select
                  count(*) filter (where source_type = 'literature') as literature,
                  count(*) filter (where source_type = 'patent')     as patents
                  from public.evidence_records e
                  join public.research_runs r on r.id = e.run_id
                 where r.user_id = $1
                """,
                user_id,
            )
        return {**dict(row), "source_counts": dict(sources)}

    # --------------------------------------------------------- job queue ---

    async def claim_job(self, worker_id: str) -> dict | None:
        """Claim one queued job.

        ``for update skip locked`` lets several workers poll the same table
        without any of them blocking or double-claiming.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                select j.id, j.run_id, j.attempts, j.max_attempts
                  from public.run_jobs j
                  join public.research_runs r on r.id = j.run_id
                 where j.status = 'queued'
                   and j.available_at <= now()
                   and r.cancel_requested = false
              order by j.created_at
                 limit 1
                   for update of j skip locked
                """
            )
            if row is None:
                return None
            await conn.execute(
                """
                update public.run_jobs
                   set status = 'claimed', claimed_by = $2,
                       claimed_at = now(), attempts = attempts + 1
                 where id = $1
                """,
                row["id"], worker_id,
            )
        return dict(row)

    async def complete_job(self, job_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "update public.run_jobs set status = 'done' where id = $1", job_id
            )

    async def release_job(self, job_id: str) -> None:
        """Return a partially executed job to the queue for its next slice.

        Distinct from :meth:`fail_job` in one way that matters: the attempt
        counter is decremented back, because ``claim_job`` incremented it and a
        deliberate pause is not a failed attempt. Without this a run needing
        more slices than ``max_attempts`` would be marked failed for making
        normal progress -- the retry budget exists to stop a *broken* run
        looping, not to cap how long a working one may take.

        The run's own status is left as ``running``: from a user's point of view
        nothing has stopped.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update public.run_jobs
                   set status = 'queued',
                       claimed_by = null,
                       claimed_at = null,
                       attempts = greatest(attempts - 1, 0),
                       available_at = now()
                 where id = $1
                """,
                job_id,
            )

    async def fail_job(self, job_id: str, error: str, *, retry_in_seconds: int = 60) -> bool:
        """Mark a job failed. Returns True if it will be retried."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select attempts, max_attempts from public.run_jobs where id = $1", job_id
            )
            if row is None:
                return False
            will_retry = row["attempts"] < row["max_attempts"]
            await conn.execute(
                """
                update public.run_jobs
                   set status = $2, last_error = $3,
                       available_at = now() + make_interval(secs => $4)
                 where id = $1
                """,
                job_id,
                "queued" if will_retry else "failed",
                error[:2000],
                float(retry_in_seconds) if will_retry else 0.0,
            )
        return will_retry


def _dump_model(model: Any) -> str | None:
    if model is None:
        return None
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json()
    return json.dumps(model, default=str)


def _as_date(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return value
