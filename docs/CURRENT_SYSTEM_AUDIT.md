# Current System Audit

**Repository:** `pharma-ai-copilot`
**Audit date:** 2026-08-03
**Auditor:** Pre-MVP conversion audit, performed before any code was modified.

## Verification method

This audit is based on reading every source file in `app/`, `components/`, and `lib/` (~50 files, no
file skipped), plus running the application locally.

The application **does run**. `npm run dev` starts cleanly on Next.js 15.5.22 and all eight routes
compile and return HTTP 200:

| Route | Status | Bytes |
|---|---|---|
| `/login` | 200 | 15,498 |
| `/dashboard` | 200 | 19,929 |
| `/patents` | 200 | 19,912 |
| `/literature` | 200 | 19,939 |
| `/strategy` | 200 | 19,921 |
| `/reports` | 200 | 19,912 |
| `/projects` | 200 | 19,921 |
| `/chat` | 200 | 19,885 |
| `/settings` | 200 | 19,921 |

Every one of those requests was made **without an authentication cookie or header**, and every one
returned the full page. This is itself the audit's most serious finding — see
[Security concerns](#4-security-concerns).

---

## 1. Current architecture

A single-tier Next.js application. There is no second tier.

```
pharma-ai-copilot/
├── app/
│   ├── layout.tsx              ThemeProvider → AuthProvider → TooltipProvider
│   ├── page.tsx                redirect to /dashboard
│   ├── login/page.tsx          client-side login form
│   └── (app)/                  AppShell-wrapped route group
│       ├── dashboard/  chat/  patents/  literature/
│       └── strategy/   reports/  projects/  settings/
├── components/
│   ├── ui/                     20 Radix + CVA primitives (shadcn-style)
│   ├── layout/                 app-shell, sidebar, topbar
│   ├── shared/                 stat-card, chart-card, page-header, agent-run-loader, …
│   ├── chat/                   composer, message-bubble, citation-chip, light-markdown
│   ├── motion/                 Framer Motion primitives
│   └── auth-provider.tsx       localStorage "auth"
└── lib/
    ├── data.ts     (31 KB)     all fixture content
    ├── responses.ts (9.8 KB)   keyword-matched chat replies
    ├── agents.ts   (4.9 KB)    agent registry + fake execution step strings
    ├── ai.ts       (1.7 KB)    stub model provider — imported by nothing
    ├── types.ts                domain interfaces
    └── utils.ts                cn(), formatRelative(), downloadFile()
```

**Stack:** Next.js 15.5.22 (App Router), React 19.1, TypeScript 5, Tailwind CSS v4,
Radix UI, Framer Motion 12, Recharts 3, `next-themes`, `lucide-react`.

**What is structurally absent:**

- No `app/api/` directory. **Zero API routes.**
- No server actions — `server-reference-manifest.js` in the build output is empty (`"node": {}`).
- No database, ORM, migrations, or connection code.
- No `fetch()` call anywhere in the source tree. Verified by grep across all `.ts`/`.tsx` files;
  the only matches are inside `.next/` build artifacts (webpack's own HMR code).
- No backend, no worker, no job queue, no orchestration framework.
- No LangGraph, no OpenAI SDK — neither is in `package.json`.
- No test files, no test runner, no CI configuration.
- No `Dockerfile`, `vercel.json`, or any deployment configuration.
- **Not a git repository.** `git status` fails; there is no `.git` directory.

Every page is a `"use client"` component that imports fixtures from `lib/data.ts` and renders them.
The architecture is a design prototype, and is internally consistent as one.

---

## 2. Existing working features

These genuinely work as implemented and represent real value to preserve.

| Feature | Location | Notes |
|---|---|---|
| Component library | `components/ui/*` (20 files) | Radix primitives + `class-variance-authority`. Correct `forwardRef`, `asChild`, and Radix a11y semantics. Production quality. |
| Application shell | `components/layout/*` | Responsive sidebar with mobile overlay, `motion.span layoutId` active-nav indicator, topbar. Works correctly. |
| Theming | `app/globals.css`, `theme-provider.tsx` | Tailwind v4 `@theme` with OKLCH tokens, light/dark via `next-themes`, `suppressHydrationWarning` set correctly. |
| Charts | `components/shared/chart-*.tsx` | Recharts wrappers with a shared themed tooltip. Render correctly against supplied data. |
| Markdown rendering | `components/chat/light-markdown.tsx` | Hand-rolled bold/list/heading parser. Safe — builds React elements, no `dangerouslySetInnerHTML` anywhere in the repo. |
| Markdown export | `lib/utils.ts` `downloadFile()` + `lib/responses.ts` `conversationToMarkdown()` | Genuinely produces and downloads a file. |
| Print export | `app/(app)/reports/page.tsx:154` | `window.print()` — real, though gated behind a cosmetic 250 ms delay. |
| Motion primitives | `components/motion/primitives.tsx` | FadeUp / Stagger wrappers, correctly implemented. |

---

## 3. Demo or mocked features

Everything the product claims to *do* is simulated. Specific findings:

### 3.1 Hard-coded research results

`lib/data.ts` (31 KB) exports fixtures that the "agents" render verbatim:
`semaglutidePatentLandscape`, `depotPeptideLiterature`, `buildStrategyOutput()`, `generatedReport`,
`projects`, `activity`, `patentActivity`, `pipelineByPhase`, `seedConversations`.

### 3.2 Agent runs that ignore user input

`app/(app)/patents/page.tsx:89-101` is representative:

```ts
async function runAnalysis(prompt?: string) {
  const text = (prompt ?? input).trim();
  if (!text || running) return;
  setRunning(true); setDone(false); setActiveStep(0);
  for (let i = 0; i < steps.length; i++) {
    setActiveStep(i);
    await new Promise((r) => setTimeout(r, 620 + Math.random() * 420));
  }
  setRunning(false); setDone(true);
}
```

`text` is read, checked for emptiness, and then **never used again**. The function sleeps and sets a
boolean, after which the page renders the fixture at line 87 (`const result = semaglutidePatentLandscape`).
Typing any question produces the semaglutide landscape.

Identical pattern in `literature/page.tsx:53`, `strategy/page.tsx:149`, `reports/page.tsx:149`.

### 3.3 Fake loading animations presented as telemetry

`lib/agents.ts:113-143` defines `AGENT_EXECUTION_STEPS`, displayed by `AgentRunLoader` as if it were
live progress:

- `"Querying global patent databases"`
- `"Parsing 1,284 claims across 312 families"`
- `"Searching PubMed, Embase & preprint servers"`
- `"Screening abstracts (PRISMA)"`

No database is queried, no claim is parsed, PubMed is never contacted. The counts are string
literals. The randomised `620 + Math.random() * 420` ms delay exists to make the fabrication feel
like computation.

### 3.4 Mock chat responses

`lib/responses.ts:12` `generateMockResponse(prompt)` lowercases the prompt and returns one of four
hardcoded essays based on substring matches (`"semaglutide"`, `"depot"`, `"snac"`, `"cqa"`), with a
random pick from two generic replies as fallback. `app/(app)/chat/page.tsx:86` awaits a 700 ms
`setTimeout` before displaying it.

The generic fallback at `lib/responses.ts:122` fabricates a source count arithmetically from the
prompt length:

```ts
`I've searched your connected corpus (${(p.length * 37) % 900 + 60} documents) …`
```

### 3.5 Fabricated citations

This is the most serious scientific-integrity problem. Sources presented to the user do not exist:

- `lib/responses.ts:65` — **`WO2027/018244`**, dated **2027**. A publication number in the future.
- `lib/responses.ts:61` — `Confidence: **94%** (PRISMA-compliant screening, dual reviewers, 3% disagreement resolved by adjudication)`. No screening occurred; there were no reviewers.
- `lib/data.ts` — `ResearchPaper` fixtures carry DOI strings that do not resolve.
- Citation objects are typed `Citation` with `title`/`source`/`year`/`type` but **no identifier field**
  and no link to any retrieved record, so nothing can be verified even in principle.

### 3.6 Static agent statuses

`lib/agents.ts:30-100` hardcodes each agent's `status`, `model: "gpt-4.1-2026-05"`, and
`knowledgeCutoff`. `app/(app)/patents/page.tsx:118-120` renders a pulsing dot badge reading
**"Live · GPT-4.1 · cutoff Jul 2026"** on a page that makes no network request of any kind.

### 3.7 Non-functional buttons

- `app/(app)/projects/page.tsx:66` — `<Button onClick={() => {}}>New project</Button>`. Empty handler.
- `app/(app)/settings/page.tsx:96` — "Save" sets a `saved` flag, shows a success toast for 1800 ms, and persists nothing.
- `app/(app)/reports/page.tsx:163` — "DOCX" export downloads an HTML string with a `.doc` extension and `application/msword` MIME type. It opens in Word but is not a DOCX file.

### 3.8 Demo-only authentication

`components/auth-provider.tsx:43-54`:

```ts
const login = React.useCallback(async (email: string) => {
  const user: UserProfile = { ...currentUser, name: firstName, email };
  const next: AuthState = { user, org: orgProfile };
  window.localStorage.setItem(AUTH_KEY, JSON.stringify(next));
  setState(next);
}, []);
```

No password parameter. No credential check. No server call. Any email string grants a session, and
identity is a `localStorage` value the user can edit in DevTools. `app/login/page.tsx:46` awaits
1100 ms to imitate a network round-trip.

### 3.9 Dead code

`lib/ai.ts` describes itself as "the single seam where real model calls plug in" and is **imported by
no file in the repository**. Verified by grep. It has never been on any code path.

---

## 4. Security concerns

Ordered by severity.

### S1 — No server-side authorisation whatsoever (Critical)

Protection is `useRequireAuth()` (`components/auth-provider.tsx:97`), a `useEffect` that calls
`router.replace("/login")` after the page has already been sent to the browser. There is no
middleware, no server component check, and no API layer to protect.

Confirmed empirically: `GET /dashboard` with no cookies returns 200 and the full page body. An
attacker never needs to defeat the redirect; they read the response. Today this only exposes
fixtures — but the same route structure is about to carry real proprietary R&D data.

### S2 — Client-side trust boundary (Critical)

Identity, organisation, and subscription state all live in `localStorage` under the key
`pharma-copilot-auth`, parsed with an unvalidated `JSON.parse` cast (`auth-provider.tsx:28`):

```ts
return raw ? (JSON.parse(raw) as AuthState) : null;
```

The `as` cast asserts a shape that is never verified. A malformed or hostile value is trusted.

### S3 — Model configuration exposed to the browser (High)

`.env.example:6` sets `NEXT_PUBLIC_OPENAI_MODEL=gpt-4.1` — uncommented, so it is a live default —
and `lib/ai.ts:15` reads it. The `NEXT_PUBLIC_` prefix inlines the value into the client bundle.

The `OPENAI_API_KEY` itself is **not currently leaked**: `.env.example:5` has it commented out,
`lib/ai.ts` is dead code, and no key exists in the repo. But `lib/ai.ts:25` reads
`process.env.OPENAI_API_KEY` inside a module with no `"use server"` directive. Had that module ever
been imported by a client component with a key configured, the pattern invites a leak. The file is
being deleted rather than repaired.

### S4 — No input validation anywhere (High)

No schema validation library is present. Textareas feed directly into state; the settings form
writes nothing so validates nothing. There is no server to validate against.

### S5 — No error handling (Medium)

There is no `error.tsx` or `not-found.tsx` in the App Router tree, and no error boundary. The single
`try/catch` in the application swallows its error silently (`patents/page.tsx:108`):

```ts
} catch {}
```

### S6 — Secrets hygiene (Medium)

`.gitignore:34` correctly ignores `.env*`, and **no secrets are currently committed**. However the
project is not a git repository at all, so no history protection is in force yet. `git init` must
happen with the ignore rules already correct — which they are.

### S7 — Prompt-injection surface (design-level)

Not yet exploitable because no model is called and no external content is retrieved. It becomes a
first-class concern the moment PubMed abstracts, patent texts, and user PDFs enter a prompt. No
defensive structure exists to build on.

### S8 — Known dependency vulnerabilities (High)

`npm audit` reports **3 high-severity advisories**, all transitive through `next@15.5.22`:

| Package | Advisory | CVSS |
|---|---|---|
| `postcss` (≤8.5.22) | Arbitrary file read via attacker-controlled `sourceMappingURL` in CSS comments | 7.5 |
| `postcss` | Path traversal in previous-source-map auto-loading → arbitrary `.map` disclosure | 7.5 |
| `postcss` | Incomplete fix of GHSA-6g55-p6wh-862q — reads arbitrary `.map` files when `from` is unset | — |
| `postcss` | XSS via unescaped `</style>` in CSS stringify output | 6.1 |
| `sharp` (<0.35.0) | Inherited libvips vulnerabilities CVE-2026-33327/33328/35590/35591 | — |
| `next` (9.3.4-canary.0 – 16.3.0-preview.10) | Parent advisory | — |

npm reports the fix as `next@16.3.0`, a **semver-major upgrade** from 15.5.22.

Practical severity here is limited: the postcss issues require attacker-controlled CSS at build
time, and `sharp` is only reachable through `next/image` optimisation, which this app does not use
(all images are local SVGs in `public/`). None is remotely triggerable by an application user.

They are nonetheless real and must be resolved. The Next.js 16 upgrade is **deliberately deferred**
until after the vertical slice is verified, so that a major framework upgrade and a full backend
rewrite are not in flight simultaneously — an upgrade at stage 1 would make every subsequent
failure ambiguous in origin. Scheduled for stage 10 alongside the production build, and recorded
in `docs/KNOWN_LIMITATIONS.md` until then.

---

## 5. Missing production requirements

Against the target MVP, the following do not exist in any form:

**Backend & orchestration**
- Python/FastAPI service; LangGraph workflow; typed graph state; checkpoint persistence
- Background job execution, progress streaming, retry, cancellation
- Supervisor and specialist agent implementations

**Data**
- PostgreSQL database, schema, migrations, connection pooling
- Persistence of runs, agent tasks, search queries, evidence, citations, report sections, errors, usage

**External integrations**
- PubMed E-utilities, Europe PMC, EPO OPS, Crossref, OpenAlex, USPTO adapters
- Rate limiting, retry/backoff, pagination, response caching, normalisation, deduplication
- Provider health reporting

**Model layer**
- OpenAI SDK; Responses API integration; structured JSON output validated by Pydantic
- Per-role model configuration, token accounting, cost tracking

**Evidence integrity**
- Evidence record model with resolvable identifiers
- Citation-to-record binding and verification
- Evidence-coverage-based confidence, contradiction detection, gap detection

**Documents**
- Upload, validation, storage, text extraction, page-anchored chunking, embeddings, retrieval

**Platform**
- Real authentication; server-side authorisation; row-level access control
- Input validation; error boundaries; structured logging; observability
- Automated tests of any kind; CI; deployment configuration; git repository
- Resolution of the 3 high-severity dependency advisories (S8)

---

## 6. Components that can be retained

Reusable **as-is** or with minimal change — roughly 60% of the frontend by file count:

- `components/ui/*` — all 20 primitives. No changes needed.
- `components/layout/app-shell.tsx`, `topbar.tsx` — no changes needed.
- `components/layout/sidebar.tsx` — structure retained; only the `navGroups` array is rewritten.
- `components/shared/*` — `stat-card`, `chart-card`, `chart-tooltip`, `page-header`, `empty-state`, `status-badge`, `logo`, `skeleton`. Presentational and data-agnostic.
- `components/motion/primitives.tsx` — no changes needed.
- `components/chat/light-markdown.tsx` — retained and becomes the sanitised report renderer.
- `components/chat/citation-chip.tsx` — retained; extended with a resolvable identifier and link.
- `app/globals.css`, `theme-provider.tsx`, `tsconfig.json`, `eslint.config.mjs`, `postcss.config.mjs` — no changes needed.
- `lib/utils.ts` — `cn()`, `formatRelative()`, `downloadFile()` all reused.
- `components/shared/agent-run-loader.tsx` — the component is **kept and rewired**. Its props are
  already `steps` + `activeStep`; the fix is to feed it real `run_events` instead of a `setTimeout`
  loop. The dishonesty is in the caller, not the component.

---

## 7. Components that should be refactored or removed

| Item | Action | Reason |
|---|---|---|
| `lib/data.ts` | **Delete** | 31 KB of fabricated results and non-existent citations. |
| `lib/responses.ts` | **Delete**, port `conversationToMarkdown()` | Keyword-matched fake answers with invented sources. |
| `lib/ai.ts` | **Delete** | Dead code; misleading comment; unsafe env pattern. |
| `lib/agents.ts` | **Refactor** | Keep the registry (id, name, description, icon, colour). Delete `AGENT_EXECUTION_STEPS`, and the hardcoded `model` / `knowledgeCutoff` / `status` fields — those come from backend config. |
| `lib/types.ts` | **Refactor** | Keep the shape vocabulary; regenerate against the real schema. **Delete `PatentSummary.score.freedom`** — an "FTO score" is a legal conclusion the product must never render. |
| `components/auth-provider.tsx` | **Rewrite** | Replace localStorage with Supabase Auth + middleware-enforced routes. |
| `app/(app)/{patents,literature,strategy,reports}` | **Remove as standalone routes** | Replaced by a single research-run detail page with per-agent tabs bound to real data. Their charts and cards are salvaged into those tabs. |
| `app/(app)/chat` | **Defer** | Not in MVP scope. Remove rather than leave a fake assistant shipping. |
| `app/(app)/projects` | **Rewrite** | Backed by the `projects` table; the empty `onClick={() => {}}` becomes a real create action. |
| `app/(app)/settings` | **Rewrite** | Must actually persist, and gains the integrations health view. |
| `app/(app)/dashboard` | **Rewrite** | Same layout, real aggregates from `research_runs` and `usage_records`. |
| `.env.example` | **Rewrite** | Remove `NEXT_PUBLIC_OPENAI_MODEL`; add all server-side provider variables as placeholders. |
| `README.md` | **Rewrite** | Currently the unmodified `create-next-app` boilerplate. |

---

## 8. Recommended implementation order

Sequenced so that each stage is independently verifiable and no stage depends on a later one. A
working vertical slice is reached at stage 7 and proven with live credentials before breadth is added.

| # | Stage | Verifiable outcome |
|---|---|---|
| 0 | This audit | — |
| 1 | Foundations: `git init`, secrets hygiene, `.env.example`, backend skeleton, delete mock modules | App still builds with fixtures gone |
| 2 | Database: Supabase project, migrations, RLS | Tables exist; RLS denies cross-user reads |
| 3 | Provider adapters: PubMed, Europe PMC, EPO OPS + cache, dedup, retry | Unit tests green on recorded fixtures; live smoke query returns real identifiers |
| 4 | LLM layer: Responses API, structured outputs, cost tracking | Pydantic-validated object returned from a live call |
| 5 | LangGraph workflow: typed state, nodes, conditional edges, checkpointer | Graph executes end-to-end on mocked providers |
| 6 | FastAPI + worker: run lifecycle, SSE progress, retry, cancel | `POST /runs` returns immediately; worker executes; events stream |
| 7 | Frontend rewire: Supabase Auth, New Research, run detail, source explorer | **Vertical slice complete** |
| — | **Live verification checkpoint** | One real run; every citation resolves by SQL; provider failure degrades honestly; kill-and-resume works |
| 8 | Document upload + RAG | Uploaded PDF cited with page reference |
| 9 | Optional providers, export, integrations page, dashboard metrics | Degraded-integration states render honestly |
| 10 | Full test suite, lint, typecheck, production build | All green |
| 11 | Documentation + seed demo project | Seed contains a question and zero pre-baked results |

### Ordering rationale

- **Providers before agents (3 before 5).** The evidence table is the foundation of citation
  integrity. Building agents first would mean building them against imagined data and inheriting
  exactly the fabrication problem this rewrite exists to remove.
- **Evidence records written before synthesis.** Citation markers are allocated from stored rows, so
  the model selects from an allowlist rather than composing identifiers. This makes fabricated
  citations structurally impossible instead of merely discouraged.
- **Auth before any real data lands (7, but S1/S2 addressed in 1–2).** Server-side authorisation must
  exist before the database holds proprietary research.
- **Live verification before breadth.** Stages 8–11 are additive. Integration risk concentrates in
  0–7, so it is retired first.

---

## Summary

The repository is a competently built, honest-to-itself **design prototype**: a well-structured
Next.js frontend with a genuinely good component library and no backend. It becomes misleading only
in what its copy claims — "Live · GPT-4.1", "Querying global patent databases", "Confidence: 94%
(PRISMA-compliant screening)" — while performing no computation.

The frontend foundation is worth keeping and roughly 60% of it survives the conversion. The entire
data and execution layer must be built from nothing, and the fixtures must be deleted rather than
adapted, because their central defect — citations to sources that do not exist, including a patent
publication dated 2027 — is precisely what the production system must make impossible.
