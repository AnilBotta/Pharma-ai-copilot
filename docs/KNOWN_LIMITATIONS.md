# Known Limitations

What has actually been verified, what has not, and what is missing. Read this
before relying on any output.

---

## 1. Verification status

The distinction below is deliberate. "Tested" means an automated test asserts
the behaviour. "Verified live" means it was executed against the real external
service and the result inspected.

### The full workflow has now run end-to-end against live services

One complete run, 2026-08-05, on the seeded peptide-depot question:

| | |
|---|---|
| Status | **completed** in 787 s (13 min) |
| Model calls | 139,005 tokens, **$0.64** estimated |
| Searches executed | 20 (10 PubMed, 10 Europe PMC) |
| Evidence stored | 6 publications, all with resolvable DOIs |
| Report | 21 sections |
| Citations | 57, **0 unresolved** |

Every cited DOI was independently confirmed against Crossref with matching
titles: `10.1016/j.nano.2026.102972`, `10.3762/bjnano.6.17`,
`10.1039/c4nr00291a`, `10.3390/ijms242316665`.

Behaviour observed in that run, all as designed:

- The patent agent reported *"not configured … This is not evidence that no
  relevant patents exist"*, and the run continued on literature alone.
- The `patent_landscape` section rendered **"No reliable evidence was retrieved
  for this section"** with confidence `insufficient_evidence`.
- The evidence reviewer found 2 high-severity issues and **requested one
  revision**, which the supervisor performed.
- No section was rated `high`. With six abstract-only sources that is the
  correct outcome.
- The limitations section stated the source count, that all six were
  abstract-only, that no patent search ran, the date window, and the error count.

Three bugs were found and fixed by that run; see §1.1.

### Verified against live services

| Capability | Evidence |
|---|---|
| PubMed retrieval | Live search returned 15 records from 158 hits with correct PMIDs, DOIs, PMCIDs, structured abstracts, dates and authors |
| Europe PMC retrieval | Live search returned 15 records from 7,454 hits with open-access flags and PMCIDs |
| Cross-provider deduplication | Ran over combined live results; every survivor carried a resolvable identifier |
| Database schema | 17 tables, 16 policies, 7 triggers applied to the live Supabase project |
| RLS isolation | Two real users created: the owner saw 1 run and 1 evidence record, the other saw 0 across runs, evidence, projects, events and literature; `anon` saw 0 including `provider_cache` |
| Citation-integrity constraints | Live inserts rejected: full-text claimed without text, record with no identifier, marker not matching `^E[0-9]+$` |
| Cascade deletes | Deleting users left every table empty |
| Server-side route protection | Every protected route returns 307 to `/login`; at baseline `/dashboard` returned 200 with 19,929 bytes to an anonymous request |
| No secrets in client bundle | 1.46 MB bundle contains the anon key and project URL only; no OpenAI key pattern, no `service_role`, none of the server env var names |
| Frontend build | `next build` produces 10 routes plus middleware; `tsc --noEmit` and `eslint` clean |
| Python suite | 256 tests passing, `ruff` clean |

### 1.1 Bugs the first live run exposed

None of these were reachable by the fixture-based tests. All are fixed, with
regression tests.

**1. Windows event loop.** `AsyncPostgresSaver` uses psycopg, which cannot run
async on the `ProactorEventLoop` Python selects by default on Windows. Every run
failed at checkpointer setup with
`psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'`. The worker
now installs `WindowsSelectorEventLoopPolicy`.

**2. Prepared statements through the pooler.**
`AsyncPostgresSaver.from_conn_string` hardcodes `prepare_threshold=0`, which in
psycopg means *prepare every statement*, not *never prepare* — that is `None`.
Server-side prepared statements bind to a backend connection, and Supabase's
transaction pooler hands out a different backend per transaction, so runs failed
mid-execution with `prepared statement "_pg3_4" does not exist` and
`… already exists`. The checkpointer connection is now built explicitly with
`prepare_threshold=None`.

**3. Europe PMC received PubMed syntax.** `PlannedSearch` carries a `provider`
field that the literature agent discarded, so every query ran against every
provider. All ten planned queries were written in PubMed syntax; PubMed returned
six usable records and **Europe PMC returned zero for all ten**, because
`[tiab]` and `[MeSH]` mean nothing to it. An entire provider was contributing
nothing, and it was invisible because zero results is a legitimate outcome.
Queries are now routed to their named provider, and the planner prompt specifies
each provider's dialect.

A fourth, found by the same script before the run: `/runs/{id}/events` was
SSE-only while the frontend polls it for JSON, so progress would never have
rendered. JSON is now the default; SSE moved to `/events/stream`.

### Tested only against fixtures — NOT verified live

| Capability | Why | What could still be wrong |
|---|---|---|
| **EPO OPS patent retrieval** | Needs `EPO_OPS_CONSUMER_KEY` / `_SECRET`, which are not configured | The OAuth2 endpoint and flow were confirmed correct (invalid credentials return 401, not 404), but the response **parser has never seen a real OPS payload**. Field paths, the single-vs-list collapsing, party de-duplication and classification parsing are all written against documented shapes and fixture data. Expect to fix parsing on first live use. |
| **All OpenAI model calls** | Needs `OPENAI_API_KEY` | The client is faked at the transport boundary in tests. Model IDs in `.env.example` (`gpt-5`, `gpt-5-mini`) have not been checked against the account's model list. `ModelProvider.health_check()` validates them at startup, so a wrong name fails fast rather than mid-run. |
| **Every SQL statement in `repository.py`** | Needs `DATABASE_URL` | The schema is verified live, and the API tests fake the repository, but the SQL itself has not executed. Column-name and type mismatches are plausible. |
| **JWT verification end-to-end** | Needs a signed-in user | The JWKS fetch and key resolution are now **verified against the live project** (1 ES256 key, `kid=f8d9b951…`, correct caching, unknown `kid` rejected). Signature verification is tested with locally generated ES256 tokens through a mocked JWKS. What remains untested is a token minted by Supabase itself — the `audience="authenticated"` assumption in particular. |
| **Checkpoint resume** | Needs a database | `AsyncPostgresSaver` is wired and `setup()` is called, but no run has been interrupted and resumed. |
| **SSE / live progress** | Needs a running backend | The endpoint exists; the frontend polls it. Neither has been exercised end-to-end. |
| **The complete research workflow** | Needs all of the above | The graph runs end-to-end in tests against fixture providers and a fake model. It has never run against real APIs. |

### Still not exercised

- **EPO OPS** remains unconfigured, so patent retrieval and its parser have
  never run against live OPS. This is the largest untested surface.
- **Checkpoint resume** — no run has been interrupted mid-flight and resumed.
  The retry path was exercised (3 attempts, honest failure) but always from the
  start.
- **The frontend against a live backend** — the JSON events endpoint was fixed
  after the run, so the browser progress view has not been watched end-to-end.
- **Cancellation** mid-run.

To enable patents:

```
EPO_OPS_CONSUMER_KEY=         # free at https://developers.epo.org
EPO_OPS_CONSUMER_SECRET=
```

`SUPABASE_JWT_SECRET` is **not** needed — this project signs with asymmetric
ES256 keys, verified against its JWKS endpoint.

---

## 2. Not implemented

### Document upload and RAG

Not built. The database schema (`documents`, `document_chunks` with a
`vector(1536)` column and an ivfflat index) and the evidence back-reference are
in place, and `internal_document` is a valid evidence source type, but there is
no upload endpoint, no PDF extraction, no chunking and no embedding pipeline.

The Documents page states this plainly rather than showing a file picker that
does nothing.

### Optional providers

Crossref, OpenAlex and USPTO adapters are not written. They appear in
configuration and on the integrations page so their absence is visible, but
selecting them does nothing. Only PubMed, Europe PMC and EPO OPS exist.

### Report export

Markdown export works (client-side assembly from fetched sections). PDF is
browser print-to-PDF via print CSS, not a server-rendered document.

### Human review checkpoint

The specified graph includes a `human_review_checkpoint` node. It is not
implemented. Runs proceed from verification straight to report generation. The
`awaiting_review` run status exists in the enum but is never set.

---

## 3. Design limitations

### The General Research Agent has no retrieval tools

It produces background framing from model knowledge alone. This is a real
weakness: an agent asked for "background" with no sources will produce fluent
recall, which is exactly what this system must not present as evidence.

The mitigation is structural, not perfect. Its claims are forced to
`assumption`, and any arriving labelled `direct` or `inferred` without citations
are downgraded in code. The report renders them as framing rather than findings.
But a reader skimming the background section is still reading unevidenced text.

### Marker blocks leave gaps

Literature and patent agents allocate from disjoint marker ranges to avoid a
concurrency collision. Numbering is contiguous within a block but gaps appear
between them (E1–E40, then E51–…). Markers are identifiers, not counts, so this
is cosmetic — but it looks odd.

### Confidence is a heuristic

Section confidence comes from citation coverage and distinct source count. It
measures how well-evidenced a section is, not whether the evidence is *good*.
A section citing six weak in-vitro papers scores higher than one citing two
strong trials.

### One revision maximum

The evidence reviewer can request one revision. If high-severity issues survive
it, they are reported in the run's warnings and the report ships with them
flagged. A second pass was judged not worth the tokens.

### Deduplication can over-merge

Records with no shared identifier are merged on normalised title. Titles under
20 characters are excluded to avoid collapsing every "Erratum", but two
genuinely distinct papers with identical titles would still merge.

### Provider coverage shapes conclusions

Absence of results reflects what these searches retrieved, never what exists.
This is stated in every report's limitations section, but it bears repeating:
a sparse patent section may mean a sparse landscape, or a poorly-phrased CQL
query.

---

## 4. Operational limitations

### Dependency vulnerabilities

`npm audit` reports **3 high-severity advisories**, all transitive through
`next@15.5.22`:

| Package | Issue | CVSS |
|---|---|---|
| `postcss` | Arbitrary file read via attacker-controlled `sourceMappingURL` | 7.5 |
| `postcss` | Path traversal in source-map auto-loading | 7.5 |
| `postcss` | XSS via unescaped `</style>` in stringify output | 6.1 |
| `sharp` | Inherited libvips CVEs | — |

npm reports the fix as `next@16.3.0`, a semver-major upgrade. Practical severity
here is limited: the postcss issues need attacker-controlled CSS at build time,
and `sharp` is only reachable through `next/image` optimisation, which this app
does not use. **They are nonetheless unresolved.** The upgrade was deferred so a
major framework change would not be in flight alongside the backend rewrite.

### Single worker

The queue uses `FOR UPDATE SKIP LOCKED`, so multiple workers are safe, but only
one is run and there is no supervision, autoscaling or dead-letter handling
beyond three attempts.

### Cost estimates are configuration, not billing

`llm/pricing.py` is an operator-maintained table. An unknown model yields `None`
and the UI shows no figure rather than a guess. **Verify the table against
current OpenAI pricing before trusting any cost number.**

### EPO OPS quota

The free tier allows 4 GB/month. Heavy use surfaces as a rate-limit error and
zero patent results, not as degraded output.

### No rate limiting on the API

Nothing prevents a user from queuing many expensive runs. `max_results` is
bounded per run (1–200); total spend is not.

### Windows-specific

Signal handling in `worker.py` degrades gracefully where
`add_signal_handler` is unsupported, so Ctrl+C relies on `KeyboardInterrupt`.

---

## 5. Scientific and regulatory limitations

- **No freedom-to-operate, validity or infringement conclusion** is produced.
  `PatentFindings` has no field to record one. Patent output is technical
  overlap only.
- **Abstract-only evidence** is labelled as such, and a database constraint
  prevents claiming full text was reviewed when only an abstract was stored.
- **No medical advice.** No dosing, treatment or clinical recommendations.
- **No regulatory assertion** without a citation supporting it.
- The system does not replace qualified scientists, patent counsel, regulatory
  experts, toxicologists, clinicians or statisticians.
