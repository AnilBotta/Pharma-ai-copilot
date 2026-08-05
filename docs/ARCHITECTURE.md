# Architecture

## Shape

Three processes, one database.

```
┌──────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Next.js 15      │────▶│  FastAPI         │────▶│  Postgres          │
│  App Router      │     │  (uvicorn)       │     │  (Supabase)        │
│  Supabase Auth   │◀────│  JWT verified    │◀────│  RLS + pgvector    │
│  middleware.ts   │     │  service role    │     └────────────────────┘
└──────────────────┘     └──────────────────┘              ▲
         │                        │                        │
         │ poll progress          │ enqueue                │
         │                        ▼                        │
         │               ┌──────────────────┐              │
         └──────────────▶│  run_jobs queue  │              │
                         └──────────────────┘              │
                                  │ claim                  │
                                  ▼                        │
                         ┌──────────────────┐              │
                         │  Python worker   │──────────────┘
                         │  LangGraph       │
                         └──────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
          PubMed /            EPO OPS          OpenAI
         Europe PMC                         Responses API
```

## Why a separate worker

A research run makes dozens of external calls and takes minutes. Holding an
HTTP request open for that is unworkable: proxies time out, a page refresh loses
the work, and there is nowhere to record partial progress.

So `POST /api/runs` does three things in one transaction — create the run,
enqueue a job, return the id — and returns immediately with `202 Accepted`. The
worker claims jobs with:

```sql
select ... from run_jobs
 where status = 'queued' and available_at <= now()
 order by created_at limit 1
   for update skip locked
```

`skip locked` lets several workers poll the same table without blocking or
double-claiming, which is what makes this a real queue without Redis or Celery.

State is checkpointed to Postgres after every graph node, so a worker that dies
mid-run leaves a resumable run. Retrying re-enters at the last completed node
rather than repeating paid API calls.

## Request paths

**Creating a run.** Browser → FastAPI (JWT verified) → `research_runs` +
`run_jobs` insert → `202` with `run_id` → browser navigates to the run page.

**Watching a run.** The browser polls `GET /runs/{id}/events?after_id=N` every
two seconds. `EventSource` cannot send an `Authorization` header, and putting an
access token in a query string would place it in server logs and browser
history, so polling with a bearer token was the safer trade.

**Executing a run.** Worker claims job → builds providers from configuration →
compiles the graph with a Postgres checkpointer → streams state → writes a
`run_events` row per node → persists everything in one transaction at the end.

## Data model

17 tables. The ones that carry the design:

| Table | Role |
|---|---|
| `evidence_records` | **The citation source of truth.** `marker` is constrained to `^E[0-9]+$` and unique per run. |
| `literature_records` | Normalised publications. `full_text_requires_content` forbids `has_full_text = true` with no stored text. `literature_has_identifier` requires at least one of doi/pmid/pmcid/url. |
| `patent_records` | `record_type` distinguishes published application, granted patent and family record. There is **no** freedom-to-operate column. |
| `run_events` | Append-only progress log. Task summaries and tool activity only — never model reasoning. |
| `report_sections` / `citations` | Report body and the section↔evidence join, with a `verified` flag. |
| `run_jobs` | Durable queue. |
| `run_errors` | Honest failure record. A provider failure is logged and surfaced; it never produces substituted results. |
| `usage_records` | Per-call model, tokens and estimated cost. |
| `provider_cache` | Public external responses, shared across users. RLS enabled with no policy: deny-all through the anon key. |
| `documents` / `document_chunks` | Upload schema. `embedding vector(1536)` is the only use of pgvector. |

Literature and patent retrieval are structured SQL queries against indexed
identifier columns. Vector search is used only for document chunks.

## The citation guarantee

This is the property the system exists to provide, so it is enforced in four
places rather than asked for once:

1. **Allocation.** Provider adapters write evidence rows *before* any synthesis
   node runs. Markers are allocated from records that were actually retrieved.
2. **Constraint.** `marker ~ '^E[0-9]+$'` and `unique (run_id, marker)` mean a
   marker is an index into retrieved data, not free text.
3. **Prompt.** Synthesis receives the marker list as its only citable sources.
4. **Validation.** Every `[En]` in generated text is extracted and checked. What
   does not resolve is stripped and replaced with `[unverified citation
   removed]`, and recorded in the run's warnings.

Step 4 is what makes the guarantee hold. Steps 1–3 make it likely; step 4 makes
it true regardless of what the model does.

The reference list and the limitations section are assembled by code from stored
rows. No model writes them.

## Access control

The backend connects with the **service role**, which bypasses RLS. So:

- Every repository read takes a `user_id` and filters on it. That is the real
  access control.
- RLS policies are defence in depth for anything reaching the database another
  way — the anon key from a browser, a future edge function, a mistake.
- Child tables derive ownership from their parent run or project through
  `private.owns_run()`, rather than carrying a duplicate `user_id` that could
  drift out of sync.

Route protection is in `middleware.ts`, which runs before any page content is
produced and calls `getUser()` (revalidates with Supabase) rather than
`getSession()` (reads a client-controlled cookie).

## Provider layer

Every adapter honours one contract:

```
succeeded     → records
found nothing → zero records, ok=True
failed        → zero records, ok=False, error explains why
```

There is no fourth branch. An adapter never substitutes or approximates,
because a fabricated source is worse than no source.

`SearchResult` distinguishes "the search worked and found nothing" from "the
search failed" — a distinction the report depends on, since the first supports
"no reliable evidence found" and the second does not.

## Model layer

`llm/provider.py` wraps `client.responses.parse()` with a Pydantic
`text_format`. The deprecated Assistants API is not used.

No model name is hardcoded. Callers select a `ModelRole` — supervisor, research,
extraction, synthesis, verification — and configuration resolves it, so a
deployment can put a cheap model behind extraction and a strong one behind
synthesis without code changes.

Retries are bounded with exponential backoff. 4xx other than 429 is not
retried, because a malformed request fails identically and only spends money
doing so.

## Frontend

Next.js 15 App Router, Tailwind v4, Radix primitives. Roughly 60% of the
original prototype's component library survived the rewrite unchanged — it was
genuinely good; what was wrong was the fabricated data underneath it.

`components/runs/agent-timeline.tsx` replaces the prototype's `AgentRunLoader`.
Same visual idea, but every state derives from an event the worker recorded,
rather than stepping through hardcoded strings on a `setTimeout`.

## Extension points

- **New literature or patent source**: implement `LiteratureProvider` or
  `PatentProvider` and add it to `build_providers()`. Nothing downstream changes.
- **New agent**: add a node module, register it in `graph.py`, append its name to
  `_MARKER_BLOCKS` if it produces evidence.
- **New model provider**: `ModelProvider` is the only place the OpenAI SDK is
  touched.
- **Document RAG**: schema and evidence source type already exist; the pipeline
  is the missing piece.
