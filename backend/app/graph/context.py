"""Runtime dependencies for graph nodes.

Nodes receive a RunContext rather than importing providers or a database
handle directly. That keeps them testable with fakes, and it is what lets the
end-to-end workflow test run the real graph against fixture providers.

The context also owns progress reporting. Every event a node emits becomes a
run_events row, which is what the UI renders - so the interface shows what
actually happened rather than a scripted animation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.provider import ModelProvider
from app.providers.base import LiteratureProvider, PatentProvider

logger = logging.getLogger(__name__)


class EventSink(Protocol):
    """Receives progress events. Backed by run_events in production."""

    async def emit(
        self,
        *,
        run_id: str,
        event_type: str,
        message: str,
        node: str | None = None,
        agent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None: ...


class NullEventSink:
    """Discards events. Used where progress is not being observed."""

    async def emit(self, **kwargs: Any) -> None:
        return None


class MemoryEventSink:
    """Collects events in a list so tests can assert on real progress."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    def messages(self) -> list[str]:
        return [e["message"] for e in self.events]

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("event_type") == event_type]


@dataclass
class RunContext:
    """Everything a node needs that is not part of the state."""

    models: ModelProvider
    literature_providers: list[LiteratureProvider] = field(default_factory=list)
    patent_providers: list[PatentProvider] = field(default_factory=list)
    events: EventSink = field(default_factory=NullEventSink)

    #: Consulted between nodes so a cancel request takes effect promptly
    #: without killing the worker mid-call.
    is_cancelled: Callable[[], Awaitable[bool]] | None = None

    #: Retrieves relevant passages from the user's uploaded documents.
    #: None when document RAG is not configured for this run.
    document_retriever: Any = None

    async def emit(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        node: str | None = None,
        agent_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self.events.emit(
                run_id=run_id,
                event_type=event_type,
                message=message,
                node=node,
                agent_id=agent_id,
                data=data,
            )
        except Exception:
            # Progress reporting must never take down a research run that is
            # otherwise succeeding.
            logger.exception("Failed to emit run event for run %s", run_id)

    async def check_cancelled(self) -> bool:
        if self.is_cancelled is None:
            return False
        try:
            return await self.is_cancelled()
        except Exception:
            logger.exception("Cancellation check failed; assuming not cancelled")
            return False
