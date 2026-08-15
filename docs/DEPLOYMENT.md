# Deployment

Two supported topologies. Pick one before you start.

| | **Supabase + Vercel** | **Long-lived processes** |
|---|---|---|
| Hosts | 2 (Supabase, Vercel) | 3 (database, API, worker) |
| Worker | HTTP-triggered, runs in time-budgeted slices | one process, polls forever |
| Scheduler | Supabase `pg_cron` | none needed |
| Cost floor | free tiers | a container that must never scale to zero |
| Section | **§A** | §B |

**§A is the recommended route** and the one this project is verified on. §B stays
documented because it is simpler to reason about and is what you want if you
already run containers.

The thing that decides the design either way: **a research run takes about 785
seconds**, measured, across ten node visits. That does not fit inside one
serverless invocation.

---

## 1. Database

Supabase, or any Postgres 15+ with `pgcrypto` and `pgvector`.

Apply `supabase/migrations/*.sql` in filename order:

```bash
supabase link --project-ref <ref>
```

```bash
supabase db push
```

Then confirm hardening carried over:

```sql
select count(*) from pg_tables where schemaname='public' and rowsecurity;   -- 17
select count(*) from pg_policies where schemaname='public';                 -- 16
select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='public' and p.prosecdef;                                  -- 0
```

The third must be zero: no SECURITY DEFINER function should live in the
PostgREST-exposed schema. Also run the Supabase advisor and confirm the only
remaining finding is the intentional deny-all on `provider_cache`.

---

# §A. Supabase + Vercel

One Vercel project serves the frontend **and** the Python API on the same domain.
Supabase provides the database and the scheduler. No third host.

## A1. How the worker survives a 300-second ceiling

Vercel kills a function at a fixed limit — **300 s on Hobby, and that cannot be
raised**; 800 s on Pro, 1800 s in beta. A 785 s run does not fit in the first and
barely fits in the second.

So the worker runs in **slices**. `WORKER_SLICE_BUDGET_SECONDS` gates whether a
slice takes on *another* node; a node already running always finishes. Worst case
is therefore `budget + longest_node`, and it is that sum which must fit the
ceiling.

Measured per-node visit on a real run:

| | seconds |
|---|---|
| longest single node (`supervisor_synthesis`) | **120.3** |
| whole run, ten visits | 785 |

| Plan | Ceiling | Set budget to | Worst case |
|---|---|---|---|
| Hobby | 300 s | **150** | ~280 s |
| Pro | 800 s | 600 | ~720 s |

A first analysis of the same data reported the longest node as 240 s and would
have ruled Hobby out. That was wrong: the graph **re-enters** `supervisor_synthesis`
when the evidence reviewer requests a revision, and the two visits had been added
together. A slice executes one visit at a time.

### Why it resumes instead of restarting

The obvious implementation — stream the graph and `break` when the budget runs
out — **silently does not work**, and a test against the real checkpointer is
what caught it. After abandoning a stream, `checkpoints` held exactly one row:
`step=-1, source=input`. LangGraph commits a step's checkpoint as part of
beginning the *next* one, so a dropped stream loses every completed node.

Nothing would have shown in the UI. Every slice would restart at node one and,
against a hard ceiling, the run could never finish — killed, restarted, killed
again, paying for every model call each time.

The worker therefore advances one super-step per `astream` call using
`interrupt_after`, which pauses the way the library intends and leaves a durable
checkpoint. Proven in `backend/tests/db/test_slice_resume.py` and end-to-end
against the live database: **a run split across 7 slices executes each node
exactly once and makes 8 model calls — the same as an unsliced run.**

## A2. Files

Already in the repository:

| File | Purpose |
|---|---|
| `api/index.py` | Vercel entrypoint; re-exports the same `app` uvicorn serves |
| `api/requirements.txt` | runtime deps, no test tooling |
| `vercel.json` | `maxDuration`, `includeFiles`, and the `/api/(.*)` rewrite |
| `.vercelignore` | keeps `.env` and `.venv` out of the bundle |
| `supabase/migrations/0018_worker_schedule.sql` | `pg_cron` + `pg_net` scheduling |

`backend/tests/test_deployment_manifest.py` fails if a runtime dependency is
added to the backend and not mirrored into `api/requirements.txt`, because that
drift shows up only as an `ImportError` on a user's first request.

## A3. Vercel setup

Import the repository as a Vercel project (framework: Next.js, root: repo root).
Then add environment variables — Production, Preview **and** Development.

Public (inlined into the browser bundle at **build** time):

```
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable key>
```

Do **not** set `NEXT_PUBLIC_API_BASE_URL`. Unset means same-origin, which is
what you want: the API is on this domain, so there is no CORS at all.

Server-only:

```
DATABASE_URL=postgresql://postgres.<ref>:<pw>@<host>:6543/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service role key>
OPENAI_API_KEY=sk-...
NCBI_API_KEY=            NCBI_EMAIL=ops@yourdomain.com
EPO_OPS_CONSUMER_KEY=    EPO_OPS_CONSUMER_SECRET=
ENVIRONMENT=production
WORKER_TRIGGER_SECRET=<generate one, see below>
WORKER_SLICE_BUDGET_SECONDS=150
PUBLIC_BASE_URL=https://<your-app>.vercel.app
```

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

On **Pro**, raise both numbers together — `maxDuration` in `vercel.json` to 800
and `WORKER_SLICE_BUDGET_SECONDS` to 600. Raising one without the other is how
you get a run killed mid-node.

## A4. Supabase scheduling

The migration reads two values from **Supabase Vault**. Add them in the
dashboard under **Project Settings → Vault → Add new secret**, which keeps the
value out of SQL editor history:

| Name | Value |
|---|---|
| `worker_tick_url` | `https://<your-app>.vercel.app/api/worker/tick` |
| `worker_tick_secret` | the same value as `WORKER_TRIGGER_SECRET` in Vercel |

Then apply `0018_worker_schedule.sql`.

> **Not `alter database postgres set`.** An earlier version of this document
> told you to put these in database-level settings. Supabase refuses that with
> `ERROR 42501: permission denied to set parameter` — its `postgres` role is
> deliberately not a superuser, and setting a custom parameter at database
> scope requires one. Vault is the correct home anyway: it encrypts at rest,
> and `vault.decrypted_secrets` is readable only by privileged roles, whereas
> a database setting is readable by anyone who can call `current_setting()`.

If the secrets are missing the migration still applies; the tick logs a notice
and does nothing. Verify it is actually configured rather than assuming:

```sql
select private.worker_config('worker_tick_url') is not null as url_set, private.worker_config('worker_tick_secret') is not null as secret_set;
```

That schedules three jobs: a minute-by-minute tick, a ten-minute sweep that
reclaims jobs abandoned by a killed invocation, and a nightly prune of
`net._http_response`, which otherwise grows without limit.

**Cron is the safety net, not the main path.** Two faster triggers do the real
work: `POST /api/runs` pokes the worker on submission, and a slice that spends
its budget triggers its own successor before returning. The tick exists for what
those miss — a crashed slice, a lost HTTP call.

The tick also does nothing when the queue is empty, which matters when it runs
1,440 times a day on a metered plan.

## A5. What this topology cannot do

- **A single node longer than the slice budget stalls the run.** The deadline is
  only checked between nodes. At 120 s against a 150 s budget there is a 2.5×
  margin today; a much larger `max_results`, or a slower model, erodes it.
- **No streaming progress push.** The UI polls `run_events`, which is unchanged.
- **Cold starts.** Every slice pays Python import time. Irrelevant next to a
  120 s node, but it is not free.

---

# §B. Long-lived processes

Use this if you already run containers, or want the worker to be a single
process that polls.

Leave `WORKER_SLICE_BUDGET_SECONDS` at `0`, which disables slicing entirely, and
`WORKER_TRIGGER_SECRET` unset, which disables `/api/worker/tick`. Do not apply
migration 0018 — nothing needs to poke anything.

## B1. API and worker

Both run from `backend/` and share the same environment.

### Container

```dockerfile
FROM python:3.13-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The worker uses the same image with a different command:

```
python -m app.worker
```

### Platform notes

Anything that runs a long-lived process works — Fly.io, Railway, Render,
ECS/Cloud Run with min-instances ≥ 1, or a VM with systemd.

**The worker must not be autoscaled to zero.** It polls; scaling to zero stops
runs from executing. Multiple workers are safe (`FOR UPDATE SKIP LOCKED`), so
scale out for throughput.

### Environment

```env
DATABASE_URL=postgresql://postgres.<ref>:<pw>@<host>:6543/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service role key>
SUPABASE_JWT_SECRET=<jwt secret>
OPENAI_API_KEY=sk-...

OPENAI_MODEL_SUPERVISOR=gpt-5
OPENAI_MODEL_RESEARCH=gpt-5
OPENAI_MODEL_EXTRACTION=gpt-5-mini
OPENAI_MODEL_SYNTHESIS=gpt-5
OPENAI_MODEL_VERIFICATION=gpt-5

NCBI_API_KEY=
NCBI_EMAIL=ops@yourdomain.com
EPO_OPS_CONSUMER_KEY=
EPO_OPS_CONSUMER_SECRET=

CORS_ALLOW_ORIGINS=https://your-frontend-domain
ENVIRONMENT=production
LOG_LEVEL=INFO
```

Use the **transaction pooler** (port 6543) on Supabase. The pool sets
`statement_cache_size=0` accordingly, because that pooler multiplexes
connections and server-side prepared statements cannot be relied upon.

**The direct host is IPv6-only.** On current Supabase projects
`db.<ref>.supabase.co` publishes an AAAA record and no A record, so it is
unreachable from any network without IPv6 — which includes most home and office
connections, and some CI runners. Verified for this project: the direct host
resolved to IPv6 only and was unreachable, while both regional pooler hosts
resolved to IPv4 and connected.

Copy the exact connection string from the dashboard's **Connect** button (top
bar), not from the Settings page. Regions front two pooler hostnames
(`aws-0-<region>` and `aws-1-<region>`); both resolve, but only the one assigned
to your project will authenticate. Using the wrong one produces
`Tenant or user not found`, which `check_setup.py` explains.

`ENVIRONMENT=production` disables `/docs`.

Set `CORS_ALLOW_ORIGINS` to your exact frontend origin. Leaving the localhost
default in production means the browser blocks every call.

---

## 3. Frontend

Vercel or any Next.js host.

```env
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable key>
NEXT_PUBLIC_API_BASE_URL=https://your-api-domain
```

```bash
npm ci && npm run build
```

Only `NEXT_PUBLIC_*` variables are available to the browser. Never add a server
secret with that prefix.

**Set all three before the first deploy, and tick every environment** —
Production, Preview and Development. `NEXT_PUBLIC_*` values are inlined into the
bundle by static substitution *when it is built*, not read when it runs. A value
added after a build has no effect on that build: the strings were already baked
in as `undefined`. Changing one requires a redeploy, and on Vercel a redeploy
**with the build cache cleared**, since a cached build will not be recompiled.

The symptom of getting this wrong used to be a build failure on `/_not-found` —
a page that needs no authentication at all — reporting

```
Error: Supabase is not configured. Copy .env.example to .env.local ...
Export encountered an error on /_not-found/page: /_not-found, exiting the build.
```

because the auth provider wraps every page, including the ones Next.js
prerenders. The provider no longer throws when the values are absent; the build
now succeeds and the running application says plainly on its sign-in page that
it is unconfigured. That is a better failure, but it is still a failure — the
app cannot authenticate anyone until the values are set.

In **§B only**, `NEXT_PUBLIC_API_BASE_URL` must point at the deployed FastAPI
service, not `localhost`. In §A leave it unset — the API is same-origin.

---

## 4. Post-deployment checks

**Health**

```bash
curl https://your-api-domain/api/health
```

Confirm `status: ok`, the database connects, and each integration reports the
state you expect. `epo_ops: not_configured` is legitimate but means patents will
not be searched.

**Auth enforcement**

```bash
curl -i https://your-frontend-domain/dashboard
```

Must be `307` to `/login`. If it returns 200 with page content, middleware is
not running — check that `middleware.ts` deployed and its matcher covers the
route.

```bash
curl -i https://your-api-domain/api/runs
```

Must be `401`.

**No secrets in the bundle**

```bash
curl -s https://your-frontend-domain/_next/static/chunks/*.js | grep -c "service_role"
```

Must be `0`.

**End-to-end**

Sign up, run `python -m app.seed --email you@example.com --start`, and confirm
the run page shows progress events and produces a report whose citations
resolve.

Then verify citation integrity directly:

```sql
-- Must return zero rows: every citation resolves to stored evidence.
select c.marker
  from public.citations c
  left join public.evidence_records e on e.id = c.evidence_id
 where e.id is null;
```

---

## 5. Operations

### Cost control

Each run makes one model call per node plus one per retrieved record for
extraction, which dominates volume — point `OPENAI_MODEL_EXTRACTION` at the
cheapest adequate model.

`max_results` bounds per-run spend (1–200). **Total spend is not bounded**;
there is no API rate limiting. Monitor `usage_records`:

```sql
select date_trunc('day', created_at) as day,
       sum(estimated_cost_usd) as cost,
       sum(input_tokens + output_tokens) as tokens
  from public.usage_records
 group by 1 order by 1 desc limit 30;
```

Cost figures come from an operator-maintained table in `llm/pricing.py`. **Verify
it against current OpenAI pricing.** An unknown model yields no figure rather
than a guess.

### Cache maintenance

```sql
select private.purge_expired_provider_cache();
```

Schedule daily via `pg_cron` or an external scheduler.

### Stuck runs

A worker killed mid-run leaves the run `running` and its job `claimed`. There is
**no automatic reaper**. To recover:

```sql
update public.run_jobs
   set status = 'queued', claimed_by = null, claimed_at = null
 where status = 'claimed' and claimed_at < now() - interval '1 hour';
```

The run resumes from its last checkpoint rather than restarting.

### Monitoring

| Signal | Query |
|---|---|
| Queue depth | `select count(*) from run_jobs where status='queued'` |
| Failure rate | `select status, count(*) from research_runs group by 1` |
| Provider failures | `select provider, count(*) from run_errors group by 1` |
| Stripped citations | search `run_events` for `never retrieved` |

The last one matters: a rising count means a model is regularly inventing
citations. They are being caught, but it is a signal worth watching.

### Backups

Supabase provides automatic backups on paid plans. `evidence_records`,
`report_sections` and `citations` are the irreplaceable tables — losing them
means losing the provenance of every report.
