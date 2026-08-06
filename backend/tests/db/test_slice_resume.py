"""Does LangGraph actually resume across slices, or quietly replay?

This is the question the whole serverless design rests on, and it cannot be
answered by mocking the checkpointer: what is under test is the LIBRARY's
behaviour when a stream is abandoned part-way and re-entered with `None`. So it
runs the real compiled graph against the real AsyncPostgresSaver on the real
database.

What it does NOT use is the network: the model provider and the literature and
patent providers are the same fakes the unit suite uses. Nothing here costs
money, which is the point - the failure being hunted is precisely one that
costs money and shows no other symptom.

    python tests/db/test_slice_resume.py

The checkpoint rows it creates are deleted afterwards.
"""

import asyncio
import pathlib
import re
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

from app.graph.context import MemoryEventSink, RunContext
from app.graph.graph import build_graph
from app.graph.state import initial_state
from app.worker import open_checkpointer
from tests.fakes import (
    FakeLiteratureProvider,
    FakeModelProvider,
    FakePatentProvider,
)

QUESTION = (
    "Evaluate the feasibility of a sustained-release depot injection of a "
    "therapeutic peptide using a novel delivery technology."
)

passed, failed = 0, 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failed += 1
        print(f"    FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def dsn() -> str:
    env = (pathlib.Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE)
    if not match:
        raise SystemExit("DATABASE_URL is not set.")
    return match.group(1).strip()


def make_context(models: FakeModelProvider) -> RunContext:
    return RunContext(
        models=models,  # type: ignore[arg-type]
        literature_providers=[FakeLiteratureProvider()],
        patent_providers=[FakePatentProvider()],
        events=MemoryEventSink(),
    )


async def stream_until(graph, stream_input, config, *, stop_after: int | None):
    """Advance the graph one super-step at a time, stopping after `stop_after`.

    ABANDONING `astream` DOES NOT WORK, and the first version of this test is
    what proved it. Breaking out of the generator left exactly one row in
    `checkpoints` - `step=-1, source=input` - no matter how many nodes had run.
    LangGraph commits the checkpoint for a step as part of starting the NEXT
    one, so a stream that is dropped mid-flight loses every completed step. The
    47 rows in `checkpoint_writes` were pending writes with no checkpoint to
    anchor them.

    The consequence would have been invisible and expensive: every slice
    restarting from node one, and on a host with a hard timeout, a run that can
    never finish - killed, restarted, killed again.

    `interrupt_after` is the supported way to stop. The graph pauses cleanly at
    the boundary and the checkpoint is durable, so the next call resumes.
    """
    from app.graph.graph import NODE_SEQUENCE

    seen: list[str] = []
    final = None
    payload = stream_input

    while True:
        async for mode, chunk in graph.astream(
            payload,
            config=config,
            stream_mode=["values", "updates"],
            interrupt_after=list(NODE_SEQUENCE),
        ):
            if mode == "updates":
                for node in chunk:
                    if not node.startswith("__"):
                        seen.append(node)
            else:
                final = chunk

        payload = None  # every later pass resumes from the checkpoint

        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            return seen, final, False  # the graph reached the end
        if stop_after is not None and len(seen) >= stop_after:
            return seen, final, True


async def main() -> int:
    thread_id = f"slice-test-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    state = initial_state(
        run_id=thread_id,
        user_id="user-1",
        project_id="project-1",
        original_question=QUESTION,
        max_results=5,
    )

    models_a = FakeModelProvider()
    models_b = FakeModelProvider()

    print(f"\nthread_id: {thread_id}")

    try:
        # ------------------------------------------------- slice 1 ---
        print("\n1. First slice, abandoned after 2 nodes")
        async with open_checkpointer(dsn()) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(make_context(models_a), checkpointer)

            existing = await checkpointer.aget_tuple(config)
            check("no checkpoint exists yet", existing is None)

            seen_1, _, stopped = await stream_until(
                graph, state, config, stop_after=2
            )
            check("stopped early", stopped, f"ran {seen_1}")
            check("a checkpoint was written",
                  await checkpointer.aget_tuple(config) is not None)

        calls_1 = [node for node, _ in models_a.calls]
        print(f"    slice 1 model calls: {calls_1}")

        # Durable per-step checkpoints are the whole mechanism, so assert on
        # them rather than trusting that the resume "looked right".
        diag = await asyncpg.connect(dsn(), statement_cache_size=0)
        try:
            steps = await diag.fetch(
                """
                select metadata::jsonb ->> 'step' as step,
                       metadata::jsonb ->> 'source' as source
                  from public.checkpoints where thread_id = $1
              order by checkpoint_id
                """,
                thread_id,
            )
            print(f"    checkpoints persisted: {[s['step'] for s in steps]}")
            check(
                "a checkpoint exists for each completed step",
                len(steps) >= 3,
                f"{len(steps)} rows",
            )
            check(
                "at least one is a committed loop step, not just the input",
                any(s["source"] == "loop" for s in steps),
                "only source=input would mean nothing was durably saved",
            )
        finally:
            await diag.close()

        # ------------------------------------------------- slice 2 ---
        print("\n2. Second slice, resuming with None")
        async with open_checkpointer(dsn()) as checkpointer:
            graph = build_graph(make_context(models_b), checkpointer)

            resuming = await checkpointer.aget_tuple(config) is not None
            check("the worker would detect a checkpoint", resuming)

            seen_2, final, _ = await stream_until(
                graph, None if resuming else state, config, stop_after=None
            )
            check("the run reached the end", final is not None)

        calls_2 = [node for node, _ in models_b.calls]
        print(f"    slice 2 model calls: {calls_2}")

        # ------------------------------------------- the actual question ---
        print("\n3. Did the second slice replay the first?")
        replayed = sorted(set(calls_1) & set(calls_2))
        check(
            "no node was executed by BOTH slices",
            not replayed,
            f"replayed: {replayed}" if replayed else "none",
        )

        first_nodes = ", ".join(seen_1)
        check(
            "the second slice did not restart at the first node",
            not seen_2 or seen_2[0] != seen_1[0],
            f"slice 1 began at {seen_1[0]}, slice 2 at "
            f"{seen_2[0] if seen_2 else '(nothing)'}",
        )
        print(f"    slice 1 nodes: {first_nodes}")
        print(f"    slice 2 nodes: {', '.join(seen_2)}")

        # A replayed graph would call the model roughly twice over.
        total = len(calls_1) + len(calls_2)
        print(f"\n4. Model calls: {len(calls_1)} + {len(calls_2)} = {total}")
        check(
            "the total is not inflated by re-execution",
            total <= 12,
            f"{total} calls",
        )

        # The report must still be complete despite being built across slices.
        print("\n5. The result survived being split")
        report = (final or {}).get("report")
        sections = getattr(report, "sections", []) or []
        check("a report was produced", len(sections) > 0, f"{len(sections)} sections")
        check(
            "the executive summary survived the split",
            bool(getattr(report, "executive_summary", "")),
        )

    finally:
        conn = await asyncpg.connect(dsn(), statement_cache_size=0)
        try:
            # Table names are literals from this tuple, never caller input, so
            # the interpolation is safe. The value is still bound as $1.
            for statement in (
                "delete from public.checkpoint_writes where thread_id = $1",
                "delete from public.checkpoint_blobs where thread_id = $1",
                "delete from public.checkpoints where thread_id = $1",
            ):
                try:
                    await conn.execute(statement, thread_id)
                except asyncpg.PostgresError:
                    pass
        finally:
            await conn.close()
        print(f"\n    cleaned up checkpoints for {thread_id}")

    print(f"\n{'=' * 62}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'=' * 62}")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
