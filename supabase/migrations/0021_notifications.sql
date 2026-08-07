-- 0021 — Phase F: the notification rules engine.
--
-- THE FAILURE MODE THIS PHASE GUARDS AGAINST
--
-- Every previous phase guarded against a state that looks better than it is.
-- This one guards against something subtler: a system that reports everything,
-- which produces exactly the same outcome as a system that reports nothing,
-- while looking like coverage. People stop reading. The one alert that mattered
-- arrives in a stream of forty that did not, and is missed.
--
-- So the noise controls are structural rather than advisory:
--
--   * DEDUPLICATION is a unique index, not a convention. One open event per
--     condition. A requirement that has been overdue for six weeks generates
--     one notification, not forty-two.
--   * AUTO-RESOLUTION closes an event when the condition clears. An alert that
--     survives the fix is noise, and worse, it teaches people that alerts do
--     not mean anything.
--   * ESCALATION requires elapsed time since the previous level was told, so
--     an unread notice cannot cascade to the executive within the minute.
--
-- AND THE THING NOTIFICATIONS MUST NEVER BECOME
--
-- A notification is a pointer to state, never the state itself. Every condition
-- here is recomputed from the record on each sweep. If the mail server is down
-- for a week, nothing is lost and nothing is wrong - the gate still knows it is
-- blocked. That is why detection is a query and not a trigger writing a queue:
-- a missed trigger would leave a permanent hole.
--
-- IT ALSO CLOSES A HOLE PHASE D LEFT OPEN
--
-- 0019 made document expiry enforceable: an expired version stops satisfying
-- requirements. It did so silently. A document lapses on a Tuesday, three
-- requirements quietly stop being satisfied, and nobody is told until somebody
-- opens the gate. `document_expiring` warns before that happens.

-- ------------------------------------------------------- notification_rules ---

create table public.notification_rules (
  id  uuid primary key default gen_random_uuid(),
  key text not null unique check (key ~ '^[a-z_]+$'),

  name        text not null,
  description text,

  --: Which detector in private.detect_notification_conditions() feeds this.
  condition text not null unique check (condition in (
    'requirement_overdue',
    'requirement_awaiting_approval',
    'document_expiring',
    'document_expired_in_use',
    'task_overdue',
    'critical_task_slipping',
    'gate_ready_for_review'
  )),

  severity text not null default 'warning'
    check (severity in ('info', 'warning', 'critical')),

  --: How many days ahead, or how many days of tolerance, depending on the
  --: condition. Null means the detector's own default.
  threshold_days integer,

  --: Role keys told first. Empty means the owner of the thing only.
  notify_roles text[] not null default '{}',

  --: Escalation. Null disables it - not everything deserves to travel upward,
  --: and a ladder on a trivial rule is how executives learn to filter the
  --: folder.
  escalate_after_hours integer check (escalate_after_hours is null or escalate_after_hours > 0),
  escalate_to_roles    text[] not null default '{}',

  is_active boolean not null default true,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger notification_rules_set_updated_at
  before update on public.notification_rules
  for each row execute function private.set_updated_at();

-- ------------------------------------------------------ notification_events ---

create table public.notification_events (
  id      uuid primary key default gen_random_uuid(),
  rule_id uuid not null references public.notification_rules(id) on delete cascade,

  project_id uuid references public.projects(id) on delete cascade,

  --: What this is about, so the UI can link to it and the detector can match an
  --: existing open event to a still-true condition.
  subject_type text not null,
  subject_id   text not null,

  severity text not null,
  title    text not null,
  detail   text,

  --: THE DEDUPLICATION KEY. One open event per rule per subject, enforced by a
  --: partial unique index rather than by every caller remembering to check.
  dedup_key text not null,

  raised_at timestamptz not null default now(),

  --: Set when the condition stops being true. Auto-resolution is what stops an
  --: alert outliving its problem.
  resolved_at     timestamptz,
  resolved_reason text,

  acknowledged_by uuid references auth.users(id) on delete set null,
  acknowledged_at timestamptz,

  escalation_level   integer not null default 0,
  last_escalated_at  timestamptz,

  created_at timestamptz not null default now()
);

-- One open event per condition. This single index is what stands between the
-- pilot and forty emails about the same overdue requirement.
create unique index notification_events_one_open
  on public.notification_events (dedup_key)
  where resolved_at is null;

create index notification_events_project_idx
  on public.notification_events (project_id, raised_at desc);
create index notification_events_open_idx
  on public.notification_events (severity, raised_at)
  where resolved_at is null;

comment on index public.notification_events_one_open is
  'Deduplication is an index, not a convention. A condition that has been true '
  'for six weeks produces one event, not forty-two.';

-- -------------------------------------------------- notification_deliveries ---

create table public.notification_deliveries (
  id       uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.notification_events(id) on delete cascade,

  recipient_user_id uuid references auth.users(id) on delete cascade,
  recipient_email   text,

  channel text not null default 'email' check (channel in ('email', 'in_app')),

  --: `skipped` is a real outcome worth recording: no email configured, or the
  --: recipient already told at a lower escalation level. Silence with a reason
  --: beats silence.
  status text not null default 'pending'
    check (status in ('pending', 'sent', 'failed', 'skipped')),
  error text,

  --: Which rung of the ladder this delivery belongs to.
  escalation_level integer not null default 0,

  sent_at    timestamptz,
  created_at timestamptz not null default now(),

  --: A person is told once per event per escalation level. Re-running the sweep
  --: cannot re-send.
  unique (event_id, recipient_user_id, escalation_level)
);

create index notification_deliveries_event_idx
  on public.notification_deliveries (event_id);
create index notification_deliveries_pending_idx
  on public.notification_deliveries (status, created_at) where status = 'pending';

-- ---------------------------------------------------------- the detectors ---
--
-- One query returning every condition that is CURRENTLY true, recomputed from
-- the record. Not a log of things that happened - a statement of what is wrong
-- right now. That is what makes auto-resolution possible: anything previously
-- raised and no longer in this result set has been fixed.

create or replace function private.detect_notification_conditions(p_project_id uuid)
returns table (
  condition    text,
  subject_type text,
  subject_id   text,
  title        text,
  detail       text,
  owner_user_id uuid
)
language sql
stable
security definer
set search_path = ''
as $$
  with rules as (
    select condition, coalesce(threshold_days, 0) as threshold_days
      from public.notification_rules where is_active
  )

  -- A mandatory requirement past its due date and still not satisfied.
  select 'requirement_overdue',
         'gate_requirement', r.id::text,
         r.ref_code || ' is overdue',
         'Due ' || r.due_date || ' and still ' || private.requirement_status(r.id) || '.',
         r.owner_user_id
    from public.gate_requirements r
    join rules ru on ru.condition = 'requirement_overdue'
   where r.project_id = p_project_id
     and r.is_mandatory
     and r.due_date is not null
     and r.due_date < current_date - make_interval(days => ru.threshold_days)
     and not private.requirement_is_satisfied(r.id)

  union all

  -- Evidence and acceptance are in place; somebody just has to approve it.
  select 'requirement_awaiting_approval',
         'gate_requirement', r.id::text,
         r.ref_code || ' is waiting for approval',
         'Accepted ' || r.acceptance_confirmed_at::date
           || ' and still awaiting an approver.',
         r.owner_user_id
    from public.gate_requirements r
    join rules ru on ru.condition = 'requirement_awaiting_approval'
   where r.project_id = p_project_id
     and private.requirement_status(r.id) = 'awaiting_approval'
     and r.acceptance_confirmed_at < now() - make_interval(days => greatest(ru.threshold_days, 1))

  union all

  -- THE PHASE D GAP. A document that will stop satisfying its requirements
  -- shortly, warned about before it does rather than after.
  select 'document_expiring',
         'controlled_document_version', v.id::text,
         d.document_number || ' expires on ' || v.expiry_date,
         'Version ' || v.version_label || ' is cited as evidence and lapses in '
           || (v.expiry_date - current_date) || ' days. Requirements relying on '
           || 'it will stop being satisfied.',
         d.owner_user_id
    from public.controlled_document_versions v
    join public.controlled_documents d on d.id = v.document_id
    join rules ru on ru.condition = 'document_expiring'
   where v.status in ('approved', 'effective')
     and v.expiry_date is not null
     and v.expiry_date >= current_date
     and v.expiry_date <= current_date + make_interval(days => greatest(ru.threshold_days, 30))
     and exists (
       select 1 from public.evidence_links e
        where e.document_version_id = v.id and e.project_id = p_project_id
     )

  union all

  -- It has already lapsed and something is still relying on it.
  select 'document_expired_in_use',
         'controlled_document_version', v.id::text,
         d.document_number || ' has lapsed and is still cited',
         'Version ' || v.version_label || ' expired on ' || v.expiry_date
           || '. Every requirement citing it is now unsatisfied.',
         d.owner_user_id
    from public.controlled_document_versions v
    join public.controlled_documents d on d.id = v.document_id
    join rules ru on ru.condition = 'document_expired_in_use'
   where v.expiry_date is not null
     and v.expiry_date < current_date
     and exists (
       select 1 from public.evidence_links e
        where e.document_version_id = v.id and e.project_id = p_project_id
     )

  union all

  select 'task_overdue',
         'project_task', t.id::text,
         t.title || ' is overdue',
         'Forecast finish was ' || t.forecast_end || '.',
         t.owner_user_id
    from public.project_tasks t
    join rules ru on ru.condition = 'task_overdue'
   where t.project_id = p_project_id
     and t.actual_end is null
     and t.forecast_end is not null
     and t.forecast_end < current_date - make_interval(days => ru.threshold_days)

  union all

  -- Slipping against the commitment, on the path that moves the end date.
  select 'critical_task_slipping',
         'project_task', t.id::text,
         t.title || ' is slipping on the critical path',
         private.task_variance_days(t.id) || ' days later than the baseline. '
           || 'Every day it slips, the programme slips.',
         t.owner_user_id
    from public.project_tasks t
    join lateral private.task_float_days(t.project_id) f on f.task_id = t.id
    join rules ru on ru.condition = 'critical_task_slipping'
   where t.project_id = p_project_id
     and f.is_critical
     and t.actual_end is null
     and coalesce(private.task_variance_days(t.id), 0) > greatest(ru.threshold_days, 0)

  union all

  -- Not everything worth saying is bad news. A gate that has become reviewable
  -- and is waiting on nobody in particular is exactly the thing that sits
  -- unnoticed for a fortnight.
  select 'gate_ready_for_review',
         'project_stage', s.id::text,
         s.name || ' is ready for review',
         'Every mandatory requirement is satisfied. The gate is waiting on a '
           || 'decision.',
         null::uuid
    from public.project_stages s
    join lateral private.gate_readiness(s.id) rd on true
    join rules ru on ru.condition = 'gate_ready_for_review'
   where s.project_id = p_project_id
     and rd.is_ready
     and s.gate_status = 'ready_for_human_review';
$$;

grant execute on function private.detect_notification_conditions(uuid) to authenticated;

-- --------------------------------------------------------------- the sweep ---
--
-- Raise what is newly true, resolve what has stopped being true. Idempotent by
-- construction: running it twice in a row raises nothing the second time,
-- because the dedup index refuses and the resolver finds nothing stale.

create or replace function private.sweep_notifications(p_project_id uuid)
returns table (raised integer, resolved integer)
language plpgsql
security definer
set search_path = ''
as $$
declare
  n_raised   integer := 0;
  n_resolved integer := 0;
begin
  -- Raise. `on conflict do nothing` leans on notification_events_one_open, so
  -- a condition true for six weeks still has exactly one open event.
  with detected as (
    select d.*, r.id as rule_id, r.severity
      from private.detect_notification_conditions(p_project_id) d
      join public.notification_rules r on r.condition = d.condition
     where r.is_active
  ),
  inserted as (
    insert into public.notification_events
      (rule_id, project_id, subject_type, subject_id, severity, title, detail,
       dedup_key)
    select rule_id, p_project_id, subject_type, subject_id, severity, title,
           detail,
           condition || ':' || subject_id
      from detected
    on conflict do nothing
    returning 1
  )
  select count(*) into n_raised from inserted;

  -- Resolve anything open whose condition is no longer detected. This is the
  -- half that keeps the list readable: an alert that outlives its problem
  -- teaches people to ignore alerts.
  with still_true as (
    select d.condition || ':' || d.subject_id as dedup_key
      from private.detect_notification_conditions(p_project_id) d
  ),
  closed as (
    update public.notification_events e
       set resolved_at = now(),
           resolved_reason = 'The condition is no longer true.'
     where e.project_id = p_project_id
       and e.resolved_at is null
       and e.dedup_key not in (select dedup_key from still_true)
    returning 1
  )
  select count(*) into n_resolved from closed;

  raised := n_raised;
  resolved := n_resolved;
  return next;
end;
$$;

grant execute on function private.sweep_notifications(uuid) to authenticated;

-- ------------------------------------------------------------- escalation ---
--
-- Escalate only when the rule allows it, enough time has passed since the
-- previous rung, and nobody has acknowledged. The elapsed-time condition is the
-- important one: without it an unread notice reaches the executive inside a
-- minute, which is how an escalation ladder becomes a spam cannon.

create or replace function private.escalate_notifications()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  n integer;
begin
  with escalated as (
    update public.notification_events e
       set escalation_level  = e.escalation_level + 1,
           last_escalated_at = now()
      from public.notification_rules r
     where r.id = e.rule_id
       and e.resolved_at is null
       and e.acknowledged_at is null
       and r.escalate_after_hours is not null
       and cardinality(r.escalate_to_roles) > 0
       -- Only one rung. A ladder that climbs by itself is how everyone ends up
       -- on every notification.
       and e.escalation_level = 0
       and coalesce(e.last_escalated_at, e.raised_at)
             < now() - make_interval(hours => r.escalate_after_hours)
    returning 1
  )
  select count(*) into n from escalated;
  return n;
end;
$$;

-- ------------------------------------------------------------ seeded rules ---
--
-- Starting points, not policy. Thresholds and audiences are organisational
-- decisions; these exist so the engine does something sensible on day one and
-- can be tuned without a migration.

insert into public.notification_rules
  (key, name, description, condition, severity, threshold_days, notify_roles,
   escalate_after_hours, escalate_to_roles)
values
  ('requirement_overdue', 'Mandatory requirement overdue',
   'A mandatory gate requirement is past its due date and not satisfied.',
   'requirement_overdue', 'warning', 0,
   '{project_manager}', 72, '{department_head}'),

  ('requirement_awaiting_approval', 'Requirement waiting for approval',
   'Evidence is attached and accepted; only an approval is outstanding.',
   'requirement_awaiting_approval', 'info', 3,
   '{senior_scientist,quality_reviewer}', null, '{}'),

  ('document_expiring', 'Controlled document expiring',
   'A document cited as evidence lapses soon. Requirements relying on it will '
   'stop being satisfied on that date.',
   'document_expiring', 'warning', 30,
   '{project_manager,quality_reviewer}', null, '{}'),

  ('document_expired_in_use', 'Lapsed document still cited',
   'A document past its expiry is still cited as evidence, so the requirements '
   'relying on it are already unsatisfied.',
   'document_expired_in_use', 'critical', 0,
   '{project_manager,quality_reviewer}', 24, '{department_head}'),

  ('task_overdue', 'Task overdue',
   'A task has passed its forecast finish and is not complete.',
   'task_overdue', 'info', 3, '{project_manager}', null, '{}'),

  ('critical_task_slipping', 'Critical path slipping',
   'A task with no float is later than its baseline, so the programme end date '
   'is moving.',
   'critical_task_slipping', 'critical', 5,
   '{project_manager}', 48, '{department_head,executive}'),

  ('gate_ready_for_review', 'Gate ready for review',
   'Every mandatory requirement is satisfied and the gate is waiting on a '
   'decision.',
   'gate_ready_for_review', 'info', 0,
   '{gate_committee_member,project_manager}', null, '{}');

-- ------------------------------------------------------------------ policies ---

alter table public.notification_rules      enable row level security;
alter table public.notification_events     enable row level security;
alter table public.notification_deliveries enable row level security;

create policy notification_rules_read on public.notification_rules
  for select to authenticated using (true);

create policy notification_events_read on public.notification_events
  for select to authenticated
  using (project_id is null or private.can_access_project(project_id));

create policy notification_deliveries_read on public.notification_deliveries
  for select to authenticated
  using (recipient_user_id = (select auth.uid()));
