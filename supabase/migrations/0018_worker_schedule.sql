-- 0018 — The database becomes the scheduler.
--
-- WHY THIS LIVES IN POSTGRES
--
-- The research worker used to be a process that ran forever, polling run_jobs.
-- On a serverless host there is no such process: a function is started by a
-- request and killed at a fixed ceiling. Something has to start it.
--
-- Vercel Cron cannot: on the Hobby plan it fires ONCE PER DAY, so a queued run
-- could wait 24 hours to begin. pg_cron has minute precision on every Supabase
-- plan, and pg_net can make the outbound call, so the scheduling moves here.
--
-- THIS IS THE SAFETY NET, NOT THE MAIN PATH
--
-- Two faster triggers do the real work, both in application code:
--
--   * POST /api/runs pokes the worker immediately after enqueuing, so a
--     submitted run starts in seconds rather than at the next tick;
--   * a slice that exhausts its time budget triggers its own successor before
--     returning, so slices run back to back instead of one per minute.
--
-- This job exists for what those miss: a slice that crashed, a trigger whose
-- HTTP call was lost, a job left claimed by an invocation the host killed. Once
-- a minute is ample for that, and it is deliberately cheap - it does nothing at
-- all when the queue is empty.
--
-- WHERE THE CONFIGURATION LIVES, AND WHY IT MOVED
--
-- The first version of this file read `current_setting('app.worker_tick_url')`,
-- set by `alter database postgres set ...`. On Supabase that is refused:
--
--     ERROR 42501: permission denied to set parameter "app.worker_tick_url"
--
-- The `postgres` role there is deliberately NOT a superuser, and setting a
-- custom parameter at database scope requires one. So both values live in
-- Supabase Vault instead - which is a better home regardless, because Vault
-- encrypts at rest and `vault.decrypted_secrets` is readable only by
-- privileged roles, whereas a database setting is visible to anyone who can
-- call current_setting().
--
-- BEFORE APPLYING, create the two secrets (Dashboard -> Project Settings ->
-- Vault, so the value never enters SQL editor history):
--
--     worker_tick_url      https://<your-app>.vercel.app/api/worker/tick
--     worker_tick_secret   the same value as WORKER_TRIGGER_SECRET in Vercel
--
-- If they are absent this migration still applies cleanly; the tick simply
-- does nothing and says so. That is intentional - a scheduler that fails
-- closed is safe, one that fails silently is not.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- --------------------------------------------------------- reading the vault ---
--
-- Wrapped in its own function so the two callers below share one definition of
-- "configured", and so a missing secret is a null rather than an exception.

create or replace function private.worker_config(p_name text)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select s.decrypted_secret
    from vault.decrypted_secrets s
   where s.name = p_name
   limit 1;
$$;

comment on function private.worker_config(text) is
  'Reads a worker setting from Supabase Vault. Returns null when unset, which '
  'callers must treat as "not configured" rather than as an error.';

-- ------------------------------------------------------------------ the tick ---

create or replace function private.trigger_worker_tick()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  tick_url    text := private.worker_config('worker_tick_url');
  tick_secret text := private.worker_config('worker_tick_secret');
  waiting     integer;
begin
  if tick_url is null or tick_secret is null then
    raise notice
      'Worker tick skipped: vault secrets worker_tick_url / worker_tick_secret are not set.';
    return;
  end if;

  -- Do not wake the worker for an empty queue. A serverless invocation costs
  -- money and a cold start even when it finds nothing, and this runs 1,440
  -- times a day.
  select count(*) into waiting
    from public.run_jobs j
    join public.research_runs r on r.id = j.run_id
   where j.status = 'queued'
     and j.available_at <= now()
     and r.cancel_requested = false;

  if waiting = 0 then
    return;
  end if;

  perform net.http_post(
    url     := tick_url,
    headers := jsonb_build_object(
      'Content-Type',    'application/json',
      'x-worker-secret', tick_secret
    ),
    body    := jsonb_build_object('source', 'pg_cron'),
    -- Return immediately. The slice runs for minutes; pg_net must not be made
    -- to wait for it, and nothing here reads the response.
    timeout_milliseconds := 2000
  );
end;
$$;

comment on function private.trigger_worker_tick() is
  'Safety net that starts a worker slice when queued jobs exist. The primary '
  'triggers are in the application: on run creation, and slice-to-slice.';

-- --------------------------------------------------------- reclaim stuck jobs ---
--
-- A serverless invocation can be killed without warning - the host hitting its
-- own timeout, a deploy mid-slice, an out-of-memory kill. The job stays
-- 'claimed' with nobody working it, and because it is not 'queued' no worker
-- ever picks it up again. The run would sit at whatever progress it reached,
-- looking active, forever.
--
-- Anything claimed for longer than any slice could legitimately last is
-- therefore returned to the queue. The graph checkpoint survives, so this
-- resumes rather than restarts.

create or replace function private.reclaim_stalled_jobs(p_stale_minutes integer default 20)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  reclaimed integer;
begin
  with released as (
    update public.run_jobs
       set status = 'queued',
           claimed_by = null,
           claimed_at = null,
           available_at = now(),
           last_error = 'Reclaimed: the worker holding this job stopped responding.'
     where status = 'claimed'
       and claimed_at < now() - make_interval(mins => p_stale_minutes)
    returning id
  )
  select count(*) into reclaimed from released;

  return reclaimed;
end;
$$;

-- ---------------------------------------------------------------- the schedule ---

-- unschedule_all is not available, and re-running a migration must not stack
-- duplicate jobs, so remove by name first.
select cron.unschedule(jobid)
  from cron.job
 where jobname in ('worker-tick', 'reclaim-stalled-jobs', 'prune-http-responses');

select cron.schedule(
  'worker-tick',
  '* * * * *',
  $$select private.trigger_worker_tick()$$
);

select cron.schedule(
  'reclaim-stalled-jobs',
  '*/10 * * * *',
  $$select private.reclaim_stalled_jobs(20)$$
);

-- pg_net records every response it receives. Left alone the table grows without
-- limit, which on a free-tier database is a real problem rather than a tidiness
-- one.
select cron.schedule(
  'prune-http-responses',
  '17 3 * * *',
  $$delete from net._http_response where created < now() - interval '2 days'$$
);
