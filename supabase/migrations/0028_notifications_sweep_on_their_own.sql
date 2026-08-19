-- 0028 — Notifications stopped being swept whenever the system was idle.
--
-- The worker tick does three things: run a research slice, sweep notifications,
-- and ingest documents. The comment introducing the sweep says it
--
--     "rides along on the tick that already runs every minute"
--
-- and that premise is false. `private.trigger_worker_tick` returns early unless
-- there is a queued research job or - since 0027 - a document awaiting ingest.
-- It was written that way deliberately and correctly: a serverless invocation
-- costs money and a cold start, 1,440 times a day. But it means the tick does
-- NOT run every minute. It runs when there is research or document work, and at
-- no other time.
--
-- So on an idle system nothing sweeps. Conditions are not detected, alerts that
-- should close stay open, escalations do not happen, and pending mail is not
-- dispatched - all while pg_cron reports `succeeded` every minute, because the
-- statement it runs did succeed.
--
-- MEASURED, NOT SUPPOSED
--
-- 44 open `requirement_overdue` events, all unacknowledged, all at escalation
-- level 0, all raised 3 days and 22 hours ago. The rule escalates after 72
-- hours. They were 22 hours overdue for escalation and had not moved, because
-- no tick had fired since the last piece of research finished.
--
-- THE FIX IS NOT TO WAKE THE WORKER MORE OFTEN
--
-- Detection, resolution and escalation are already pure SQL - `private.
-- sweep_notifications` and `private.escalate_notifications` are database
-- functions and were from the day they were written. They never needed the
-- application at all, and running them here costs one query every few minutes
-- instead of a serverless invocation.
--
-- Only DELIVERY needs the application, because sending mail means calling
-- Resend. So the tick is additionally woken when there is mail actually waiting
-- - which is a cheap question with an exact answer, unlike "might a condition
-- have become true", which can only be answered by doing the work.

-- ------------------------------------------------------- the sweep, in SQL ---

create or replace function private.sweep_all_notifications()
returns table (projects integer, raised integer, resolved integer, escalated integer)
language plpgsql
security definer
set search_path = ''
as $$
declare
  n_projects  integer := 0;
  n_raised    integer := 0;
  n_resolved  integer := 0;
  n_escalated integer := 0;
  r           record;
  swept       record;
begin
  for r in
    select id from public.projects where pdp_enabled = true
  loop
    select * into swept from private.sweep_notifications(r.id);
    n_projects := n_projects + 1;
    n_raised   := n_raised + coalesce(swept.raised, 0);
    n_resolved := n_resolved + coalesce(swept.resolved, 0);
  end loop;

  n_escalated := private.escalate_notifications();

  return query select n_projects, n_raised, n_resolved, n_escalated;
end;
$$;

comment on function private.sweep_all_notifications() is
  'Detection, resolution and escalation for every PDP project, in the database. '
  'The application does the same work on its tick, and both are idempotent - '
  'detection is a query over current state, and raising leans on the one-open-'
  'event unique index. This exists because the tick only fires when there is '
  'research or document work, so on an idle system nothing swept at all. See 0028.';

-- Every five minutes. Detection is a handful of queries over current state and
-- costs nothing worth saving; the alternative is alerts whose timeliness
-- depends on whether somebody happened to be running research.
select cron.unschedule('notification-sweep')
 where exists (select 1 from cron.job where jobname = 'notification-sweep');

select cron.schedule(
  'notification-sweep',
  '*/5 * * * *',
  $$select private.sweep_all_notifications()$$
);

-- ------------------------------------------- wake the worker to send mail ---

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

  -- Documents waiting to be ingested. Mirrors DocumentRepository.claim_next;
  -- if the two drift the tick either fires for nothing or declines to fire for
  -- something. See 0027.
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

  -- Mail waiting to be sent, and A PERSON TO SEND IT TO.
  --
  -- The audience check is not an optimisation. `dispatch_pending` writes one
  -- delivery row per recipient, so an event with no eligible recipient
  -- produces no row at all - and a condition of the form "has no delivery at
  -- its current rung" would then be true of that event for ever, waking a
  -- serverless function every minute in perpetuity to send nothing.
  --
  -- That is not hypothetical on this deployment. `requirement_overdue`
  -- escalates to `department_head`, and nobody holds that role, so all 44 open
  -- alerts escalate to a rung with an empty audience. Without the join below,
  -- fixing the sweep would have replaced a tick that never fired with one that
  -- never stopped.
  --
  -- Mirrors the audience query in `dispatch_pending`, including its exclusion
  -- of `skipped`: a row saying nothing left the building must not count as
  -- delivered, or a backlog raised before any provider existed can never be
  -- sent.
  --
  -- Deliberately asks only about mail, not about whether a condition might
  -- have become true. That second question cannot be answered without doing
  -- the detection, and detection now happens in the database on its own
  -- schedule, so by the time there is anything to send this query finds it.
  if waiting = 0 then
    select count(*) into waiting
      from public.notification_events e
      join public.notification_rules r on r.id = e.rule_id
     where e.resolved_at is null
       and e.acknowledged_at is null
       and exists (
         select 1
           from public.user_roles ur
           join public.profiles p on p.id = ur.user_id
          where ur.role_id in (
                  select id from public.roles
                   where key = any(
                     case when e.escalation_level = 0
                          then r.notify_roles else r.escalate_to_roles end))
            and (ur.project_id is null or ur.project_id = e.project_id)
            and (ur.expires_at is null or ur.expires_at > now())
            and p.is_active
            and not exists (
              select 1 from public.notification_deliveries d
               where d.event_id = e.id
                 and d.recipient_user_id = ur.user_id
                 and d.escalation_level = e.escalation_level
                 and d.status <> 'skipped'
            )
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
    timeout_milliseconds := 2000
  );
end;
$$;

comment on function private.trigger_worker_tick() is
  'Safety net that starts a worker slice when there is work the APPLICATION '
  'must do: a queued research job, a document awaiting ingest, or an alert '
  'awaiting delivery. Detection and escalation no longer depend on it - they '
  'run in the database on their own schedule (0028), because gating them on '
  'other work meant an idle system swept nothing at all.';
