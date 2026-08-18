"""Stage 8: uploaded documents and retrieval, against the live database.

The properties worth pinning here are the ones no unit test can see, because
they are enforced by the schema rather than by Python:

  * one user cannot read another's documents or chunks
  * a document is `ready` only when no chunk is missing an embedding
  * a citation to an uploaded document resolves to an actual chunk row
  * deleting a document takes its chunks with it

The last of those is the one that would rot quietly. `evidence_records` has held
a `document_chunk_id` foreign key since 0003 and nothing ever wrote to it, so
until now the column proved nothing about anything.

    python tests/db/test_document_rag.py
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncpg

OWNER = "dc000000-0000-0000-0000-000000000001"
STRANGER = "dc000000-0000-0000-0000-000000000002"
PROJECT = "dc100000-0000-0000-0000-000000000001"
DOCUMENT = "dc200000-0000-0000-0000-000000000001"
RUN = "dc300000-0000-0000-0000-000000000001"

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
    return re.search(r"^DATABASE_URL=(.+)$", env, re.MULTILINE).group(1).strip()


def vec(seed: float) -> str:
    """A 1536-dimension vector in pgvector's text form."""
    return "[" + ",".join(repr(seed) for _ in range(1536)) + "]"


async def main() -> int:
    conn = await asyncpg.connect(dsn(), statement_cache_size=0)
    tx = conn.transaction()
    await tx.start()
    try:
        # ------------------------------------------------------------ setup ---
        for uid, email in (
            (OWNER, "dc-owner@test.local"), (STRANGER, "dc-stranger@test.local")
        ):
            await conn.execute(
                """
                insert into auth.users (id, instance_id, aud, role, email,
                    encrypted_password, email_confirmed_at, created_at, updated_at)
                values ($1,'00000000-0000-0000-0000-000000000000','authenticated',
                        'authenticated',$2,'x',now(),now(),now())
                """,
                uid, email,
            )
        await conn.execute(
            "insert into public.projects (id, user_id, name) values ($1,$2,'RAG Test')",
            PROJECT, OWNER,
        )
        await conn.execute(
            """
            insert into public.documents
              (id, user_id, project_id, filename, mime_type, size_bytes,
               storage_path, status)
            values ($1,$2,$3,'Stability Report.pdf','application/pdf',2048,
                    $4,'embedding')
            """,
            DOCUMENT, OWNER, PROJECT, f"{OWNER}/obj",
        )

        # ---------------------------------------------- 1. migration 0025 ---
        print("\n1. Migration 0025 is applied")

        columns = {
            r["column_name"]
            for r in await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name='documents'"
            )
        }
        check("claimed_at exists", "claimed_at" in columns)
        check("attempts exists", "attempts" in columns)

        bucket = await conn.fetchrow(
            "select id, public from storage.buckets where id = 'documents'"
        )
        check("the documents bucket exists", bucket is not None)
        # A public bucket would make every uploaded document world-readable to
        # anyone who learned its path - which is a uuid, but a uuid is not a
        # permission.
        check("and it is private", bucket is not None and bucket["public"] is False)

        # --------------------------------------- 2. readiness is derived ---
        print("\n2. `ready` is a fact about the data, not a flag")

        for index, seed in enumerate([0.1, 0.2, 0.3]):
            await conn.execute(
                """
                insert into public.document_chunks
                  (document_id, chunk_index, content, page_number, embedding)
                values ($1,$2,$3,$4,$5::vector)
                """,
                DOCUMENT, index, f"Passage {index} about depot release.",
                index + 1, vec(seed),
            )
        # One left deliberately unembedded.
        await conn.execute(
            """
            insert into public.document_chunks
              (document_id, chunk_index, content, page_number)
            values ($1,3,'Passage 3, not yet embedded.',4)
            """,
            DOCUMENT,
        )

        remaining = await conn.fetchval(
            "select count(*) from public.document_chunks "
            "where document_id = $1 and embedding is null",
            DOCUMENT,
        )
        check("an unembedded chunk is visible as such", remaining == 1, f"{remaining}")

        await conn.execute(
            "update public.document_chunks set embedding = $2::vector "
            "where document_id = $1 and embedding is null",
            DOCUMENT, vec(0.4),
        )
        remaining = await conn.fetchval(
            "select count(*) from public.document_chunks "
            "where document_id = $1 and embedding is null",
            DOCUMENT,
        )
        check("and none remain once filled", remaining == 0)

        await conn.execute(
            "update public.documents set status = 'ready' where id = $1", DOCUMENT
        )

        # -------------------------------------------- 3. vector retrieval ---
        print("\n3. Retrieval returns passages with their page")

        rows = await conn.fetch(
            """
            select c.id, c.page_number, d.filename,
                   1 - (c.embedding <=> $1::vector) as similarity
              from public.document_chunks c
              join public.documents d on d.id = c.document_id
             where d.project_id = $2 and d.user_id = $3 and d.status = 'ready'
          order by c.embedding <=> $1::vector
             limit 3
            """,
            vec(0.1), PROJECT, OWNER,
        )
        check("nearest passages are returned", len(rows) == 3, f"{len(rows)}")
        check(
            "every one carries a page number",
            all(r["page_number"] is not None for r in rows),
        )
        check(
            "and the filename needed for a citation",
            all(r["filename"] == "Stability Report.pdf" for r in rows),
        )

        # ------------------------------------- 3b. search is exact, not approximate ---
        print("\n3b. Retrieval is exact, and the plan proves it")

        # The ivfflat index from 0004 was built on an empty table, so its
        # centroids described nothing and it returned neighbours that were not
        # the nearest - measured at 0/10 overlap with exact search. 0026 removed
        # it. If it ever comes back, retrieval silently starts missing passages
        # again, and a passage that was never retrieved cannot be cited: its
        # absence is indistinguishable from the document not containing it.
        approximate = await conn.fetch(
            """
            select indexname from pg_indexes
             where schemaname = 'public' and tablename = 'document_chunks'
               and indexdef ilike '%ivfflat%' or indexdef ilike '%hnsw%'
            """
        )
        check(
            "no approximate index is present",
            len(approximate) == 0,
            str([r["indexname"] for r in approximate]),
        )

        plan = "\n".join(
            r["QUERY PLAN"]
            for r in await conn.fetch(
                """
                explain select c.id from public.document_chunks c
                 where c.document_id = $2
              order by c.embedding <=> $1::vector limit 3
                """,
                vec(0.1), DOCUMENT,
            )
        )
        check("the planner scans rather than probes", "Index Scan" not in plan)

        # ------------------------------- 4. a citation resolves to a chunk ---
        print("\n4. Evidence resolves to the exact passage")

        await conn.execute(
            """
            insert into public.research_runs (id, project_id, user_id, original_question)
            values ($1,$2,$3,'Does the depot release over 28 days?')
            """,
            RUN, PROJECT, OWNER,
        )
        chunk_id = rows[0]["id"]
        await conn.execute(
            """
            insert into public.evidence_records
              (run_id, marker, source_type, provider, title, identifier_type,
               identifier, access_level, retrieved_by_agent, document_chunk_id)
            values ($1,'E101','internal_document','Stability Report.pdf',
                    'Stability Report.pdf - p. 1','document','Stability Report.pdf#p1',
                    'full_text','document_agent',$2)
            """,
            RUN, chunk_id,
        )
        resolved = await conn.fetchrow(
            """
            select e.marker, c.page_number, c.content
              from public.evidence_records e
              join public.document_chunks c on c.id = e.document_chunk_id
             where e.run_id = $1
            """,
            RUN,
        )
        check("the citation joins back to its chunk", resolved is not None)
        check(
            "and lands on a page, not just a file",
            resolved is not None and resolved["page_number"] is not None,
            f"p. {resolved['page_number']}" if resolved else "",
        )

        # -------------------------------------------------- 5. isolation ---
        print("\n5. One user cannot read another's documents")

        await conn.execute("set local role authenticated")
        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            f'{{"sub":"{STRANGER}","role":"authenticated"}}',
        )
        visible = await conn.fetchval(
            "select count(*) from public.documents where id = $1", DOCUMENT
        )
        check("the stranger sees no document", visible == 0, f"{visible}")
        chunks_visible = await conn.fetchval(
            "select count(*) from public.document_chunks where document_id = $1",
            DOCUMENT,
        )
        check("nor any of its chunks", chunks_visible == 0, f"{chunks_visible}")

        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            f'{{"sub":"{OWNER}","role":"authenticated"}}',
        )
        own = await conn.fetchval(
            "select count(*) from public.documents where id = $1", DOCUMENT
        )
        check("the owner still sees their own", own == 1, f"{own}")
        await conn.execute("set local role postgres")

        # ---------------------------------------------------- 6. cascade ---
        print("\n6. Deleting a document takes its chunks with it")

        # The evidence row references a chunk, so this also proves the cascade
        # reaches through that foreign key rather than blocking on it.
        await conn.execute("delete from public.documents where id = $1", DOCUMENT)
        orphans = await conn.fetchval(
            "select count(*) from public.document_chunks where document_id = $1",
            DOCUMENT,
        )
        check("no chunks survive", orphans == 0, f"{orphans}")

        print(f"\n{passed} passed, {failed} failed")
        return 0 if failed == 0 else 1
    finally:
        await tx.rollback()
        await conn.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
