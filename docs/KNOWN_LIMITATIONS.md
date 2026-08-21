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

### 1.0 EPO OPS, verified live — and the two defects that surfaced

Credentials were added and the adapter run against the real service. Both
defects had been predicted in this document as the risk of fixture-only testing;
both were real.

**1. Wrong envelope key — the serious one.** The live service returns
`ops:biblio-search`. The documented shape, which the adapter and its fixture
were written against, says `ops:biblio-search-result`. A search returning
**15,159 hits parsed as zero records**.

It failed *silently*. `ok=True` with no records is a legitimate outcome — a
search that found nothing — so nothing raised, nothing logged, and a run would
simply have reported "no patents found" while stating honestly that patents had
been searched. That is a worse failure than a crash: the report would have been
confidently wrong in the one direction this system exists to prevent.

Both spellings are now accepted, with a regression test.

**2. IPC codes truncated.** OPS pads classifications to fixed width:
`"H10K  30/    15            A I"`. Tokenising and taking the first two fields
gave `H10K 30/`, dropping the subgroup and making every IPC code wrong but
plausible-looking. Now parsed as `H10K 30/15`, with a parametrised test over
four real padded forms.

Verified after fixing — `ti="carbon nanotube"` returns real records:

```
WO2026160546A1  fam=100684570  KOREA INST OF MATERIALS SCIENCE [KR]   priority 2025-01-23
WO2026154647A1  fam=100620759  DR GOO CO LTD [JP]                     priority 2025-01-17
US20260208867A1 fam=100577943  GOODRICH CORP [US]                     priority 2025-01-21
```

### 1.0b EPO OPS, a second live run — two more defects, both concrete

A user-facing run against the seeded PDX-114 walkthrough reported the patent
search entirely broken: 9 queries, all 9 failed, mixed `400`/`404`/`413`.
`ProviderHTTPClient` discards the response body on error, so the app itself
never saw more than "Request failed with status N." Reproduced live with the
credentials and the exact queries recovered from `search_queries`, both causes
turned out to be real and to have entirely different fixes.

**1. Patent-search queries were never filtered by their own `provider` field.**
The stored plan showed the planner had done its job correctly — 4 queries
labelled `provider="europepmc"` in Europe PMC's `TITLE_ABS:` syntax, 5 labelled
`provider="epo_ops"` in proper CQL, all inside `patent_searches`. `patent_agent`
sent every one of the 9 to every configured patent provider regardless of the
label, because nothing read it — the exact defect §1.1's `TestQueryRouting`
already documents for the literature side, present here too because the
patent side never got the same fix. Live, that got exactly what asking for it
gets:

```
CLIENT.InvalidIndex (400): "Invalid index name title_abs"
CLIENT.NotOperatorMaxNumber (413): "There can not be more than 1 NOT operators"
```

`patent_agent` now has its own `_queries_by_provider`, routing each query only
to the provider it names. It differs from the literature version in one
deliberate way: a query naming a *known-but-not-ours* provider (here,
`europepmc`, a real provider name that just isn't a patent provider) is
**dropped**, not broadcast to whatever patent providers exist — broadcasting is
what caused this incident, since the only configured patent provider received
it anyway. An unlabelled query still broadcasts, since there is nothing to
route it by.

**2. A zero-result CQL search is reported by OPS as HTTP 404, not 200 with an
empty list.** The 5 correctly-routed queries were narrow-and-correct CQL
searching for a fictional walkthrough compound (`PDX-114`) that has no real
patents — a legitimate empty result, which OPS expresses as
`SERVER.EntityNotFound`, `"No results found"`, at HTTP 404:

```
ti=peptide                                              -> 200, 45,676 hits
(ti="PDX-114" or ti="PDX114" or ...) and ab=peptide      -> 404, "No results found"
```

`ProviderHTTPClient`'s generic `>=400` handling turned that into a reported
provider failure — "epo_ops failed" — for what was actually a correct, honest
zero. `EPOOPSProvider.search()` now special-cases a 404 as an empty successful
result rather than forwarding it as an error; every other status still
surfaces as a failure exactly as before.

Both fixes replayed against the exact failing run's stored plan, live: routing
now sends exactly the 5 correctly-labelled queries to EPO OPS, and all 5 come
back `ok=True` with `records=0` rather than reported as broken.

**Still unverified for EPO:** the family-lookup endpoint, legal-status
retrieval (deliberately not implemented — it costs extra quota and would invite
legal inference), and behaviour at the 4 GB monthly quota ceiling.

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

### 1.2 PDP Phase C, verified against the live database — and the engine bug it exposed

`backend/tests/db/test_phase_c_workflow.py` drives `PdpRepository` — the code an
HTTP request, and later an agent tool, actually reaches — against the real
database inside a rolled-back transaction. **75 assertions, all passing**,
alongside the 22 of `test_readiness_engine.py`.

The headline case, constructed and confirmed:

```
readiness_pct = 93.1    is_ready = FALSE    blockers = 1
gate approval REFUSED, and the refusal names R-004
```

Also confirmed live: a draft template cannot be instantiated; instantiating twice
is refused; an unfinished or foreign research run is refused as evidence;
acceptance cannot be confirmed with nothing attached; the requirement owner and
the acceptance confirmer are both refused approval by database trigger; attaching
evidence *or* withdrawing acceptance supersedes an existing approval; a
prerequisite going unsatisfied cascades to its dependants; a mandatory
requirement cannot be scoped out; and the person who approved a requirement
cannot subsequently be made its owner.

**A latent defect in the readiness engine surfaced during this work, and it was
serious.** `requirement_is_satisfied()` recursed until the stack ran out, on a
requirement with *no prerequisites at all*. Migration 0014 had written the
prerequisite check as one query with the recursive call in the `WHERE` clause:

```sql
where d.requirement_id = req_id
  and dep.is_mandatory
  and not private.requirement_is_satisfied(dep.id)   -- planner may run this first
```

SQL is declarative; the planner may apply quals in any order. Given the row
counts it chose to scan `gate_requirements` and evaluate the function *before*
the join restriction, calling it on every requirement in the table including the
one already being evaluated. The comment above the query claimed recursion
terminates because the dependency graph is acyclic — true, and irrelevant: the
recursion was not following the dependency graph.

Nothing was wrong with the data or the cycle trigger. The bug shipped with 0014
and only appeared when the planner's estimates changed, which is the worst
property a defect in a gate decision can have — the engine's behaviour depended
on table statistics rather than on the record. Migration 0017 moves the recursion
into a `plpgsql` loop, where it runs once per real dependency edge and cannot be
reordered.

Migration 0016 additionally replaced `constraint reviewer_is_not_owner check
(true)` — a constraint named for a rule it did not enforce, since a `CHECK`
cannot reference another table — with a trigger that does enforce it.

#### What Phase C has NOT been verified against

| Gap | Why it matters |
|---|---|
| **The browser UI end-to-end** | Since resolved for Phase C — the gate workspace was driven in a browser against the real database, including both refusals. The Phase D document register pages build and typecheck but have **not** been exercised in a browser. |
| **A two-person workflow in the UI** | Segregation of duties means one account cannot complete a requirement: whoever confirms acceptance is refused approval. A pilot needs a second account. This is the design working, not a bug, but it makes a solo demo dead-end at the approval step. |
| **`gate_blockers()` at scale** | It filters with `not private.requirement_is_satisfied(r.id)` in a `WHERE` clause. Unlike the 0017 case this cannot recurse, but the planner may still evaluate it on more rows than the stage contains. Correct, potentially slow on a large portfolio; not yet measured. |
| **Concurrent approval of the same requirement** | The `approvals_one_current` partial unique index makes a double approval fail rather than duplicate, but the losing request's error message has not been checked. |

### 1.3 Phase D closed a hole that had been open since Phase C

The readiness engine advertises seven conditions. The third — *"document
evidence is on a current, non-superseded version"* — was **not enforced**. There
was no register to check against, so it was a comment describing an intention
while the code did nothing.

The consequence was the module's own failure mode: a requirement satisfied by a
document stayed satisfied forever, including after that document was replaced.
A gate could report ready on a superseded specification and nothing anywhere
would say so.

Migration 0019 makes it code, and `test_document_register.py` (25 assertions,
live database) pins it: superseding a document leaves the requirement
**unsatisfied**, invalidates the approval that rested on it, and produces a
blocker naming the fix. An approved-but-**expired** version also fails, which a
status label alone would have hidden.

Worth noting how it was found: not by testing, but by counting. 43 of the 50
seeded requirements demand document evidence, which is what made it obvious that
condition 3 had never been reachable.

#### Phase D gaps

| Gap | Why it matters |
|---|---|
| **No SharePoint Graph API** | Links are recorded and trusted. Nothing verifies the URL resolves, that the file behind it is the one approved, or that its permissions match. The `checksum` column exists for this and nothing populates it automatically. |
| **The register UI is unexercised in a browser** | It builds and typechecks; the underlying repository is covered by 25 live assertions. |
| **No document review workflow** | A version moves between statuses by API call. There is no reviewer assignment, no circulation, no e-signature. Phase I territory. |
| **Expiry is not proactive** | An expired version stops satisfying requirements the day it expires, silently. Nothing warns beforehand — that needs the Phase F notification engine. |

### 1.4 Phase E gaps

The frozen baseline is verified (25 live assertions, including that editing a
baseline date is refused while the forecast moves and the slip is computed). What
is **not** built:

| Gap | Consequence |
|---|---|
| **No formal change-request workflow** | Re-baselining requires approval authority and a stated reason, but it is one call, not a proposal somebody else reviews. The plan's `schedule_change_requests` table was not built — approval authority plus an audited reason covers the pilot case. |
| **No Gantt visualisation** | The schedule page is a table showing baseline against forecast with variance. Deliberate: a chart library was not worth the dependency when the number that matters is the slip, and a bar chart hides it more often than it shows it. |
| **Critical path assumes finish-to-start** | `SS`, `FF` and `SF` dependency types are stored and honoured for lag, but the backward pass treats every edge as finish-to-start. On a schedule using them heavily the float will be wrong. |
| **No resource levelling or capacity** | Effort is recorded per task; nothing checks whether one person is on six critical tasks at once. |
| **The schedule UI is unexercised in a browser** | It builds and typechecks; the layer beneath it has 25 live assertions. |

### 1.5 Phase F gaps

Deduplication, auto-resolution and escalation are verified (22 live assertions,
including that three sweeps produce one event and that the database itself
refuses a duplicate). What is **not** done:

| Gap | Consequence |
|---|---|
| **No email has ever been sent** | With no `RESEND_API_KEY` the notifier is `LoggingNotifier` and every delivery is recorded `skipped` with a reason. The Resend path is written but has never run against the real API — the request shape is unverified. |
| **No digests** | Each event produces its own message. The plan called for daily digests to senior management; the dedup index makes the volume survivable but a busy programme will still generate several mails a day. |
| **Escalation is one rung** | `escalate_to_roles` fires once. There is no three-tier ladder, and no reminder cadence after that. |
| **Sweep is per-tick, not per-event** | Conditions are found by a sweep every minute rather than fired by a trigger the instant they become true, so an alert can be up to a minute late. Deliberate — a query over current state cannot leave a permanent hole the way a missed trigger can. |
| **No in-app or Slack channel** | The `channel` column allows `in_app`, and the UI reads events directly, but nothing writes in-app deliveries. |
| **Recipients are role-based only** | The rule names roles; there is no per-user subscription or mute. Someone holding `project_manager` on six programmes gets everything for all six. |

### 1.6 Phase G gaps

The authority limit is verified against the live database (21 assertions,
including that an agent holding a user id with **every** approving role is still
refused, at 100% readiness with zero blockers — so it is the agent rule firing,
not the readiness check standing in for it).

Writing that suite caught two defects in the suite itself, both of which would
have produced a false pass: the gate test originally ran on an unready gate and
"passed" on the readiness refusal, proving nothing; and the confirmation test
ran raw SQL on an unmarked connection, so no agent rule could have applied.

**What is not verified:**

| Gap | Consequence |
|---|---|
| ~~Neither agent has ever run against a real model~~ | **Now verified.** Both ran against the live model: 993/3,715 tokens for the gate assessment (59.3 s) and 329/702 for the portfolio summary, **$0.046 for the pair**. The blocker analysis named root causes rather than restating the list, assigned each action to a role, and referred the scientific question onward instead of answering it. It also exposed a prompt defect — the agent suggested re-baselining overdue dates "to current realities", which is the Phase E failure arriving by a longer route. The prompt now forbids that framing. |
| **No LangGraph graph** | The plan called for these as graphs with checkpointing. They are single structured calls — enough for one gate, but there is no multi-step planning, no tool loop, and no resumability. The *conversational* Manager Agent does have a tool loop (`ModelProvider.complete_with_tools`); these two single-shot endpoints do not. |
| **The handoff is a string, not a call** | `handoff_question` is recorded for a human to act on. Nothing invokes the Scientist Agent with it. |
| ~~No agent UI~~ | **Now built.** `AgentAssessment` on the gate page and `PortfolioBriefing` on the programmes index. Both render below the readiness engine's own figures and are labelled advisory; neither persists, so a stale assessment cannot be mistaken for current fact. Not yet exercised by a human against the deployment. |
| **The verdict-vocabulary check is four words** | It catches the obvious cases. An agent determined to imply a decision could write "meets every criterion listed" and the constraint would allow it. The prompt forbids it; the database only catches the flagrant version. |

### Tested only against fixtures — NOT verified live

| Capability | Why | What could still be wrong |
|---|---|---|
| ~~EPO OPS patent retrieval~~ | **Now verified live — see below** | Two parsing defects found and fixed on first real use. |
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

### 1.6b Notifications: now sending, after two failures that looked identical

**Verified in production.** `/api/health` reports
`resend: configured — "Alert email via Resend, from SyncAI <hello@mail.syncai.tech>"`,
and a sweep delivered the entire backlog:

```
{"sent":44,"failed":0,"skipped":0,"considered":44}
```

Getting there took two fixes, and the instructive part is that **both failed the
same way from the outside** — 44 rows marked `skipped`, no error anywhere, and a
system that looked configured. Neither was visible without reading the database.

**Email needs two variables and sends nothing without both:**

```
RESEND_API_KEY
NOTIFICATION_FROM_EMAIL     (RESEND_FROM_EMAIL is also accepted)
```

`build_notifier` falls back to the logging notifier if either is missing, so a
near-miss on one name disables alerts entirely and reports nothing about why.
That is not hypothetical: a deployment had `RESEND_API_KEY` and
`RESEND_FROM_EMAIL` both correctly set and still delivered nothing, because the
field only bound `NOTIFICATION_FROM_EMAIL`. Both names are accepted now, and
`GET /api/health` reports which half is missing when one is.

That last clause is only true since the fix below. Previously a `skipped`
delivery permanently consumed its slot in the `(event_id, recipient,
escalation_level)` unique constraint, so configuring email later would have
delivered **nothing** — the 44 would have stayed unsent forever while the table
showed 44 deliveries. Found by reading production, not by a test: the dispatch
path had no database coverage at all, which is how it survived. It has six
assertions now.

### 1.7 The conversational Manager Agent

Built in four steps and driven in a browser against the real model at each one.
See `MANAGER_AGENT.md` for what it may and may not do.

**Verified live:** the streaming tool loop against the real Responses API; 28
tools across reading, dispatch, writes and proposing; dispatching the PDP
Operations Agent from inside a turn (nested agent marks, no conflict);
`actor_agent` distinguishing an agent's edit from a person's; the premise check
refusing a confirmation after a colleague withdrew an acceptance; and
segregation of duties still refusing the confirming person.

**Bugs the live runs exposed**, none of which a green unit suite had caught:

| | |
|---|---|
| `usage_records` was empty for the chat | The loop called the usage sink; the route built `ModelProvider` without one. Six turns spent money and recorded none of it. **No unit test can see a constructor argument that was never passed** |
| `actor_agent` was never set | Latent since Phase A. `audit_events` has had the column since 0007, described as making accountability unambiguous, and nothing populated it — so every agent action looked like a person's |
| jsonb double-encoding | The pool's codec encodes with `json.dumps`; passing an already-serialised string stored JSON inside JSON. Surfaced far away as a response-validation error |
| `get_blockers` did not exist | The first live run answered a portfolio question with eight `get_gate` calls, 38,687 tokens. One tool shaped like the question: 11,176 |

**What is not verified:**

| Gap | Consequence |
|---|---|
| ~~Steps 2–4 have not run on the deployment~~ | **Now verified on `pharma-ai-copilot.vercel.app`.** Vercel does **not** buffer the SSE body: sampling the panel every 200 ms, tool activity appeared at 10.0 s and 16.6 s and the prose grew across three separate samples from 20.0 s to 20.6 s. A buffered body would have delivered all of it in one step at the end. Five tools in one turn, answer complete and correct |
| **A successful approval-by-confirmation** | Not a defect: the only account on the demo project confirmed the acceptance itself and is correctly barred from approving. Proving the happy path needs a second user with gate authority |
| **`search_docs` is keyword-scored** | Good enough for one repository's prose, and tested against the questions users actually ask. It will miss a question phrased entirely in synonyms |
| **No LangGraph graph for the chat** | A bounded tool loop, not a planner. No resumability: a turn killed mid-flight is lost, though the question and any partial answer are recorded |

---

## 2. Not implemented

### Document upload and RAG — now built (stage 8)

Implemented and verified on the deployment. PDF, plain text and Markdown upload
directly to a private Supabase Storage bucket via a signed URL, are extracted
page by page, chunked with page and heading retained, embedded in batches, and
retrieved by the `document_agent` branch as `internal_document` evidence with
page-anchored citations.

What remains true and worth knowing:

- **No OCR.** A scanned PDF contains images of text, extracts to nothing, and is
  failed with a message saying so rather than arriving `ready` and empty.
- **Vector search is exact, not approximate.** The ivfflat index from `0004` was
  built on an empty table, so its centroids partitioned nothing; measured at
  0/10 overlap with exact search on uniformly distributed vectors, though it
  returned the same top three on a real corpus. Removed in `0026`. Exact search
  costs about 31 ms at 4,000 chunks. Reconsider an index around 100k chunks per
  project, built *after* the corpus exists and with recall actually measured.
- **Documents are project-scoped.** A run searches every `ready` document on its
  own project. There is no per-run selection and no cross-project sharing.
- **The upload goes around the API**, because a serverless request body is
  capped near 4.5 MB and the limit is 25 MB.

### Human review checkpoint — partially built

The specified graph includes a `human_review_checkpoint` node. There is still no
node, and no run pauses mid-graph for a person.

What now exists is the outcome that mattered most. A report whose reviewer still
reports high-severity findings after its one permitted revision ends
`awaiting_review` rather than `completed`, and the report's Limitations section
opens by saying it did not pass verification and listing what survived.

Before this, `verification.requires_revision` was forced False once the revision
budget was spent, so it meant "clean **or** we gave up" and nothing downstream
could tell the difference. A run finished with nine unresolved high-severity
findings, recorded `completed`, and said nothing about verification anywhere in
its report.

Still absent: nobody is *asked* to review. The run is held and labelled; there
is no assignment, no notification, and no action that clears the state.

### Optional providers

Crossref, OpenAlex and USPTO adapters are not written. They appear in
configuration and on the integrations page so their absence is visible, but
selecting them does nothing. Only PubMed, Europe PMC and EPO OPS exist.

### Report export

Markdown export works (client-side assembly from fetched sections). PDF is
browser print-to-PDF via print CSS, not a server-rendered document.

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
