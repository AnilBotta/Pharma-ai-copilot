"""The Manager Agent's tool loop, against a faked transport.

What is actually being tested is the loop's *restraint*. A tool loop is the one
place in this codebase where the model decides how many paid calls to make, so
the interesting cases are all about it being stopped: by iteration count, by the
clock, by the token budget - and about a failing tool being handed back rather
than ending the turn.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from app.llm.provider import (
    LoopFinished,
    LoopTruncated,
    ModelProvider,
    ModelRole,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from app.manager import docs, tools
from tests.test_llm import make_settings

# --------------------------------------------------------------------------- #
# A fake Responses-API stream
# --------------------------------------------------------------------------- #


@dataclass
class _Event:
    type: str
    delta: str = ""
    item: Any = None
    response: Any = None


@dataclass
class _FunctionCall:
    call_id: str
    name: str
    arguments: str
    type: str = "function_call"


class _Usage:
    input_tokens = 1000
    output_tokens = 200
    output_tokens_details = None
    input_tokens_details = None


class _Response:
    usage = _Usage()
    status = "completed"


class _Stream:
    def __init__(self, events: list[_Event]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self._events:
            yield event


class FakeResponses:
    """Plays back scripted turns, one per `create` call."""

    def __init__(self, turns: list[list[_Event]]) -> None:
        self._turns = turns
        self.calls: list[dict] = []

    async def create(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._turns) - 1)
        return _Stream(self._turns[index])


class FakeClient:
    def __init__(self, turns: list[list[_Event]]) -> None:
        self.responses = FakeResponses(turns)

    async def close(self) -> None:
        return None


def _text_turn(text: str) -> list[_Event]:
    return [
        _Event("response.output_text.delta", delta=text),
        _Event("response.completed", response=_Response()),
    ]


def _tool_turn(name: str, arguments: str = "{}", call_id: str = "c1") -> list[_Event]:
    return [
        _Event(
            "response.output_item.done",
            item=_FunctionCall(call_id=call_id, name=name, arguments=arguments),
        ),
        _Event("response.completed", response=_Response()),
    ]


def _provider(settings, turns: list[list[_Event]]) -> ModelProvider:
    return ModelProvider(settings, client=FakeClient(turns))


async def _drain(gen) -> list[Any]:
    return [event async for event in gen]


# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_turn_with_no_tool_calls_finishes_immediately():
    settings = make_settings()
    provider = _provider(settings, [_text_turn("Gate 1 cannot open.")])

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[{"role": "user", "content": "status?"}],
            tools=[],
            execute=_unused_execute,
        )
    )

    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], LoopFinished)
    assert events[-1].text == "Gate 1 cannot open."
    assert provider._client.responses.calls.__len__() == 1


@pytest.mark.asyncio
async def test_a_tool_call_is_executed_and_fed_back():
    settings = make_settings()
    provider = _provider(
        settings,
        [_tool_turn("get_gate", '{"stage_id": "abc"}'), _text_turn("Two blockers.")],
    )
    seen: list[tuple[str, dict]] = []

    async def execute(name: str, arguments: dict) -> Any:
        seen.append((name, arguments))
        return {"blocker_count": 2}

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
        )
    )

    assert seen == [("get_gate", {"stage_id": "abc"})]
    assert any(isinstance(e, ToolStarted) for e in events)
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished and finished[0].ok is True
    assert isinstance(events[-1], LoopFinished)

    # The second call must carry the function call AND its output, or the model
    # has no idea what it just asked for.
    second = provider._client.responses.calls[1]["input"]
    assert any(item.get("type") == "function_call" for item in second)
    assert any(item.get("type") == "function_call_output" for item in second)


@pytest.mark.asyncio
async def test_a_failing_tool_is_reported_to_the_model_not_raised():
    settings = make_settings()
    provider = _provider(
        settings, [_tool_turn("get_gate"), _text_turn("I could not read that gate.")]
    )

    async def execute(name: str, arguments: dict) -> Any:
        raise ValueError("Gate 9f2 not found.")

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
        )
    )

    failed = [e for e in events if isinstance(e, ToolFinished)]
    assert failed and failed[0].ok is False
    # The turn survives and the model gets a chance to say something useful.
    assert isinstance(events[-1], LoopFinished)

    output = [
        item
        for item in provider._client.responses.calls[1]["input"]
        if item.get("type") == "function_call_output"
    ]
    assert "Gate 9f2 not found." in output[0]["output"]


@pytest.mark.asyncio
async def test_the_iteration_cap_stops_a_model_that_never_stops_calling():
    settings = make_settings()
    # Every scripted turn asks for another tool call; only the cap ends this.
    provider = _provider(settings, [_tool_turn("list_programmes")])

    async def execute(name: str, arguments: dict) -> Any:
        return {"ok": True}

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
            max_iterations=3,
        )
    )

    assert isinstance(events[-1], LoopTruncated)
    assert events[-1].reason == "iterations"
    assert len(provider._client.responses.calls) == 3


@pytest.mark.asyncio
async def test_an_expired_deadline_stops_the_loop_before_spending_anything():
    settings = make_settings()
    provider = _provider(settings, [_text_turn("never reached")])

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=_unused_execute,
            deadline=time.monotonic() - 1,
        )
    )

    assert isinstance(events[0], LoopTruncated)
    assert events[0].reason == "time"
    assert provider._client.responses.calls == []


@pytest.mark.asyncio
async def test_the_token_budget_stops_the_loop():
    settings = make_settings()
    provider = _provider(settings, [_tool_turn("list_programmes")])

    async def execute(name: str, arguments: dict) -> Any:
        return {}

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
            # One scripted turn spends 1,200 tokens, so the second is refused.
            max_total_tokens=1_000,
            max_iterations=8,
        )
    )

    assert isinstance(events[-1], LoopTruncated)
    assert events[-1].reason == "tokens"
    assert len(provider._client.responses.calls) == 1


@pytest.mark.asyncio
async def test_truncation_is_never_dressed_up_as_an_answer():
    settings = make_settings()
    """A limit must not produce a LoopFinished. The distinction is the point."""
    provider = _provider(settings, [_tool_turn("list_programmes")])

    async def execute(name: str, arguments: dict) -> Any:
        return {}

    events = await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
            max_iterations=2,
        )
    )

    assert not any(isinstance(e, LoopFinished) for e in events)


@pytest.mark.asyncio
async def test_usage_is_reported_once_per_model_call():
    """Every iteration of the loop must reach the usage sink.

    This was wrong once in a way nothing caught: the loop called the sink
    correctly, but the route constructed ModelProvider without one, so six
    chat turns spent money and recorded none of it. The provider half is
    locked here; the wiring is asserted by reading usage_records after a live
    turn, because a unit test cannot see a constructor argument that was never
    passed.
    """
    recorded: list[tuple[str, str | None, str | None]] = []

    async def sink(usage: Any, node: str | None, purpose: str | None) -> None:
        recorded.append((usage.model, node, purpose))

    provider = ModelProvider(
        make_settings(),
        usage_sink=sink,
        client=FakeClient([_tool_turn("list_programmes"), _text_turn("done")]),
    )

    async def execute(name: str, arguments: dict) -> Any:
        return {}

    await _drain(
        provider.complete_with_tools(
            role=ModelRole.SUPERVISOR,
            instructions="x",
            conversation=[],
            tools=[],
            execute=execute,
            purpose="manager_chat",
        )
    )

    # Two model calls: the one that asked for a tool, and the one that answered.
    assert len(recorded) == 2
    assert {r[1] for r in recorded} == {"manager_agent"}
    assert {r[2] for r in recorded} == {"manager_chat"}


# ------------------------------------------------------------------ dispatch ---
#
# Two limits here are enforced in code rather than in the prompt, because they
# are the two that cost money. An instruction not to spend is exactly the kind
# a long enough conversation talks its way past.


def _ctx(**overrides: Any) -> tools.ToolContext:
    base = dict(
        user_id="u1",
        pdp=None,
        core=None,
        pool=None,
        settings=None,
        models=None,
    )
    base.update(overrides)
    return tools.ToolContext(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_gate_assessment_is_refused_late_in_a_turn():
    # Started far enough in the past that a minute-long assessment would risk
    # being killed with the work half done and paid for.
    ctx = _ctx(started=time.monotonic() - (tools.ASSESS_LATEST_START_SECONDS + 30))

    result = await tools._assess_gate(ctx, stage_id="whatever")

    assert result["started"] is False
    assert "on its own" in result["reason"]


@pytest.mark.asyncio
async def test_only_one_research_run_may_be_started_per_turn():
    created: list[dict] = []

    class Core:
        async def create_run(self, user_id: str, project_id: str, payload: dict) -> dict:
            created.append(payload)
            return {"id": f"run-{len(created)}"}

    ctx = _ctx(core=Core(), settings=make_settings())

    first = await tools._start_research_run(
        ctx, project_id="p1", question="What are the stability risks?"
    )
    second = await tools._start_research_run(
        ctx, project_id="p1", question="And the manufacturing ones?"
    )

    assert first["queued"] is True
    assert second["queued"] is False
    assert "already been started" in second["reason"]
    assert len(created) == 1, "the second call must not reach the database"


@pytest.mark.asyncio
async def test_max_results_is_clamped_rather_than_trusted():
    captured: list[dict] = []

    class Core:
        async def create_run(self, user_id: str, project_id: str, payload: dict) -> dict:
            captured.append(payload)
            return {"id": "run-1"}

    ctx = _ctx(core=Core(), settings=make_settings())
    await tools._start_research_run(
        ctx, project_id="p1", question="q", max_results=5000
    )

    assert captured[0]["max_results"] == 25


def test_the_three_kinds_of_tool_stay_distinguishable():
    """Reads, dispatch and writes are three lists, and nothing is in two.

    The lists are what the panel styles from and what a reader of this module
    uses to answer "what can this thing change". A tool drifting between them,
    or appearing in none, is how a write ends up presented as a read.
    """
    dispatch = {t.name for t in tools.DISPATCH_TOOLS}
    writes = {t.name for t in tools.WRITE_TOOLS}
    reads = {t.name for t in tools.READ_TOOLS}

    assert dispatch == {"assess_gate", "start_research_run", "sweep_notifications"}
    assert not (reads & dispatch) and not (reads & writes) and not (dispatch & writes)
    assert reads | dispatch | writes == set(tools.registry())
    assert len(tools.schemas()) == len(reads) + len(dispatch) + len(writes)


def test_every_tool_schema_is_well_formed():
    for tool in tools.ALL_TOOLS:
        schema = tool.schema()
        assert schema["type"] == "function"
        assert schema["name"] and schema["description"]
        params = schema["parameters"]
        assert params["type"] == "object"
        # Required names must actually be declared, or the model is being told
        # to send a field the schema does not describe.
        assert set(params["required"]) <= set(params["properties"])


# --------------------------------------------------------------- docs search ---


def test_docs_search_finds_the_governance_rule_not_just_any_page():
    hits = docs.search("why can I not approve a requirement myself")
    assert hits, "the segregation-of-duties question must match something"
    headings = " ".join(h["heading"].lower() for h in hits)
    assert "who may do what" in headings or "the one rule" in headings


def test_docs_search_distinguishes_the_two_readiness_numbers():
    hits = docs.search("readiness percentage is_ready gate")
    assert hits
    assert any("two numbers" in h["heading"].lower() for h in hits)


def test_docs_search_returns_nothing_rather_than_a_bad_match():
    # The agent is instructed to say the documentation does not cover it. That
    # only works if an unrelated query genuinely returns empty.
    assert docs.search("cornbread recipe hummingbird") == []
    assert docs.search("") == []


async def _unused_execute(name: str, arguments: dict) -> Any:  # pragma: no cover
    raise AssertionError("no tool should have been called")
