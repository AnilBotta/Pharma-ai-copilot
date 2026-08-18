"""Database access for uploaded documents and their chunks.

Same rule as `app.repository`: the backend runs under the service role and so
bypasses RLS, which makes the `user_id` filter in each method the real access
control. The policies in 0005 are the second line of defence.
"""

from __future__ import annotations

import logging
from typing import Any

from app.repository import NotFound

logger = logging.getLogger(__name__)

#: A document claimed longer ago than this was interrupted - the host killed the
#: function mid-ingest - and is offered again. Comfortably longer than the 300 s
#: function ceiling, so a slow document in progress is never stolen from a
#: worker that is still working on it.
RECLAIM_AFTER_SECONDS = 900

#: Ingest attempts before a document is failed for good. Three is enough to ride
#: out a transient Storage or embedding error; beyond that the file itself is
#: the problem and retrying forever only spends money.
MAX_INGEST_ATTEMPTS = 3


class DocumentRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ------------------------------------------------------------- writes ---

    async def create(
        self,
        user_id: str,
        *,
        project_id: str | None,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_path: str,
    ) -> dict:
        """Record an intended upload, before the file exists.

        The row is written first so the storage path is owned by a database row
        from the outset. An object in the bucket with no row is unreferenced
        litter nobody will ever look for; a row with no object is visible,
        explainable and cleanable.
        """
        async with self._pool.acquire() as conn:
            if project_id is not None:
                owns = await conn.fetchval(
                    "select 1 from public.projects where id = $1 and user_id = $2",
                    project_id, user_id,
                )
                if not owns:
                    raise NotFound(f"Project {project_id} not found.")

            row = await conn.fetchrow(
                """
                insert into public.documents
                    (user_id, project_id, filename, mime_type, size_bytes,
                     storage_path, status)
                values ($1, $2, $3, $4, $5, $6, 'pending')
                returning *
                """,
                user_id, project_id, filename, mime_type, size_bytes, storage_path,
            )
        return dict(row)

    async def mark_uploaded(self, user_id: str, document_id: str, size_bytes: int) -> dict:
        """Confirm the object landed, and record its true size.

        The size recorded at creation was the browser's claim about a file it
        had not yet sent. This one comes from Storage.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                update public.documents
                   set size_bytes = $3, status = 'pending', error = null
                 where id = $1 and user_id = $2
                returning *
                """,
                document_id, user_id, size_bytes,
            )
        if row is None:
            raise NotFound(f"Document {document_id} not found.")
        return dict(row)

    async def fail(self, document_id: str, message: str) -> None:
        """Record why a document could not be ingested.

        `error` is shown to the user verbatim. A document that failed without
        saying why is the same as one that silently did nothing.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update public.documents
                   set status = 'failed', error = $2, claimed_at = null
                 where id = $1
                """,
                document_id, message,
            )

    # -------------------------------------------------------- the ingest queue ---

    async def claim_next(self) -> dict | None:
        """Take the next document needing work, or None.

        Covers three cases in one statement:

          * `pending`  - never started
          * `extracting` / `embedding` with a stale claim - a worker took it and
            was killed before finishing. Without this branch the row would sit
            in a working state forever while the interface reported progress.

        `for update skip locked` lets concurrent ticks poll the same table
        without blocking or double-claiming, matching `Repository.claim_job`.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                select *
                  from public.documents
                 where storage_path is not null
                   and (
                         (status = 'pending' and claimed_at is null)
                      or (status in ('pending', 'extracting', 'embedding')
                          and claimed_at is not null
                          and claimed_at < now() - interval '{RECLAIM_AFTER_SECONDS} seconds')
                   )
              order by created_at
                 limit 1
                   for update skip locked
                """  # noqa: S608 - interval is a module constant, not user input
            )
            if row is None:
                return None

            claimed = await conn.fetchrow(
                """
                update public.documents
                   set claimed_at = now(),
                       attempts   = attempts + 1,
                       status     = case when status = 'pending' then 'extracting'
                                         else status end
                 where id = $1
                returning *
                """,
                row["id"],
            )
        return dict(claimed)

    async def exhausted(self, document: dict) -> bool:
        """Whether this document has used up its attempts."""
        return int(document.get("attempts") or 0) > MAX_INGEST_ATTEMPTS

    async def release(self, document_id: str) -> None:
        """Give a document back without changing its status.

        Used when a slice runs out of time mid-embedding. The work already done
        is committed; clearing the claim lets the next tick continue rather than
        waiting out the reclaim window.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "update public.documents set claimed_at = null where id = $1",
                document_id,
            )

    # ------------------------------------------------------------- chunks ---

    async def replace_chunks(
        self,
        document_id: str,
        chunks: list[dict],
        *,
        page_count: int | None,
        extracted_chars: int,
    ) -> None:
        """Write the extracted chunks, with no embeddings yet.

        Replaces rather than appends, so a re-extraction after an interrupted
        attempt cannot leave the first attempt's chunks behind alongside the
        second's. Embeddings are filled in later batches; the document becomes
        `ready` only when none are left null.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "delete from public.document_chunks where document_id = $1",
                document_id,
            )
            await conn.executemany(
                """
                insert into public.document_chunks
                    (document_id, chunk_index, content, page_number,
                     section_heading, token_count)
                values ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (
                        document_id,
                        chunk["chunk_index"],
                        chunk["content"],
                        chunk.get("page_number"),
                        chunk.get("section_heading"),
                        chunk.get("token_count"),
                    )
                    for chunk in chunks
                ],
            )
            await conn.execute(
                """
                update public.documents
                   set status = 'embedding', page_count = $2, extracted_chars = $3,
                       error = null
                 where id = $1
                """,
                document_id, page_count, extracted_chars,
            )

    async def next_unembedded(self, document_id: str, limit: int) -> list[dict]:
        """The next batch of chunks still needing a vector."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, chunk_index, content
                  from public.document_chunks
                 where document_id = $1 and embedding is null
              order by chunk_index
                 limit $2
                """,
                document_id, limit,
            )
        return [dict(r) for r in rows]

    async def save_embeddings(self, vectors: dict[str, list[float]]) -> None:
        """Attach vectors to chunks.

        pgvector's text input format is what asyncpg can send without a codec
        registration, and it is exact: these are floats rendered in full, not
        rounded for display.
        """
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                update public.document_chunks
                   set embedding = $2::vector
                 where id = $1
                """,
                [
                    (chunk_id, "[" + ",".join(repr(float(x)) for x in vector) + "]")
                    for chunk_id, vector in vectors.items()
                ],
            )

    async def finish_if_complete(self, document_id: str) -> bool:
        """Mark `ready` when no chunk is missing an embedding.

        Readiness is derived from the data rather than set by whoever thought
        they were finished. A document with one unembedded chunk is not ready,
        however the loop that was filling them terminated.
        """
        async with self._pool.acquire() as conn:
            remaining = await conn.fetchval(
                """
                select count(*) from public.document_chunks
                 where document_id = $1 and embedding is null
                """,
                document_id,
            )
            if remaining:
                return False
            await conn.execute(
                """
                update public.documents
                   set status = 'ready', claimed_at = null, error = null
                 where id = $1
                """,
                document_id,
            )
        return True

    # -------------------------------------------------------------- reads ---

    async def list_for_user(
        self, user_id: str, *, project_id: str | None = None
    ) -> list[dict]:
        query = """
            select d.*,
                   (select count(*) from public.document_chunks c
                     where c.document_id = d.id) as chunk_count,
                   (select count(*) from public.document_chunks c
                     where c.document_id = d.id and c.embedding is null)
                     as pending_chunk_count
              from public.documents d
             where d.user_id = $1
        """
        args: list[Any] = [user_id]
        if project_id:
            args.append(project_id)
            query += f" and d.project_id = ${len(args)}"
        query += " order by d.created_at desc"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]

    async def get(self, user_id: str, document_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.documents where id = $1 and user_id = $2",
                document_id, user_id,
            )
        if row is None:
            raise NotFound(f"Document {document_id} not found.")
        return dict(row)

    async def delete(self, user_id: str, document_id: str) -> str | None:
        """Delete a document, returning its storage path so the object can go too.

        Chunks cascade via the foreign key in 0004.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                delete from public.documents
                 where id = $1 and user_id = $2
                returning storage_path
                """,
                document_id, user_id,
            )
        if row is None:
            raise NotFound(f"Document {document_id} not found.")
        return row["storage_path"]

    # ---------------------------------------------------------- retrieval ---

    async def search_chunks(
        self,
        *,
        project_id: str,
        user_id: str,
        embedding: list[float],
        limit: int,
    ) -> list[dict]:
        """Nearest chunks among a project's ready documents.

        Filtered on `user_id` as well as `project_id`. The project already
        implies the owner, so this is redundant - and it is the kind of
        redundancy worth keeping, because it means a future change to how
        projects are shared cannot silently widen what a run can read.

        `<=>` is cosine distance, matching the operator class the index in 0004
        was built with. Similarity is reported as `1 - distance` so a larger
        number means a closer match, which is what every caller expects.
        """
        vector = "[" + ",".join(repr(float(x)) for x in embedding) + "]"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select c.id, c.document_id, c.chunk_index, c.content,
                       c.page_number, c.section_heading,
                       d.filename, d.mime_type,
                       1 - (c.embedding <=> $3::vector) as similarity
                  from public.document_chunks c
                  join public.documents d on d.id = c.document_id
                 where d.project_id = $1
                   and d.user_id = $2
                   and d.status = 'ready'
                   and c.embedding is not null
              order by c.embedding <=> $3::vector
                 limit $4
                """,
                project_id, user_id, vector, limit,
            )
        return [dict(r) for r in rows]

    async def ready_documents(self, project_id: str, user_id: str) -> list[dict]:
        """Documents a run is entitled to search. Used to report what was consulted."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, filename, page_count
                  from public.documents
                 where project_id = $1 and user_id = $2 and status = 'ready'
              order by created_at
                """,
                project_id, user_id,
            )
        return [dict(r) for r in rows]


__all__ = [
    "MAX_INGEST_ATTEMPTS",
    "RECLAIM_AFTER_SECONDS",
    "DocumentRepository",
]
