"""Ingest: from an object in the bucket to embedded, retrievable chunks.

STAGED SO IT SURVIVES BEING KILLED

Ingest runs inside the worker tick, which the host may terminate at 300 s. The
status machine 0004 defined - pending -> extracting -> embedding -> ready -
already describes two phases, and that is what makes this resumable:

    extract    once, writes every chunk with a NULL embedding
    embed      a bounded batch per pass, until none are left

Each batch is committed as it completes, so an interrupted tick loses one batch
rather than the document, and the next tick continues from where it stopped.
`ready` is set only when a count of unembedded chunks returns zero, which makes
readiness a fact derived from the data instead of a flag set by whichever loop
believed it had finished.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import Settings
from app.documents.chunk import chunk_pages
from app.documents.extract import ExtractionError, extract
from app.documents.repository import DocumentRepository
from app.documents.storage import DocumentStorage, StorageError
from app.llm.provider import LLMError, ModelProvider

logger = logging.getLogger(__name__)

#: Chunks embedded per API call. The embeddings endpoint takes batches happily;
#: this is sized so one call is quick enough that losing it to a timeout costs
#: little, and so a failure retries a small unit of work.
EMBED_BATCH = 64

#: The dimension of `document_chunks.embedding`, fixed by migration 0004 and by
#: the ivfflat index built on it. Changing the embedding model to one of another
#: size is a schema change, not a configuration change.
EMBEDDING_DIMENSIONS = 1536

#: Wall-clock a single ingest pass will spend before handing back. Well inside
#: the 300 s function ceiling, and it leaves room for the research slice that
#: shares the tick.
PASS_BUDGET_SECONDS = 90.0


async def ingest_pending(
    settings: Settings,
    repository: DocumentRepository,
    models: ModelProvider,
    *,
    budget_seconds: float = PASS_BUDGET_SECONDS,
    record_usage: Any = None,
) -> dict[str, Any]:
    """Advance one document as far as the budget allows.

    Returns a summary rather than raising: the caller is the worker tick, whose
    own success is "the tick ran". Every failure that belongs to a document is
    recorded on that document, where the user can see it.
    """
    document = await repository.claim_next()
    if document is None:
        return {"claimed": False}

    document_id = str(document["id"])
    filename = document.get("filename") or document_id

    if await repository.exhausted(document):
        # Its attempts are spent. Failing it here, rather than trying again,
        # is what stops a file that cannot be parsed from being retried on
        # every tick for the rest of the deployment's life.
        message = (
            f"Ingest failed after {document.get('attempts')} attempts. "
            f"{document.get('error') or 'See the previous error.'}"
        )
        await repository.fail(document_id, message)
        return {"claimed": True, "document_id": document_id, "outcome": "exhausted"}

    deadline = time.monotonic() + budget_seconds

    try:
        if document["status"] == "extracting":
            await _extract_phase(settings, repository, document)

        embedded = await _embed_phase(
            repository, models, document_id, deadline=deadline,
            user_id=str(document["user_id"]), record_usage=record_usage,
        )
    except ExtractionError as exc:
        # Expected and explainable: not a readable PDF, password-protected, a
        # scan with no text layer. The message is written for the user.
        await repository.fail(document_id, str(exc))
        logger.info("Document %s failed extraction: %s", document_id, exc)
        return {"claimed": True, "document_id": document_id, "outcome": "failed"}
    except (StorageError, LLMError) as exc:
        # Possibly transient. Leave the status alone so the next tick retries,
        # but record what happened rather than looking like nothing occurred.
        await repository.release(document_id)
        logger.warning("Document %s ingest interrupted: %s", document_id, exc)
        return {"claimed": True, "document_id": document_id, "outcome": "retry"}
    except Exception as exc:
        # Broad on purpose. A bug in this code must not leave the document
        # claimed and silent; it fails visibly, with the reason attached.
        await repository.fail(document_id, f"Unexpected error during ingest: {exc}")
        logger.exception("Document %s ingest raised", document_id)
        return {"claimed": True, "document_id": document_id, "outcome": "failed"}

    if await repository.finish_if_complete(document_id):
        logger.info("Document %s (%s) is ready", document_id, filename)
        return {
            "claimed": True,
            "document_id": document_id,
            "outcome": "ready",
            "embedded": embedded,
        }

    # Out of budget with chunks still unembedded. Hand it back so the next tick
    # continues immediately instead of waiting out the reclaim window.
    await repository.release(document_id)
    return {
        "claimed": True,
        "document_id": document_id,
        "outcome": "continues",
        "embedded": embedded,
    }


async def _extract_phase(
    settings: Settings, repository: DocumentRepository, document: dict
) -> None:
    """Download, extract, chunk, and store chunks without embeddings."""
    storage = DocumentStorage(settings)
    content = await storage.download(document["storage_path"])

    pages = extract(
        content,
        document["mime_type"],
        filename=document.get("filename") or "",
    )
    chunks = chunk_pages(pages)

    if not chunks:
        # Text was extracted but nothing survived chunking - a document of
        # fragments below the minimum useful size. Saying "ready" here would
        # present an empty document as a searchable one.
        raise ExtractionError(
            "Text was extracted but no passage was long enough to be useful. "
            "This document appears to contain only headings or page furniture."
        )

    await repository.replace_chunks(
        str(document["id"]),
        chunks,
        page_count=len(pages),
        extracted_chars=sum(len(p.text) for p in pages),
    )


async def _embed_phase(
    repository: DocumentRepository,
    models: ModelProvider,
    document_id: str,
    *,
    deadline: float,
    user_id: str,
    record_usage: Any,
) -> int:
    """Embed batches until the document is done or the budget is spent."""
    embedded = 0

    while time.monotonic() < deadline:
        batch = await repository.next_unembedded(document_id, EMBED_BATCH)
        if not batch:
            break

        vectors, usage = await models.embed([row["content"] for row in batch])

        if len(vectors) != len(batch):
            raise LLMError(
                f"Embedding returned {len(vectors)} vectors for {len(batch)} chunks."
            )

        # The dimension guard. `document_chunks.embedding` is vector(1536); a
        # model of another size makes every insert fail with a message about
        # vector dimensions, far from the setting that caused it.
        if vectors and len(vectors[0]) != EMBEDDING_DIMENSIONS:
            raise ExtractionError(
                f"OPENAI_EMBEDDING_MODEL produces {len(vectors[0])}-dimension "
                f"vectors, but the database column holds {EMBEDDING_DIMENSIONS}. "
                "Set the embedding model back, or migrate the column and rebuild "
                "every existing document - the two cannot be mixed, because "
                "vectors of different models are not comparable."
            )

        await repository.save_embeddings(
            {str(row["id"]): vector for row, vector in zip(batch, vectors, strict=True)}
        )
        embedded += len(batch)

        if record_usage is not None:
            try:
                await record_usage(
                    run_id=None,
                    user_id=user_id,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    estimated_cost_usd=(
                        float(usage.estimated_cost_usd)
                        if usage.estimated_cost_usd is not None
                        else None
                    ),
                    duration_ms=usage.duration_ms,
                    purpose="document_ingest",
                )
            except Exception:
                # Accounting must never cost a document its embeddings, which
                # have already been paid for and written.
                logger.warning("Could not record ingest usage", exc_info=True)

    return embedded


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EMBED_BATCH",
    "PASS_BUDGET_SECONDS",
    "ingest_pending",
]
