-- 0030 — "This gate has not been worked on in nine days."
--
-- Every one of the seven existing conditions is about a single item: one
-- requirement overdue, one document expiring, one task slipping. None is about
-- a GATE. So the system could say "G0-CO-001 is overdue" forty-four times and
-- never say the thing somebody actually needs to hear, which is that a gate has
-- stalled.
--
-- The difference matters to whoever reads it. Forty-four item alerts are a list
-- to work through. One gate alert is a fact to act on, and it is what makes
-- "left unattended" visible at all.
--
-- WHAT COUNTS AS ATTENDED
--
-- Any audit event touching the stage or one of its requirements. The audit
-- trail has recorded every approval, every piece of evidence, every due date
-- moved and every status change with an `occurred_at` since 0007 - so "when was
-- this gate last worked on" has been answerable all along and nothing asked.
--
-- Note what it deliberately does NOT count: the alert itself. Raising a
-- notification is not attending to a gate, and if it reset the clock the
-- condition could never fire twice.
--
-- WHY THE WHOLE FUNCTION IS RESTATED
--
-- Postgres has no "append a branch" for a SQL function; `create or replace`
-- takes the whole body, exactly as 0028 restated `trigger_worker_tick`. The
-- body below was taken verbatim from the running database rather than
-- re-typed - a first attempt at re-transcribing it from 0021 silently
-- reintroduced a table name that a later migration had changed, which no
-- compiler would have caught.

-- ------------------------------------------------------- the threshold cascade ---
--
-- One number does not fit every gate. A concept gate may reasonably sit for a
-- fortnight; a gate holding up a clinical batch may not survive three days. But
-- asking somebody to set a value on eight gates per programme guarantees it is
-- never set at all.
--
-- So: a system default that applies everywhere, overridable per gate, with the
-- template carrying the sensible starting point.
--
--   notification_rules.threshold_days              system default
--     -> template_stages.unattended_after_days     per gate of a template
--          -> project_stages.unattended_after_days per gate of a programme
--
-- The template value is COPIED into the stage at instantiation, exactly as
-- name, description, gate_question and exit_criteria already are. That is what
-- 0013's instance layer is for: editing a template must never silently change a
-- programme already running.
--
-- Nullable rather than defaulted, so an inherited value stays distinguishable
-- from a chosen one - which is what lets the UI say "7 days (system default)"
-- rather than implying somebody picked it.

alter table public.template_stages
  add column if not exists unattended_after_days integer
    check (unattended_after_days is null or unattended_after_days > 0);

alter table public.project_stages
  add column if not exists unattended_after_days integer
    check (unattended_after_days is null or unattended_after_days > 0);

comment on column public.project_stages.unattended_after_days is
  'Days without recorded activity before this gate is reported unattended. '
  'Null inherits the system default from notification_rules.threshold_days.';

comment on column public.template_stages.unattended_after_days is
  'Starting value copied into project_stages when a programme is instantiated. '
  'Null means the instance inherits the system default.';

-- ------------------------------------------------------------- the new rule ---

alter table public.notification_rules
  drop constraint if exists notification_rules_condition_check;

alter table public.notification_rules
  add constraint notification_rules_condition_check check (condition in (
    'requirement_overdue',
    'requirement_awaiting_approval',
    'document_expiring',
    'document_expired_in_use',
    'task_overdue',
    'critical_task_slipping',
    'gate_ready_for_review',
    'gate_unattended'
  ));

insert into public.notification_rules
  (key, name, description, condition, severity, threshold_days,
   notify_roles, escalate_after_hours, escalate_to_roles)
values (
  'gate_unattended',
  'Gate left unattended',
  'A gate with outstanding mandatory work that nobody has touched. Raised once '
  'for the gate rather than once per requirement, because the point is that the '
  'gate has stalled.',
  'gate_unattended',
  'warning',
  7,
  array['project_manager'],
  72,
  array['department_head']
)
on conflict (condition) do nothing;

-- ------------------------------------------------------------- the detector ---

CREATE OR REPLACE FUNCTION private.detect_notification_conditions(p_project_id uuid)
 RETURNS TABLE(condition text, subject_type text, subject_id text, title text, detail text, owner_user_id uuid)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
     and s.gate_status = 'ready_for_human_review'

  union all

  -- THE GATE-LEVEL ONE. Open, with mandatory work outstanding, and untouched
  -- for longer than its threshold.
  --
  -- `last_touched` is the audit trail, falling back to when the gate was
  -- created - so a gate made this morning with no history is not immediately
  -- reported as neglected, while one created a fortnight ago and never touched
  -- correctly is.
  --
  -- It deliberately does NOT use `project_stages.updated_at`. That column is
  -- maintained by a trigger on every write to the row, including writes that
  -- are not work on the gate at all: changing this very threshold sets it, so
  -- an administrator adjusting a notification setting would silently reset the
  -- inactivity clock on the gate they were configuring. Measured - the gate
  -- stopped firing immediately after its threshold was edited, and stayed
  -- silent even when the setting was put back.
  select 'gate_unattended',
         'project_stage', s.id::text,
         s.name || ' has not been worked on',
         'No recorded activity for '
           || greatest(extract(day from now() - act.last_touched)::integer, 0)
           || ' day(s), with '
           || (select count(*) from public.gate_requirements r
                where r.project_stage_id = s.id
                  and r.is_mandatory
                  and not private.requirement_is_satisfied(r.id))
           || ' mandatory requirement(s) still outstanding.',
         null::uuid
    from public.project_stages s
    join rules ru on ru.condition = 'gate_unattended'
    join lateral (
      select coalesce(
               (select max(a.occurred_at)
                  from public.audit_events a
                 where a.project_id = s.project_id
                   and (
                     (a.entity_type = 'project_stage' and a.entity_id = s.id::text)
                     or (a.entity_type = 'gate_requirement'
                         and a.entity_id in (
                           select r.id::text from public.gate_requirements r
                            where r.project_stage_id = s.id
                         ))
                   )),
               s.created_at
             ) as last_touched
    ) act on true
   where s.project_id = p_project_id
     and s.gate_status in ('not_started', 'in_progress', 'at_risk',
                           'ready_for_human_review')
     and exists (
       select 1 from public.gate_requirements r
        where r.project_stage_id = s.id
          and r.is_mandatory
          and not private.requirement_is_satisfied(r.id)
     )
     and act.last_touched < now() - make_interval(
           days => greatest(
             coalesce(s.unattended_after_days, ru.threshold_days, 7), 1
           )
         );
$function$;

grant execute on function private.detect_notification_conditions(uuid) to authenticated;
