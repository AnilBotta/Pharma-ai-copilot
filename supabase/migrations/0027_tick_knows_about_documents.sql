-- 0027 — The scheduler's safety net could not see uploaded documents.
--
-- 0018 gave `private.trigger_worker_tick()` a deliberate early return:
--
--     -- Do not wake the worker for an empty queue. A serverless invocation
--     -- costs money and a cold start even when it finds nothing, and this runs
--     -- 1,440 times a day.
--
-- Correct, and it counted `run_jobs` alone, because in 0018 research runs were
-- the only work a tick could do. Stage 8 then hung document ingest on that same
-- tick without teaching the trigger that documents exist.
--
-- THE CONSEQUENCE
--
-- Upload a document while no research run happens to be queued, and the tick is
-- never called. The document stays `pending` forever. Every surface reports
-- health: pg_cron runs every minute and records `succeeded`, because the SQL
-- statement did succeed - it decided there was nothing to do and returned.
--
-- Observed exactly that. A document sat `pending` with `attempts = 0` while
-- cron.job_run_details showed an unbroken run of successes, and pg_net had not
-- recorded a response in over an hour.
--
-- WHY THE APPLICATION-SIDE NUDGE IS NOT ENOUGH
--
-- `POST /documents/{id}/complete` calls trigger_tick itself, so the normal path
-- through the UI does start ingest promptly. But that call is best-effort by
-- design - it is wrapped in a suppressed exception precisely so a scheduler
-- hiccup cannot fail an upload the user completed successfully. The scheduler
-- is what covers that failure. A safety net that does not know about half the
-- work is not a safety net; it is a second thing to check when the first thing
-- silently did nothing.
--
-- The early return stays. It is right, and it now asks about all the work
-- rather than some of it.

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

  -- Research runs waiting to be executed.
  select count(*) into waiting
    from public.run_jobs j
    join public.research_runs r on r.id = j.run_id
   where j.status = 'queued'
     and j.available_at <= now()
     and r.cancel_requested = false;

  -- Documents waiting to be ingested. The condition mirrors
  -- DocumentRepository.claim_next: work that has never started, plus work whose
  -- claim went stale because the host killed the function part-way through. If
  -- these drift apart the tick either fires for nothing or, worse, declines to
  -- fire for something - which is the failure this migration exists to fix.
  if waiting = 0 then
    select count(*) into waiting
      from public.documents d
     where d.storage_path is not null
       and (
             (d.status = 'pending' and d.claimed_at is null)
          or (d.status in ('pending', 'extracting', 'embedding')
              and d.claimed_at is not null
              and d.claimed_at < now() - interval '900 seconds')
       );
  end if;

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
  'Safety net that starts a worker slice when there is work: a queued research '
  'job, or a document awaiting ingest. The primary triggers are in the '
  'application - on run creation, on upload completion, and slice-to-slice - '
  'and this covers the case where one of those best-effort calls does not '
  'arrive. It must know about every kind of work the tick performs; see 0027.';
