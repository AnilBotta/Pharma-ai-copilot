# Known Limitations

What has actually been verified, what has not, and what is missing. Read this
before relying on any output.

---

## 1. Verification status

The distinction below is deliberate. "Tested" means an automated test asserts
the behaviour. "Verified live" means it was executed against the real external
service and the result inspected.

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

### The definition-of-done items that remain unmet

A user cannot yet sign in, submit a question and receive a report, because no
run has ever executed against live services. Everything is built and wired; what
is missing is credentials:

```
DATABASE_URL=                 # Supabase → Settings → Database (pooler, 6543)
SUPABASE_SERVICE_ROLE_KEY=    # Supabase → Settings → API Keys
OPENAI_API_KEY=               # required; nothing runs without it
EPO_OPS_CONSUMER_KEY=         # optional; patents degrade honestly without it
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
