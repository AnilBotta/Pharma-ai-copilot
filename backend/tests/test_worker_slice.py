"""Slice execution: the part that makes a serverless host viable.

Three things are worth testing here and one of them matters far more than the
others.

The one that matters is RESUME. A slice that restarts the graph instead of
resuming still produces a correct report, still reports progress, and still
finishes - it just re-runs every completed node and pays for every model call
again. There is no error, no alert, and nothing in the UI to see. Only the bill
and the token counters know. So it gets tested directly.

The others are the authentication on the tick endpoint, which spends money if
left open, and the accounting in release_job, which must not consume a retry
attempt for work that is progressing normally.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

WORKER_SECRET = "worker-secret-long-enough-to-be-real"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / "absent.env")
    for key, value in {
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "OPENAI_API_KEY": "sk-test",
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("WORKER_TRIGGER_SECRET", "PUBLIC_BASE_URL", "WORKER_SLICE_BUDGET_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _client() -> TestClient:
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.state.repository = object()
    return TestClient(app)


# --------------------------------------------------------------------------- #
# The tick endpoint spends money, so it is not left open
# --------------------------------------------------------------------------- #


class TestTickAuthentication:
    def test_disabled_when_no_secret_is_configured(self) -> None:
        """Fail closed. An unset variable must not publish the endpoint."""
        response = _client().post("/api/worker/tick")
        assert response.status_code == 503
        assert "WORKER_TRIGGER_SECRET" in response.json()["detail"]

    @pytest.mark.parametrize(
        "header",
        [None, "", "wrong", WORKER_SECRET + "x", WORKER_SECRET[:-1]],
        ids=["absent", "empty", "wrong", "too-long", "prefix"],
    )
    def test_rejects_anything_but_the_exact_secret(
        self, monkeypatch: pytest.MonkeyPatch, header: str | None
    ) -> None:
        from app.config import get_settings

        monkeypatch.setenv("WORKER_TRIGGER_SECRET", WORKER_SECRET)
        get_settings.cache_clear()

        headers = {} if header is None else {"x-worker-secret": header}
        response = _client().post("/api/worker/tick", headers=headers)
        assert response.status_code == 401

    def test_accepts_the_configured_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.config import get_settings

        monkeypatch.setenv("WORKER_TRIGGER_SECRET", WORKER_SECRET)
        get_settings.cache_clear()

        called: dict[str, Any] = {}

        async def fake_slice(settings, repository, pool):
            called["ran"] = True
            return {"claimed": False, "outcome": "idle"}

        import app.worker as worker_module

        monkeypatch.setattr(worker_module, "run_one_slice", fake_slice)
        monkeypatch.setattr("app.db.get_pool", lambda: object())

        response = _client().post(
            "/api/worker/tick", headers={"x-worker-secret": WORKER_SECRET}
        )
        assert response.status_code == 200
        assert response.json()["outcome"] == "idle"
        assert called["ran"] is True

    def test_no_bearer_token_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The callers are a database scheduler and the deployment itself.

        Neither holds a user session, so requiring one would make the endpoint
        uncallable by the only things meant to call it.
        """
        from app.config import get_settings

        monkeypatch.setenv("WORKER_TRIGGER_SECRET", WORKER_SECRET)
        get_settings.cache_clear()

        async def fake_slice(settings, repository, pool):
            return {"claimed": False, "outcome": "idle"}

        import app.worker as worker_module

        monkeypatch.setattr(worker_module, "run_one_slice", fake_slice)
        monkeypatch.setattr("app.db.get_pool", lambda: object())

        response = _client().post(
            "/api/worker/tick", headers={"x-worker-secret": WORKER_SECRET}
        )
        assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Resume, the failure that costs money silently
# --------------------------------------------------------------------------- #


class FakeCheckpointer:
    """Reports whether a checkpoint exists for a thread."""

    def __init__(self, has_checkpoint: bool) -> None:
        self._has = has_checkpoint

    async def setup(self) -> None:
        return None

    async def aget_tuple(self, config):
        return object() if self._has else None


class GraphSnapshot:
    def __init__(self, next_nodes: tuple[str, ...]) -> None:
        self.next = next_nodes


class RecordingGraph:
    """A double that behaves the way the real graph does under interrupt_after.

    Two properties are modelled deliberately, because getting either wrong in a
    fake would hide the bugs they exist to catch:

    * ``astream`` advances ONE node per call and then returns, which is what
      ``interrupt_after`` produces. A fake that streamed every node in one call
      would make slicing look like it worked when it did not.
    * ``aget_state().next`` reports whether work remains, which is how the
      worker distinguishes "finished" from "paused".

    It also yields LangGraph's ``(mode, data)`` tuples: a full state under
    "values", ``{node_name: delta}`` under "updates".
    """

    def __init__(self, nodes: list[str]) -> None:
        self.nodes = nodes
        self.position = 0
        self.stream_input: Any = "not called"
        self.first_input: Any = "not called"
        self.call_count = 0
        self.interrupt_after: Any = None

    def astream(self, stream_input, config=None, stream_mode=None, interrupt_after=None):
        self.stream_input = stream_input
        if self.call_count == 0:
            self.first_input = stream_input
        self.interrupt_after = interrupt_after
        self.call_count += 1

        node = self.nodes[self.position] if self.position < len(self.nodes) else None
        if node is not None:
            self.position += 1

        async def gen():
            if node is None:
                return
            yield "updates", {node: {}}
            yield "values", {"errors": [], "report": None, "last_node": node}

        return gen()

    async def aget_state(self, config):
        remaining = self.nodes[self.position:]
        return GraphSnapshot((remaining[0],) if remaining else ())


@pytest.fixture
def worker_parts(monkeypatch: pytest.MonkeyPatch):
    """A Worker wired to fakes, plus handles on what it touched."""
    from app.config import get_settings
    from app.worker import Worker

    calls: dict[str, Any] = {
        "released": [], "completed": [], "failed": [], "events": [], "status": [],
    }

    class FakeRepository:
        async def update_run_status(self, run_id, status, **kwargs):
            calls["status"].append((run_id, status, kwargs.get("current_node")))

        async def append_event(self, **kwargs):
            calls["events"].append(kwargs)

        async def save_run_results(self, run_id, state):
            calls["saved"] = state

        async def is_cancel_requested(self, run_id):
            return False

        async def complete_job(self, job_id):
            calls["completed"].append(job_id)

        async def release_job(self, job_id):
            calls["released"].append(job_id)

        async def fail_job(self, job_id, error, **kwargs):
            calls["failed"].append((job_id, error))
            return False

        async def record_usage(self, **kwargs):
            return None

    class FakePool:
        def acquire(self):
            raise AssertionError("The run row is stubbed; no pool access expected.")

    worker = Worker(get_settings(), FakeRepository(), FakePool())

    async def fake_load_run(run_id):
        return {
            "id": run_id,
            "user_id": "u",
            "project_id": "p",
            "original_question": "Is a depot feasible?",
            "jurisdictions": [],
            "max_results": 10,
        }

    monkeypatch.setattr(worker, "_load_run", fake_load_run)
    return worker, calls, monkeypatch


def _install_graph(monkeypatch, graph, *, has_checkpoint: bool):
    import app.worker as worker_module

    @asynccontextmanager
    async def fake_checkpointer(dsn):
        yield FakeCheckpointer(has_checkpoint)

    monkeypatch.setattr(worker_module, "open_checkpointer", fake_checkpointer)
    monkeypatch.setattr(worker_module, "build_graph", lambda ctx, cp: graph)
    monkeypatch.setattr(worker_module, "build_providers", lambda s, c: ([], []))
    monkeypatch.setattr(worker_module, "PostgresCache", lambda pool: object())

    class FakeModels:
        async def aclose(self):
            return None

    monkeypatch.setattr(worker_module, "ModelProvider", lambda *a, **k: FakeModels())


class TestResume:
    """The expensive silent failure."""

    async def test_a_fresh_run_is_given_its_initial_state(self, worker_parts) -> None:
        worker, _calls, monkeypatch = worker_parts
        graph = RecordingGraph(["intake_and_scope"])
        _install_graph(monkeypatch, graph, has_checkpoint=False)

        await worker.execute({"id": "j1", "run_id": "r1", "attempts": 1})

        assert isinstance(graph.first_input, dict), (
            "A run with no checkpoint must start from its initial state."
        )
        assert graph.first_input.get("original_question")
        assert graph.interrupt_after, (
            "Without interrupt_after the graph runs to completion in one call "
            "and the checkpoints for individual steps are never committed."
        )

    async def test_a_checkpointed_run_resumes_instead_of_restarting(
        self, worker_parts
    ) -> None:
        """The one that protects the bill.

        Passing the initial state again re-enters the graph at node one and
        repeats every paid model call already made. LangGraph resumes from the
        checkpoint only when the input is None.
        """
        worker, _calls, monkeypatch = worker_parts
        graph = RecordingGraph(["supervisor_synthesis"])
        _install_graph(monkeypatch, graph, has_checkpoint=True)

        await worker.execute({"id": "j1", "run_id": "r1", "attempts": 2})

        assert graph.first_input is None, (
            "A checkpointed run was restarted rather than resumed. Every "
            "completed node would run again, at full cost, with no error shown."
        )

    async def test_resuming_is_announced(self, worker_parts) -> None:
        worker, calls, monkeypatch = worker_parts
        graph = RecordingGraph(["supervisor_synthesis"])
        _install_graph(monkeypatch, graph, has_checkpoint=True)

        await worker.execute({"id": "j1", "run_id": "r1", "attempts": 2})

        assert any(
            "Resuming" in (e.get("message") or "") for e in calls["events"]
        ), "A user watching progress should see that work continued, not restarted."


class TestSlicing:
    async def test_no_deadline_runs_to_completion(self, worker_parts) -> None:
        worker, calls, monkeypatch = worker_parts
        graph = RecordingGraph(["a", "b", "c"])
        _install_graph(monkeypatch, graph, has_checkpoint=False)

        outcome = await worker.execute({"id": "j1", "run_id": "r1", "attempts": 1})

        assert outcome == "completed"
        assert calls["completed"] == ["j1"]
        assert calls["released"] == []

    async def test_an_expired_budget_releases_the_job_rather_than_failing_it(
        self, worker_parts
    ) -> None:
        worker, calls, monkeypatch = worker_parts
        graph = RecordingGraph(["a", "b", "c"])
        _install_graph(monkeypatch, graph, has_checkpoint=False)

        # Already expired: the first node boundary should end the slice.
        outcome = await worker.execute(
            {"id": "j1", "run_id": "r1", "attempts": 1},
            deadline=time.monotonic() - 1,
        )

        assert outcome == "sliced"
        assert calls["released"] == ["j1"], "A paused run must return to the queue."
        assert calls["failed"] == [], "A pause is not a failure."
        assert calls["completed"] == [], "Nothing finished, so nothing may be marked done."
        assert "saved" not in calls, (
            "Partial state must not be written as if it were the final report."
        )

    async def test_a_slice_always_advances_at_least_one_node(
        self, worker_parts
    ) -> None:
        """Otherwise slices ping-pong forever making no progress.

        If the budget is already spent when the slice starts, stopping before
        any node has run would release the job unchanged, and the next slice
        would do exactly the same.
        """
        worker, calls, monkeypatch = worker_parts
        graph = RecordingGraph(["a", "b"])
        _install_graph(monkeypatch, graph, has_checkpoint=False)

        await worker.execute(
            {"id": "j1", "run_id": "r1", "attempts": 1},
            deadline=time.monotonic() - 100,
        )

        advanced = [s for s in calls["status"] if s[2] is not None]
        assert advanced, "The slice ended without executing a node."

    async def test_a_generous_budget_does_not_slice(self, worker_parts) -> None:
        worker, _calls, monkeypatch = worker_parts
        graph = RecordingGraph(["a", "b"])
        _install_graph(monkeypatch, graph, has_checkpoint=False)

        outcome = await worker.execute(
            {"id": "j1", "run_id": "r1", "attempts": 1},
            deadline=time.monotonic() + 600,
        )
        assert outcome == "completed"


# --------------------------------------------------------------------------- #
# The trigger must never break the thing that calls it
# --------------------------------------------------------------------------- #


class TestTrigger:
    async def test_unconfigured_trigger_is_a_no_op(self) -> None:
        """A long-lived worker polls and needs no trigger. Not an error."""
        from app.config import get_settings
        from app.worker import trigger_tick

        assert await trigger_tick(get_settings()) is False

    async def test_a_read_timeout_counts_as_delivered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The read timeout is the mechanism, not a fault.

        We want the request sent and emphatically do not want to wait for the
        response, which only arrives when the next slice has finished.
        """
        import httpx

        from app.config import get_settings
        from app.worker import trigger_tick

        monkeypatch.setenv("WORKER_TRIGGER_SECRET", WORKER_SECRET)
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test/")
        get_settings.cache_clear()

        class FakeClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def post(self, url, **kwargs):
                assert url == "https://example.test/api/worker/tick", (
                    "The trailing slash on PUBLIC_BASE_URL must not double up."
                )
                assert kwargs["headers"]["x-worker-secret"] == WORKER_SECRET
                raise httpx.ReadTimeout("expected")

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        assert await trigger_tick(get_settings()) is True

    async def test_a_connection_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lost trigger is recoverable; the scheduled sweep catches the job."""
        import httpx

        from app.config import get_settings
        from app.worker import trigger_tick

        monkeypatch.setenv("WORKER_TRIGGER_SECRET", WORKER_SECRET)
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
        get_settings.cache_clear()

        class FakeClient:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def post(self, *a, **k):
                raise httpx.ConnectError("no route")

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        assert await trigger_tick(get_settings()) is False
