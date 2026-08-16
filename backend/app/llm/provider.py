"""OpenAI model provider.

Uses the Responses API (``client.responses.parse``) with Pydantic-typed
structured output. The deprecated Assistants API is not used anywhere.

No model name is hardcoded. Callers select a *role* - supervision, research,
extraction, synthesis, verification - and the concrete model for that role comes
from configuration, so a deployment can put a cheap model behind extraction and
a strong one behind synthesis without touching code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)


class ModelRole(StrEnum):
    """What a call is for. Maps to a configured model, not a fixed one."""

    SUPERVISOR = "supervisor"
    RESEARCH = "research"
    EXTRACTION = "extraction"
    SYNTHESIS = "synthesis"
    VERIFICATION = "verification"


class LLMError(Exception):
    """A model call that could not be completed."""

    error_type = "model_error"


class LLMTimeout(LLMError):
    error_type = "timeout"


class LLMValidationError(LLMError):
    """The model returned output that did not satisfy the requested schema."""

    error_type = "validation"


@dataclass
class Usage:
    """Token accounting for one call."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    duration_ms: int = 0
    #: None when the model has no configured pricing. Never a guess.
    estimated_cost_usd: Decimal | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StructuredResult[T: BaseModel]:
    """A validated model response plus its cost."""

    output: T
    usage: Usage
    #: Populated when the model was asked to repair malformed output.
    repaired: bool = False
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Tool-loop events
#
# The loop is an async generator so an SSE endpoint can forward these straight
# to the browser. They are plain dataclasses rather than dicts so that adding a
# field is a type error at every consumer instead of a silently missing key.
# --------------------------------------------------------------------------- #


@dataclass
class TextDelta:
    """A fragment of the model's prose, as it arrives."""

    text: str


@dataclass
class ToolStarted:
    name: str
    arguments: dict


@dataclass
class ToolFinished:
    name: str
    #: False when the tool raised. The failure was handed back to the model,
    #: not swallowed - see the loop.
    ok: bool
    result: Any


@dataclass
class LoopFinished:
    """The model stopped calling tools and produced an answer."""

    text: str
    usage: Usage


@dataclass
class LoopTruncated:
    """A limit was reached first. Never dressed up as an answer."""

    reason: str
    detail: str


def _add_usage(total: Usage, one: Usage) -> Usage:
    """Accumulate across tool-loop iterations."""
    cost = total.estimated_cost_usd
    if one.estimated_cost_usd is not None:
        cost = (cost or Decimal(0)) + one.estimated_cost_usd
    return Usage(
        model=total.model,
        input_tokens=total.input_tokens + one.input_tokens,
        output_tokens=total.output_tokens + one.output_tokens,
        reasoning_tokens=total.reasoning_tokens + one.reasoning_tokens,
        cached_tokens=total.cached_tokens + one.cached_tokens,
        duration_ms=total.duration_ms + one.duration_ms,
        estimated_cost_usd=cost,
    )


class ModelProvider:
    """Reusable OpenAI client with retries, cost tracking and typed output.

    A single instance is shared for a process. ``usage_sink`` is an optional
    callback invoked after every call so the graph can persist a usage_records
    row without this module needing to know about the database.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        usage_sink: Callable[[Usage, str | None, str | None], Awaitable[None]] | None = None,
        client: Any = None,
    ) -> None:
        self._settings = settings
        self._usage_sink = usage_sink
        self._client = client or openai.AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            # Retries are handled here rather than by the SDK so that failures
            # are logged and counted consistently with provider adapters.
            max_retries=0,
        )

    def model_for(self, role: ModelRole) -> str:
        return {
            ModelRole.SUPERVISOR: self._settings.openai_model_supervisor,
            ModelRole.RESEARCH: self._settings.openai_model_research,
            ModelRole.EXTRACTION: self._settings.openai_model_extraction,
            ModelRole.SYNTHESIS: self._settings.openai_model_synthesis,
            ModelRole.VERIFICATION: self._settings.openai_model_verification,
        }[role]

    # ------------------------------------------------------------- structured ---

    async def complete_structured[T: BaseModel](
        self,
        *,
        role: ModelRole,
        schema: type[T],
        instructions: str,
        user_input: str,
        max_output_tokens: int | None = None,
        node: str | None = None,
        purpose: str | None = None,
    ) -> StructuredResult[T]:
        """Call the model and return output validated against ``schema``.

        Raises LLMError if the call cannot be completed, or LLMValidationError
        if the model will not produce schema-conforming output. Neither is
        swallowed: a node that cannot get structured output must fail loudly
        rather than proceed with a half-formed result.
        """
        model = self.model_for(role)
        started = time.monotonic()

        response = await self._call_with_retries(
            model=model,
            schema=schema,
            instructions=instructions,
            user_input=user_input,
            max_output_tokens=max_output_tokens,
        )

        usage = self._extract_usage(model, response, started)
        if self._usage_sink:
            await self._usage_sink(usage, node, purpose)

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise LLMValidationError(
                f"{model} returned no parseable output for schema {schema.__name__}. "
                f"Response status: {getattr(response, 'status', 'unknown')}."
            )

        warnings = []
        if getattr(response, "status", None) == "incomplete":
            detail = getattr(response, "incomplete_details", None)
            reason = getattr(detail, "reason", "unknown") if detail else "unknown"
            warnings.append(
                f"Model output was truncated ({reason}); this section may be incomplete."
            )

        return StructuredResult(output=parsed, usage=usage, warnings=warnings)

    async def _call_with_retries[T: BaseModel](
        self,
        *,
        model: str,
        schema: type[T],
        instructions: str,
        user_input: str,
        max_output_tokens: int | None,
    ) -> Any:
        attempts = max(1, self._settings.openai_max_retries)
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "instructions": instructions,
                    "input": user_input,
                    "text_format": schema,
                }
                if max_output_tokens:
                    kwargs["max_output_tokens"] = max_output_tokens
                return await self._client.responses.parse(**kwargs)

            except openai.APITimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Model call timed out (attempt %d/%d, model=%s)",
                    attempt + 1,
                    attempts,
                    model,
                )
                if attempt == attempts - 1:
                    raise LLMTimeout(
                        f"{model} did not respond within "
                        f"{self._settings.openai_timeout_seconds}s after {attempts} attempts."
                    ) from exc

            except openai.RateLimitError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise LLMError(
                        f"{model} rate limit reached after {attempts} attempts."
                    ) from exc

            except openai.APIStatusError as exc:
                # 4xx other than 429 will not improve on retry.
                if exc.status_code < 500 and exc.status_code != 429:
                    raise LLMError(
                        f"{model} rejected the request ({exc.status_code}). "
                        f"This usually indicates a configuration problem."
                    ) from exc
                last_error = exc
                if attempt == attempts - 1:
                    raise LLMError(
                        f"{model} failed with status {exc.status_code} after "
                        f"{attempts} attempts."
                    ) from exc

            except ValidationError as exc:
                # The model produced JSON that does not satisfy the schema.
                last_error = exc
                logger.warning(
                    "Schema validation failed for %s (attempt %d/%d)",
                    schema.__name__,
                    attempt + 1,
                    attempts,
                )
                if attempt == attempts - 1:
                    raise LLMValidationError(
                        f"{model} could not produce output matching "
                        f"{schema.__name__} after {attempts} attempts."
                    ) from exc

            except openai.APIConnectionError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise LLMError(f"Could not reach the OpenAI API: {exc}.") from exc

            await asyncio.sleep(min(0.5 * (2**attempt), 8.0))

        raise LLMError(f"{model} call failed: {last_error}")

    # ------------------------------------------------------------------ usage ---

    def _extract_usage(self, model: str, response: Any, started: float) -> Usage:
        duration_ms = int((time.monotonic() - started) * 1000)
        raw = getattr(response, "usage", None)
        if raw is None:
            return Usage(model=model, duration_ms=duration_ms)

        output_details = getattr(raw, "output_tokens_details", None)
        input_details = getattr(raw, "input_tokens_details", None)

        usage = Usage(
            model=model,
            input_tokens=getattr(raw, "input_tokens", 0) or 0,
            output_tokens=getattr(raw, "output_tokens", 0) or 0,
            reasoning_tokens=getattr(output_details, "reasoning_tokens", 0) or 0,
            cached_tokens=getattr(input_details, "cached_tokens", 0) or 0,
            duration_ms=duration_ms,
        )
        usage.estimated_cost_usd = estimate_cost(
            model, usage.input_tokens, usage.output_tokens, usage.cached_tokens
        )
        return usage

    # -------------------------------------------------------------- tool loop ---

    async def complete_with_tools(
        self,
        *,
        role: ModelRole,
        instructions: str,
        conversation: list[dict],
        tools: list[dict],
        execute: Callable[[str, dict], Awaitable[Any]],
        max_iterations: int = 8,
        deadline: float | None = None,
        max_total_tokens: int | None = None,
        purpose: str | None = None,
    ) -> Any:
        """Run a streaming tool-calling conversation, yielding events as it goes.

        An async generator rather than a coroutine returning a result, because
        the caller is an SSE endpoint: a chat turn that reads six tables before
        it can answer should say so while it happens, not go silent for forty
        seconds and then produce a paragraph.

        BOUNDED THREE WAYS, DELIBERATELY

        ``max_iterations`` caps tool round-trips, ``deadline`` caps wall clock,
        and ``max_total_tokens`` caps spend. A tool loop is the one place in
        this codebase where a prompt bug costs money on every cycle rather than
        once, and where the model itself decides how many cycles there are. All
        three limits are hit rarely and all three are cheap; the absence of any
        one of them is the expensive kind of oversight.

        Reaching a limit yields ``LoopTruncated`` and stops. It never fabricates
        a conclusion the model did not reach, because a truncated answer
        presented as a complete one is worse than an obvious refusal.
        """
        model = self.model_for(role)
        # Copied: the caller's transcript is theirs, and the loop appends the
        # model's own function calls and their results to this working list.
        working: list[dict] = list(conversation)
        totals = Usage(model=model)

        for _iteration in range(max_iterations):
            if deadline is not None and time.monotonic() >= deadline:
                yield LoopTruncated(
                    reason="time",
                    detail=(
                        "This turn ran out of time before the answer was "
                        "finished. Nothing above is a conclusion."
                    ),
                )
                return
            if max_total_tokens is not None and totals.total_tokens >= max_total_tokens:
                yield LoopTruncated(
                    reason="tokens",
                    detail=(
                        f"This turn reached its {max_total_tokens:,} token budget "
                        "before the answer was finished."
                    ),
                )
                return

            started = time.monotonic()
            text_parts: list[str] = []
            calls: list[dict] = []
            raw_response: Any = None

            stream = await self._client.responses.create(
                model=model,
                instructions=instructions,
                input=working,
                tools=tools,
                stream=True,
            )

            async for event in stream:
                kind = getattr(event, "type", "")

                if kind == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        text_parts.append(delta)
                        yield TextDelta(text=delta)

                elif kind == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", None) == "function_call":
                        calls.append(
                            {
                                "type": "function_call",
                                "call_id": getattr(item, "call_id", ""),
                                "name": getattr(item, "name", ""),
                                "arguments": getattr(item, "arguments", "") or "{}",
                            }
                        )

                elif kind == "response.completed":
                    raw_response = getattr(event, "response", None)

                elif kind in ("response.failed", "error"):
                    raise LLMError(
                        f"{model} failed mid-stream: "
                        f"{getattr(event, 'message', None) or kind}."
                    )

            usage = self._extract_usage(model, raw_response, started)
            totals = _add_usage(totals, usage)
            if self._usage_sink:
                await self._usage_sink(usage, "manager_agent", purpose)

            # No tool calls means the model considers itself finished.
            if not calls:
                yield LoopFinished(text="".join(text_parts), usage=totals)
                return

            working.extend(calls)

            for call in calls:
                try:
                    arguments = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                yield ToolStarted(name=call["name"], arguments=arguments)

                # A failing tool is reported BACK TO THE MODEL rather than
                # raised. A gate id that does not exist, or a project the
                # caller cannot see, is information the model can act on -
                # it can apologise, or try the right id. Killing the turn
                # would turn a recoverable mistake into a dead end.
                try:
                    result = await execute(call["name"], arguments)
                    ok, payload = True, result
                except Exception as exc:
                    logger.warning(
                        "Manager tool %s failed: %s", call["name"], exc, exc_info=True
                    )
                    ok, payload = False, {"error": str(exc)[:500]}

                yield ToolFinished(name=call["name"], ok=ok, result=payload)

                working.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": json.dumps(payload, default=str)[:60_000],
                    }
                )

        yield LoopTruncated(
            reason="iterations",
            detail=(
                f"This turn used all {max_iterations} of its tool steps without "
                "reaching an answer."
            ),
        )

    # -------------------------------------------------------------- embeddings ---

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], Usage]:
        """Embed a batch of texts for document retrieval."""
        if not texts:
            return [], Usage(model=self._settings.openai_embedding_model)

        model = self._settings.openai_embedding_model
        started = time.monotonic()
        try:
            response = await self._client.embeddings.create(model=model, input=texts)
        except openai.APIError as exc:
            raise LLMError(f"Embedding call to {model} failed: {exc}") from exc

        vectors = [item.embedding for item in response.data]
        raw = getattr(response, "usage", None)
        usage = Usage(
            model=model,
            input_tokens=getattr(raw, "prompt_tokens", 0) or 0,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        usage.estimated_cost_usd = estimate_cost(model, usage.input_tokens, 0)
        return vectors, usage

    async def health_check(self) -> tuple[bool, str]:
        """Confirm the API key works and the configured models exist.

        Verifying the model list matters because a typo in
        OPENAI_MODEL_SYNTHESIS would otherwise surface as a mid-run failure
        after real money had already been spent on earlier nodes.
        """
        try:
            listing = await self._client.models.list()
        except openai.AuthenticationError:
            return False, "OPENAI_API_KEY was rejected."
        except openai.APIError as exc:
            return False, f"Could not reach the OpenAI API: {exc}."

        available = {m.id for m in listing.data}
        configured = {self.model_for(role) for role in ModelRole}
        configured.add(self._settings.openai_embedding_model)

        missing = sorted(
            name
            for name in configured
            if name not in available and not any(a.startswith(name) for a in available)
        )
        if missing:
            return False, f"Configured models unavailable to this key: {', '.join(missing)}."
        return True, f"Authenticated; {len(configured)} configured models available."

    async def aclose(self) -> None:
        await self._client.close()
