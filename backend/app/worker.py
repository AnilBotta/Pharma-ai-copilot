"""Background worker.

Claims one job at a time from run_jobs with ``for update skip locked`` and
executes the research graph. Several workers can run against the same queue
without coordination.

TWO WAYS TO RUN IT

*As a long-lived process* - polls until stopped:

    python -m app.worker

*As a slice* - executes for a bounded time and hands the rest to the next
invocation. This is what makes a serverless host viable, where a function is
killed at a fixed ceiling (300 s on Vercel Hobby, and unraisable) while a real
research run takes about 785 s.

Slicing costs almost nothing to add because the mechanism already existed for
another reason: state is checkpointed to Postgres after every node, so a worker
that dies mid-run leaves a resumable run rather than a lost one. A slice is that
same resume performed on purpose.

WHAT THE BUDGET ACTUALLY MEANS

``worker_slice_budget_seconds`` gates whether the loop takes on ANOTHER node; a
node already running is always allowed to finish. Worst case is therefore
``budget + longest_node``, and it is that sum which has to fit the host's
timeout - not the budget alone. Measured on a real run, the longest single node
visit is ~120 s, so a 150 s budget lands at ~280 s against a 300 s ceiling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import time
import uuid
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app import db
from app.config import Settings, get_settings
from app.graph.context import RunContext
from app.graph.graph import NODE_SEQUENCE, build_graph, progress_for
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

            # No deadline: a long-lived process runs a job to completion.
            await self.execute(job)

        logger.info("Worker %s stopped", self.id)

    async def execute(self, job: dict, *, deadline: float | None = None) -> str:
        """Run a job, optionally stopping at ``deadline`` (a monotonic time).

        Returns the outcome: ``completed``, ``failed``, ``cancelled``, or
        ``sliced`` when it stopped early with the run still resumable.
        """
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
            return "failed"

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

        # Uploaded documents are searched per project, so the retriever is bound
        # to this run's project and owner and cannot be pointed elsewhere. It is
        # None when the project has no ready documents, which is the ordinary
        # case and is why the node stays silent rather than reporting an absence
        # in every report.
        try:
            from app.documents.repository import DocumentRepository
            from app.documents.retrieval import DocumentRetriever

            retriever = await DocumentRetriever.for_run(
                DocumentRepository(self.pool),
                models,
                project_id=str(run["project_id"]),
                user_id=str(run["user_id"]),
            )
        except Exception:
            # A run must not fail because internal documents could not be
            # listed. It proceeds on external evidence, which is the same
            # degradation a missing patent provider gets.
            logger.warning("Could not prepare document retrieval", exc_info=True)
            retriever = None

        context = RunContext(
            models=models,
            literature_providers=literature,
            patent_providers=patents,
            events=RepositoryEventSink(self.repository),
            is_cancelled=lambda: self.repository.is_cancel_requested(run_id),
            document_retriever=retriever,
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

                # RESUME, DO NOT RESTART.
                #
                # Passing the initial state again would re-enter the graph at
                # the beginning and repeat every node - and every paid API call
                # - that a previous slice already completed. LangGraph resumes
                # from the checkpoint when the input is None, so the presence of
                # a checkpoint for this thread decides which we pass. Getting
                # this wrong is silent: the run still finishes, it just costs
                # several times as much and reports invented progress.
                resuming = await checkpointer.aget_tuple(config) is not None
                if resuming:
                    logger.info("Resuming run %s from its checkpoint", run_id)
                    await self.repository.append_event(
                        run_id=run_id,
                        event_type="node_started",
                        message="Resuming from the last completed step.",
                    )

                final_state = None
                sliced = False
                nodes_this_slice = 0
                previous_node: str | None = None
                payload = None if resuming else self._initial_state(run)

                # ONE SUPER-STEP PER astream CALL, PAUSED BY interrupt_after.
                #
                # The obvious implementation - stream everything and `break` out
                # of the loop when the budget runs out - silently does not work,
                # and a test against the real checkpointer is what showed it.
                # After abandoning a stream part-way through, `checkpoints` held
                # exactly one row: `step=-1, source=input`. LangGraph commits a
                # step's checkpoint as part of beginning the NEXT step, so a
                # dropped stream loses every node that had completed. The
                # pending rows in `checkpoint_writes` had no checkpoint to
                # anchor them.
                #
                # Nothing about that would have been visible in the UI. Each
                # slice would restart at node one, and on a host that kills a
                # function at a fixed ceiling the run could never finish:
                # killed, restarted, killed again, forever, paying for every
                # model call each time.
                #
                # `interrupt_after` pauses the graph the way the library intends
                # - cleanly, with the checkpoint durable - so the next call
                # genuinely resumes. Verified in tests/db/test_slice_resume.py:
                # a run split across two slices executes each node exactly once
                # and makes the same number of model calls as an unsplit one.
                #
                # The two stream modes serve different needs. `values` carries
                # the accumulated state, which is what gets saved at the end.
                # `updates` names the node that just ran, and that name comes
                # from the graph itself. This code previously read a
                # `current_node` key out of the state, which nothing ever wrote:
                # `research_runs.current_node` was null for every run ever
                # executed and `progress_pct` never moved off 0 until the run
                # finished. Progress only appeared to work because the UI polls
                # `run_events`, which the nodes populate themselves.
                while True:
                    before = nodes_this_slice

                    async for mode, chunk in graph.astream(
                        payload,
                        config=config,
                        stream_mode=["values", "updates"],
                        interrupt_after=list(NODE_SEQUENCE),
                    ):
                        if mode == "values":
                            final_state = chunk
                            continue

                        # mode == "updates": {node_name: state_delta}
                        for node in chunk:
                            if node.startswith("__"):  # __start__, __end__
                                continue
                            previous_node = node
                            nodes_this_slice += 1
                            await self.repository.update_run_status(
                                run_id, "running",
                                current_node=node, progress_pct=progress_for(node),
                            )

                    payload = None  # every later pass resumes from the checkpoint

                    snapshot = await graph.aget_state(config)
                    if not snapshot.next:
                        break  # the graph reached the end

                    if nodes_this_slice == before:
                        # A pass that advanced nothing would spin forever.
                        raise RuntimeError(
                            "The graph made no progress but reports work "
                            f"remaining at {snapshot.next}."
                        )

                    # Stop only at a node boundary, and only once this slice has
                    # actually advanced something. Without the progress check a
                    # slice whose budget was already spent on startup would
                    # release the job having done nothing, and the run would
                    # ping-pong between invocations forever.
                    if deadline is not None and time.monotonic() >= deadline:
                        sliced = True
                        break

            if sliced:
                await self.repository.release_job(job_id)
                await self.repository.append_event(
                    run_id=run_id,
                    event_type="node_completed",
                    message=(
                        f"Paused after {nodes_this_slice} step(s); another worker "
                        "will continue from here."
                    ),
                    node=previous_node,
                )
                logger.info(
                    "Run %s sliced after %d node(s) at %s",
                    run_id, nodes_this_slice, previous_node,
                )
                return "sliced"

            if final_state is None:
                raise RuntimeError("Graph produced no state.")

            await self.repository.save_run_results(run_id, final_state)

            if await self.repository.is_cancel_requested(run_id):
                await self._finish(run_id, job_id, "cancelled", "Run cancelled by user.")
                return "cancelled"

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
                return "failed"

            await self._finish(run_id, job_id, "completed", "Research run complete.")
            return "completed"

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
            return "failed"
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


# --------------------------------------------------------------------------- #
# Slice execution, for hosts that kill long invocations
# --------------------------------------------------------------------------- #


async def run_one_slice(
    settings: Settings, repository: Repository, pool: Any
) -> dict[str, Any]:
    """Claim one job and work on it until the slice budget is spent.

    Returns a small summary rather than raising, because the caller is an HTTP
    endpoint whose own success is "the tick ran", not "the research finished".
    """
    worker = Worker(settings, repository, pool)

    job = await repository.claim_job(worker.id)
    if job is None:
        return {"claimed": False, "outcome": "idle"}

    budget = settings.worker_slice_budget_seconds
    deadline = time.monotonic() + budget if budget > 0 else None

    started = time.monotonic()
    outcome = await worker.execute(job, deadline=deadline)

    return {
        "claimed": True,
        "run_id": str(job["run_id"]),
        "outcome": outcome,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        # True means work remains and the caller should trigger a successor.
        "continues": outcome == "sliced",
    }


async def trigger_tick(settings: Settings) -> bool:
    """Ask the deployment to run a worker tick. Fire and forget.

    The read timeout is deliberately tiny and the resulting timeout is
    swallowed. We want the request *delivered* - which happens on connect and
    write - and emphatically do not want to wait for the response, because the
    response only arrives when that whole slice has finished, minutes later.
    Awaiting it would hold this invocation open for the duration of the next
    one, which on a host that bills by wall-clock is the expensive way to
    deadlock.

    Returns whether the request was sent, not whether the work succeeded.
    """
    if not settings.public_base_url or not settings.worker_trigger_secret:
        # Nothing to call, or nothing to authenticate with. A long-lived worker
        # polls and needs neither, so this is a normal state, not an error.
        return False

    import httpx

    url = f"{settings.public_base_url}/api/worker/tick"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, write=5.0, read=0.25, pool=5.0)
        ) as client:
            await client.post(
                url,
                headers={
                    "x-worker-secret": settings.worker_trigger_secret.get_secret_value()
                },
                json={},
            )
    except httpx.ReadTimeout:
        return True  # delivered; we simply did not wait for the answer
    except Exception as exc:
        # A lost trigger is recoverable: the scheduled sweep picks the job up
        # within a minute. Worth a log line, not worth failing the caller.
        logger.warning("Could not trigger a worker tick at %s: %s", url, exc)
        return False
    return True


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
