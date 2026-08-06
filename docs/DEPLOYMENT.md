# Deployment

Three deployable units: the Next.js frontend, the FastAPI API, and the worker.
The worker is a separate long-running process and **cannot** run on serverless
functions — a research run takes minutes.

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

## 2. API and worker

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

`NEXT_PUBLIC_API_BASE_URL` must point at the deployed FastAPI service, not
`localhost`. **The backend cannot run on Vercel**: the worker is a long-lived
process that polls a job queue and executes multi-minute graphs, which no
serverless function can host. See §2 for Railway or Render.

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
