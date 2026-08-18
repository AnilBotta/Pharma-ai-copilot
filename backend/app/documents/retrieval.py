"""Retrieval over a project's uploaded documents.

This is what fills the `document_retriever` slot that `RunContext` has held
open since the graph was built. It is scoped to one project and one user for the
lifetime of a run, so no caller can widen what a run is allowed to read by
passing a different id.
"""

from __future__ import annotations

import logging

from app.documents.repository import DocumentRepository
from app.llm.provider import ModelProvider

logger = logging.getLogger(__name__)

#: Below this cosine similarity a passage is not about the question, and
#: including it would put irrelevant internal material in front of the model as
#: though it were responsive. Retrieval always returns its nearest neighbours -
#: nearest is not the same as relevant, and on a small corpus the difference is
#: the whole problem.
MIN_SIMILARITY = 0.25


class DocumentRetriever:
    """Nearest-passage search over one project's ready documents."""

    def __init__(
        self,
        repository: DocumentRepository,
        models: ModelProvider,
        *,
        project_id: str,
        user_id: str,
        document_count: int = 0,
    ) -> None:
        self._repository = repository
        self._models = models
        self._project_id = project_id
        self._user_id = user_id
        self.document_count = document_count

    @classmethod
    async def for_run(
        cls,
        repository: DocumentRepository,
        models: ModelProvider,
        *,
        project_id: str,
        user_id: str,
    ) -> DocumentRetriever | None:
        """Build a retriever, or None when the project has no ready documents.

        Returning None rather than an empty retriever lets the node skip
        silently. A project with no uploads is the ordinary case, and a report
        that announces "no internal documents were searched" on every run is
        noise that teaches people to stop reading warnings.
        """
        ready = await repository.ready_documents(project_id, user_id)
        if not ready:
            return None
        return cls(
            repository,
            models,
            project_id=project_id,
            user_id=user_id,
            document_count=len(ready),
        )

    async def search(self, query: str, *, limit: int = 12) -> list[dict]:
        """Passages closest to `query`, nearest first.

        Raises rather than returning nothing on failure. A retrieval error and
        an empty corpus produce identical output otherwise, and the node needs
        to tell the user which happened.
        """
        vectors, _usage = await self._models.embed([query])
        if not vectors:
            return []

        rows = await self._repository.search_chunks(
            project_id=self._project_id,
            user_id=self._user_id,
            embedding=vectors[0],
            limit=limit,
        )

        kept = [r for r in rows if (r.get("similarity") or 0) >= MIN_SIMILARITY]
        if len(kept) < len(rows):
            logger.debug(
                "Dropped %d passage(s) below the similarity floor",
                len(rows) - len(kept),
            )
        return kept


__all__ = ["MIN_SIMILARITY", "DocumentRetriever"]
