"""Background worker.

Polls run_jobs, claims one job at a time with ``for update skip locked``, and
executes the research graph. Several workers can run against the same queue
without coordination.

Run it as its own process:

    python -m app.worker

State is checkpointed to Postgres after every node, so a worker that dies
mid-run leaves a resumable run rather than a lost one. Retrying re-enters the
graph at the last completed node instead of repeating paid API calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import uuid
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app import db
from app.config import Settings, get_settings
from app.graph.context import RunContext
from app.graph.graph import build_graph, progress_for
from app.graph.state import initial_state
from app.llm.provider import ModelProvider, Usage
from app.main import configure_logging
from app.providers.cache import PostgresCache
from app.providers.epo_ops import EPOOPSProvider
from app.providers.europepmc import EuropePMCProvider
from app.providers.pubmed import PubMedProvider
from app.repository import Repository

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0


@contextlib.asynccontextmanager
async def open_checkpointer(dsn: str):
    """Checkpointer on a connection that works through a transaction pooler.

    ``AsyncPostgresSaver.from_conn_string`` hardcodes ``prepare_threshold=0``.
    In psycopg that means "prepare every statement on first use", not "never
    prepare" - which is ``None``. Server-side prepared statements are bound to a
    backend connection, and Supabase's transaction pooler hands out a different
    backend per transaction, so the saver fails part-way through a run with

        prepared statement "_pg3_4" does not exist
        prepared statement "_pg3_0" already exists

    depending on which backend it lands on. The errors look like corruption but
    are just statement caching colliding with connection multiplexing.

    The connection is therefore built here with ``prepare_threshold=None``.
    This also matches ``statement_cache_size=0`` on the asyncpg pool in db.py,
    which exists for the same reason.
    """
    async with await AsyncConnection.connect(
        dsn, autocommit=True, prepare_threshold=None, row_factory=dict_row
    ) as conn:
        yield AsyncPostgresSaver(conn=conn)


class RepositoryEventSink:
    """Writes progress events to run_events."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def emit(self, **kwargs: Any) -> None:
        await self._repository.append_event(**kwargs)


def build_providers(settings: Settings, cache: PostgresCache):
    """Construct providers from configuration.

    Unconfigured providers are still constructed. They report
    ``is_configured == False``, which is what lets the run degrade with an
    honest message instead of silently skipping a source.
    """
    literature = [
        PubMedProvider(
            api_key=(
                settings.ncbi_api_key.get_secret_value() if settings.ncbi_api_key else None
            ),
            email=settings.ncbi_email,
            cache=cache,
            cache_ttl=settings.provider_cache_ttl_seconds,
        ),
        EuropePMCProvider(
            cache=cache,
            cache_ttl=settings.provider_cache_ttl_seconds,
            email=settings.crossref_mailto,
        ),
    ]
    patents = [
        EPOOPSProvider(
            consumer_key=(
                settings.epo_ops_consumer_key.get_secret_value()
                if settings.epo_ops_consumer_key
                else None
            ),
            consumer_secret=(
                settings.epo_ops_consumer_secret.get_secret_value()
                if settings.epo_ops_consumer_secret
                else None
            ),
            cache=cache,
            cache_ttl=settings.provider_cache_ttl_seconds,
        )
    ]
    return literature, patents


class Worker:
    def __init__(self, settings: Settings, repository: Repository, pool: Any) -> None:
        self.settings = settings
        self.repository = repository
        self.pool = pool
        self.id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._stopping = asyncio.Event()

    def request_stop(self) -> None:
        logger.info("Stop requested; finishing the current job")
        self._stopping.set()

    async def run_forever(self) -> None:
        logger.info("Worker %s started", self.id)
        while not self._stopping.is_set():
            try:
                job = await self.repository.claim_job(self.id)
            except Exception:
                logger.exception("Failed to claim a job; backing off")
                await asyncio.sleep(POLL_INTERVAL_SECONDS * 5)
                continue

            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=POLL_INTERVAL_SECONDS
                    )
                continue

            await self._execute(job)

        logger.info("Worker %s stopped", self.id)

    async def _execute(self, job: dict) -> None:
        run_id = str(job["run_id"])
        job_id = str(job["id"])
        logger.info("Executing run %s (job %s, attempt %d)", run_id, job_id, job["attempts"])

        cache = PostgresCache(self.pool)
        literature, patents = build_providers(self.settings, cache)

        try:
            run = await self._load_run(run_id)
        except Exception:
            logger.exception("Could not load run %s", run_id)
            await self.repository.fail_job(job_id, "Run row could not be loaded.")
            return

        async def usage_sink(usage: Usage, node: str | None, purpose: str | None) -> None:
            await self.repository.record_usage(
                run_id=run_id,
                user_id=str(run["user_id"]),
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cached_tokens=usage.cached_tokens,
                estimated_cost_usd=(
                    float(usage.estimated_cost_usd)
                    if usage.estimated_cost_usd is not None
                    else None
                ),
                duration_ms=usage.duration_ms,
                node=node,
                purpose=purpose,
            )

        models = ModelProvider(self.settings, usage_sink=usage_sink)
        context = RunContext(
            models=models,
            literature_providers=literature,
            patent_providers=patents,
            events=RepositoryEventSink(self.repository),
            is_cancelled=lambda: self.repository.is_cancel_requested(run_id),
        )

        await self.repository.update_run_status(run_id, "running", progress_pct=0)
        await self.repository.append_event(
            run_id=run_id,
            event_type="run_started",
            message="Research run started.",
        )

        try:
            async with open_checkpointer(str(self.settings.database_url)) as checkpointer:
                await checkpointer.setup()
                graph = build_graph(context, checkpointer)

                # thread_id keys the checkpoint, so a retry of the same run
                # resumes rather than starting over.
                config = {
                    "configurable": {"thread_id": run_id},
                    "recursion_limit": 50,
                }

                final_state = None
                async for chunk in graph.astream(
                    self._initial_state(run), config=config, stream_mode="values"
                ):
                    final_state = chunk
                    node = chunk.get("current_node")
                    if node:
                        await self.repository.update_run_status(
                            run_id, "running",
                            current_node=node, progress_pct=progress_for(node),
                        )

            if final_state is None:
                raise RuntimeError("Graph produced no state.")

            await self.repository.save_run_results(run_id, final_state)

            if await self.repository.is_cancel_requested(run_id):
                await self._finish(run_id, job_id, "cancelled", "Run cancelled by user.")
                return

            fatal = [e for e in final_state.get("errors", []) if e.get("is_fatal")]
            if fatal:
                await self.repository.update_run_status(
                    run_id, "failed", progress_pct=100,
                    error_message=fatal[0]["message"],
                )
                await self.repository.append_event(
                    run_id=run_id, event_type="run_completed",
                    message=f"Run failed: {fatal[0]['message']}",
                )
                await self.repository.complete_job(job_id)
                return

            await self._finish(run_id, job_id, "completed", "Research run complete.")

        except asyncio.CancelledError:
            await self.repository.update_run_status(run_id, "queued")
            raise
        except Exception as exc:
            logger.exception("Run %s failed", run_id)
            will_retry = await self.repository.fail_job(job_id, str(exc))
            await self.repository.append_event(
                run_id=run_id,
                event_type="error",
                message=(
                    f"Run failed: {exc}. "
                    + ("It will be retried." if will_retry else "No retries remain.")
                ),
            )
            if not will_retry:
                await self.repository.update_run_status(
                    run_id, "failed", error_message=str(exc)[:1000]
                )
        finally:
            for provider in (*literature, *patents):
                with contextlib.suppress(Exception):
                    await provider.aclose()
            with contextlib.suppress(Exception):
                await models.aclose()

    async def _finish(self, run_id: str, job_id: str, status: str, message: str) -> None:
        await self.repository.update_run_status(run_id, status, progress_pct=100)
        await self.repository.append_event(
            run_id=run_id, event_type="run_completed", message=message
        )
        await self.repository.complete_job(job_id)
        logger.info("Run %s %s", run_id, status)

    async def _load_run(self, run_id: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.research_runs where id = $1", run_id
            )
        if row is None:
            raise LookupError(f"Run {run_id} not found.")
        return dict(row)

    @staticmethod
    def _initial_state(run: dict):
        return initial_state(
            run_id=str(run["id"]),
            user_id=str(run["user_id"]),
            project_id=str(run["project_id"]),
            original_question=run["original_question"],
            molecule=run.get("molecule"),
            indication=run.get("indication"),
            dosage_form=run.get("dosage_form"),
            route_of_administration=run.get("route_of_administration"),
            delivery_technology=run.get("delivery_technology"),
            development_stage=run.get("development_stage"),
            jurisdictions=list(run.get("jurisdictions") or []),
            date_from=run.get("date_from"),
            date_to=run.get("date_to"),
            max_results=run.get("max_results") or 50,
            additional_instructions=run.get("additional_instructions"),
        )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    pool = await db.create_pool(settings)
    worker = Worker(settings, Repository(pool), pool)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            # Windows does not support add_signal_handler for these.
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run_forever()
    finally:
        await db.close_pool()


def _configure_event_loop() -> None:
    """Use a selector event loop on Windows.

    LangGraph's AsyncPostgresSaver talks to Postgres through psycopg, which
    cannot run in async mode on the ProactorEventLoop that Python selects by
    default on Windows. Without this every run fails at checkpointer setup with

        psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'

    which is fatal but easy to misread as a connection problem, because it only
    surfaces once a job is actually claimed.

    The selector loop caps out around 512 sockets. A worker executes one run at
    a time against a handful of hosts, so that limit is not a constraint here.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    _configure_event_loop()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
