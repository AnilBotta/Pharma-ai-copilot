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
