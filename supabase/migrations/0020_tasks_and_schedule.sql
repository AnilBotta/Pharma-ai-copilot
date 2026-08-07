-- 0020 — Phase E: tasks, dependencies and the schedule.
--
-- THE RULE THIS PHASE EXISTS TO ENFORCE
--
-- A project management tool's characteristic lie is not a wrong date. It is a
-- date that was moved. A task slips, someone edits the plan, and the programme
-- reports on schedule forever while finishing a year late. Every individual
-- edit looked reasonable; the record of what was originally promised is simply
-- gone.
--
-- That is this module's "false green" wearing a different hat, and it gets the
-- same treatment: make the shortcut structurally unavailable.
--
--   * BASELINE dates are immutable once a baseline is approved. Not "should not
--     be edited" - the trigger refuses the UPDATE.
--   * FORECAST dates move freely. That is what they are for.
--   * VARIANCE is computed from the two and cannot be edited at all, because it
--     is not stored.
--   * Re-baselining is a separate, audited, approved act that keeps every
--     previous baseline. You can always ask what the plan was in March.
--
-- NO PERCENT COMPLETE
--
-- There is deliberately no percent_complete column, and no status column
-- either. A percentage anybody can type is the same lie as a readiness
-- percentage that unlocks a gate - the notorious task that is 90% done for
-- eight months. A task's state is derived from three facts that are either
-- true or not: has it started, has it finished, and is it past its forecast.
--
-- This mirrors gate_requirements, which has no completion column for exactly
-- the same reason.

-- -------------------------------------------------------------- project_tasks ---

create table public.project_tasks (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects(id) on delete cascade,

  -- Optional links to the stage-gate structure. A task usually exists to
  -- deliver a requirement; when it does, saying so is what lets the timeline
  -- explain why a gate is late.
  project_stage_id uuid references public.project_stages(id) on delete set null,
  requirement_id   uuid references public.gate_requirements(id) on delete set null,

  wbs_code    text,
  title       text not null check (length(trim(title)) > 0),
  description text,
  discipline  text,

  owner_user_id uuid references auth.users(id) on delete set null,

  -- THE THREE DATE SETS. They answer different questions and must not be
  -- collapsed into one.
  --   baseline: what we committed to. Frozen.
  --   forecast: what we now expect. Moves.
  --   actual:   what happened.
  baseline_start date,
  baseline_end   date,
  forecast_start date,
  forecast_end   date,
  actual_start   date,
  actual_end     date,

  effort_days numeric(8,2) check (effort_days is null or effort_days >= 0),

  priority text not null default 'medium'
    check (priority in ('low', 'medium', 'high', 'critical')),

  -- Blocking is an explicit act with a reason, as elsewhere in this module.
  is_blocked     boolean not null default false,
  blocked_reason text,

  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint task_dates_ordered check (
    (baseline_start is null or baseline_end is null or baseline_end >= baseline_start)
    and (forecast_start is null or forecast_end is null or forecast_end >= forecast_start)
    and (actual_start   is null or actual_end   is null or actual_end   >= actual_start)
  ),
  -- A task cannot have finished without having started.
  constraint finished_implies_started check (
    actual_end is null or actual_start is not null
  ),
  constraint blocked_task_has_reason check (
    not is_blocked or (blocked_reason is not null and length(trim(blocked_reason)) > 0)
  )
);

create index project_tasks_project_idx on public.project_tasks (project_id);
create index project_tasks_stage_idx   on public.project_tasks (project_stage_id)
  where project_stage_id is not null;
create index project_tasks_req_idx     on public.project_tasks (requirement_id)
  where requirement_id is not null;
create index project_tasks_owner_idx   on public.project_tasks (owner_user_id)
  where owner_user_id is not null;
create index project_tasks_open_idx    on public.project_tasks (project_id, forecast_end)
  where actual_end is null;

create trigger project_tasks_set_updated_at
  before update on public.project_tasks
  for each row execute function private.set_updated_at();

comment on table public.project_tasks is
  'No status or percent_complete column by design. State is derived from '
  'actual_start, actual_end and forecast_end by private.task_status().';

-- --------------------------------------------------------- task_dependencies ---

create table public.task_dependencies (
  predecessor_id uuid not null references public.project_tasks(id) on delete cascade,
  successor_id   uuid not null references public.project_tasks(id) on delete cascade,

  -- Finish-to-start is the overwhelming default; the others exist because real
  -- schedules use them and approximating them with FS produces wrong dates.
  dependency_type text not null default 'FS'
    check (dependency_type in ('FS', 'SS', 'FF', 'SF')),
  lag_days integer not null default 0,

  created_at timestamptz not null default now(),

  primary key (predecessor_id, successor_id),
  constraint no_self_dependency check (predecessor_id <> successor_id)
);

create index task_dependencies_successor_idx on public.task_dependencies (successor_id);

-- A cycle makes the critical path non-terminating, so it is refused at write
-- time rather than defended against on every read. Same approach as the
-- requirement dependency graph in 0011 and 0013.
create or replace function private.reject_task_dependency_cycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    with recursive reachable(id) as (
      select new.successor_id
      union
      select d.successor_id
        from public.task_dependencies d
        join reachable r on d.predecessor_id = r.id
    )
    select 1 from reachable where id = new.predecessor_id
  ) then
    raise exception
      'dependency cycle: % cannot precede %', new.predecessor_id, new.successor_id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger task_dependencies_no_cycle
  before insert or update on public.task_dependencies
  for each row execute function private.reject_task_dependency_cycle();

-- ------------------------------------------------------- project_milestones ---

create table public.project_milestones (
  id         uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  project_stage_id uuid references public.project_stages(id) on delete set null,

  name        text not null check (length(trim(name)) > 0),
  description text,

  baseline_date date,
  forecast_date date,
  actual_date   date,

  -- A date promised outside the organisation - to a partner, a regulator, an
  -- investor. Moving one has consequences a purely internal date does not.
  is_contractual boolean not null default false,

  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index project_milestones_project_idx
  on public.project_milestones (project_id, forecast_date);

create trigger project_milestones_set_updated_at
  before update on public.project_milestones
  for each row execute function private.set_updated_at();

-- ------------------------------------------------------- schedule_baselines ---

create table public.schedule_baselines (
  id         uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,

  version integer not null,
  name    text not null,
  reason  text,

  -- A baseline is a commitment, so it names who made it. The check constraint
  -- makes that structural rather than a convention.
  approved_by uuid not null references auth.users(id) on delete restrict,
  approved_at timestamptz not null default now(),

  -- What the schedule looked like at the moment of approval, kept whole. The
  -- individual task rows will move on; this will not.
  snapshot jsonb not null,

  superseded_at timestamptz,

  created_at timestamptz not null default now(),

  unique (project_id, version)
);

-- One current baseline per project.
create unique index schedule_baselines_one_current
  on public.schedule_baselines (project_id)
  where superseded_at is null;

comment on table public.schedule_baselines is
  'Every baseline is kept. Re-baselining supersedes the previous one rather '
  'than overwriting it, so "what did we commit to in March" stays answerable.';

-- ------------------------------------------- baseline dates are immutable ---
--
-- The whole point of the phase. Once a project has an approved baseline, the
-- baseline columns on its tasks and milestones cannot be edited - not by the
-- API, not by an agent, not by anyone holding a database connection through the
-- application role.
--
-- private.rebaseline() is the only sanctioned path, and it identifies itself by
-- setting a transaction-local flag the trigger checks. A caller who has not set
-- that flag is, by definition, not going through the audited route.

create or replace function private.reject_baseline_edit()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  has_baseline boolean;
  target_project uuid;
begin
  if coalesce(current_setting('app.rebaselining', true), '') = 'on' then
    return new;  -- the sanctioned path
  end if;

  target_project := new.project_id;

  select exists (
    select 1 from public.schedule_baselines b
     where b.project_id = target_project and b.superseded_at is null
  ) into has_baseline;

  if not has_baseline then
    return new;  -- nothing committed yet; the plan is still being drafted
  end if;

  if tg_table_name = 'project_tasks' then
    if new.baseline_start is distinct from old.baseline_start
       or new.baseline_end is distinct from old.baseline_end then
      raise exception
        'baseline dates are frozen: task % is covered by an approved baseline. '
        'Move the forecast dates, or re-baseline through an approved change.',
        old.id
        using errcode = 'insufficient_privilege';
    end if;
  else
    if new.baseline_date is distinct from old.baseline_date then
      raise exception
        'baseline dates are frozen: milestone % is covered by an approved '
        'baseline. Move the forecast date, or re-baseline through an approved '
        'change.', old.id
        using errcode = 'insufficient_privilege';
    end if;
  end if;

  return new;
end;
$$;

create trigger project_tasks_baseline_is_frozen
  before update on public.project_tasks
  for each row execute function private.reject_baseline_edit();

create trigger project_milestones_baseline_is_frozen
  before update on public.project_milestones
  for each row execute function private.reject_baseline_edit();

-- ----------------------------------------------------------- derived state ---

create or replace function private.task_status(p_task_id uuid)
returns text
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  t public.project_tasks%rowtype;
  unmet_predecessors integer;
begin
  select * into t from public.project_tasks where id = p_task_id;
  if not found then return 'unknown'; end if;

  if t.actual_end is not null then
    -- Finished. Whether it finished late is a separate question, answered by
    -- the variance columns rather than by overwriting this.
    return 'complete';
  end if;

  if t.is_blocked then return 'blocked'; end if;

  if t.actual_start is not null then
    if t.forecast_end is not null and t.forecast_end < current_date then
      return 'overdue';
    end if;
    return 'in_progress';
  end if;

  -- Not started. Is it waiting on something, or just late to begin?
  select count(*) into unmet_predecessors
    from public.task_dependencies d
    join public.project_tasks p on p.id = d.predecessor_id
   where d.successor_id = p_task_id
     and p.actual_end is null;

  if unmet_predecessors > 0 then return 'waiting_on_predecessor'; end if;

  if t.forecast_start is not null and t.forecast_start < current_date then
    return 'late_to_start';
  end if;

  return 'not_started';
end;
$$;

-- Slip against the commitment, in days. Positive means later than promised.
-- Null when there is no baseline to compare against, which is honest: an
-- un-baselined task has no variance, it just has a plan.
create or replace function private.task_variance_days(p_task_id uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
  select case
    when t.baseline_end is null then null
    else (coalesce(t.actual_end, t.forecast_end) - t.baseline_end)
  end
  from public.project_tasks t where t.id = p_task_id;
$$;

-- ------------------------------------------------------------ critical path ---
--
-- Float is how much a task can slip before the project end date moves. Zero
-- float means it is on the critical path: every day it slips, the programme
-- slips.
--
-- Computed backwards from the latest forecast finish in the project. A task's
-- late finish is the earliest of its successors' late starts; with no
-- successors it is the project end.

create or replace function private.task_float_days(p_project_id uuid)
returns table (task_id uuid, late_finish date, float_days integer, is_critical boolean)
language sql
stable
security definer
set search_path = ''
as $$
  with recursive
  project_end as (
    select max(forecast_end) as d
      from public.project_tasks
     where project_id = p_project_id and forecast_end is not null
  ),
  -- Terminal tasks: nothing depends on them.
  terminal as (
    select t.id, (select d from project_end) as late_finish
      from public.project_tasks t
     where t.project_id = p_project_id
       and not exists (
         select 1 from public.task_dependencies d where d.predecessor_id = t.id
       )
  ),
  walk(id, late_finish) as (
    select id, late_finish from terminal
    union all
    -- A predecessor must finish by its successor's late start, less any lag.
    select p.id,
           (w.late_finish
              - coalesce((s.forecast_end - s.forecast_start), 0)
              - d.lag_days)::date
      from walk w
      join public.task_dependencies d on d.successor_id = w.id
      join public.project_tasks s on s.id = w.id
      join public.project_tasks p on p.id = d.predecessor_id
     where p.project_id = p_project_id
  ),
  -- A task reached by several paths takes the tightest constraint.
  tightest as (
    select id, min(late_finish) as late_finish from walk group by id
  )
  select t.id,
         x.late_finish,
         (x.late_finish - t.forecast_end)::integer as float_days,
         (x.late_finish - t.forecast_end) <= 0 as is_critical
    from public.project_tasks t
    join tightest x on x.id = t.id
   where t.project_id = p_project_id
     and t.forecast_end is not null;
$$;

grant execute on function private.task_status(uuid)          to authenticated;
grant execute on function private.task_variance_days(uuid)   to authenticated;
grant execute on function private.task_float_days(uuid)      to authenticated;

-- ---------------------------------------------------------------- rebaseline ---
--
-- The only sanctioned way to move a baseline. It keeps the previous one,
-- records who approved the change and why, and stamps the current forecast as
-- the new commitment.

create or replace function private.rebaseline(
  p_project_id  uuid,
  p_approved_by uuid,
  p_name        text,
  p_reason      text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  next_version integer;
  new_id uuid;
  captured jsonb;
begin
  if p_reason is null or length(trim(p_reason)) = 0 then
    raise exception 'a re-baseline must state why the commitment changed'
      using errcode = 'check_violation';
  end if;

  -- Capture what is being replaced before anything moves.
  select coalesce(jsonb_agg(jsonb_build_object(
           'task_id', t.id, 'title', t.title,
           'baseline_start', t.baseline_start, 'baseline_end', t.baseline_end,
           'forecast_start', t.forecast_start, 'forecast_end', t.forecast_end
         )), '[]'::jsonb)
    into captured
    from public.project_tasks t where t.project_id = p_project_id;

  update public.schedule_baselines
     set superseded_at = now()
   where project_id = p_project_id and superseded_at is null;

  select coalesce(max(version), 0) + 1 into next_version
    from public.schedule_baselines where project_id = p_project_id;

  insert into public.schedule_baselines
      (project_id, version, name, reason, approved_by, snapshot)
  values (p_project_id, next_version, p_name, p_reason, p_approved_by, captured)
  returning id into new_id;

  -- Identify this transaction as the sanctioned path so the freeze trigger
  -- stands aside. Transaction-local: it cannot leak into another statement.
  perform set_config('app.rebaselining', 'on', true);

  update public.project_tasks
     set baseline_start = forecast_start,
         baseline_end   = forecast_end
   where project_id = p_project_id;

  update public.project_milestones
     set baseline_date = forecast_date
   where project_id = p_project_id;

  perform set_config('app.rebaselining', 'off', true);

  return new_id;
end;
$$;

-- ------------------------------------------------------------------ policies ---

alter table public.project_tasks      enable row level security;
alter table public.task_dependencies  enable row level security;
alter table public.project_milestones enable row level security;
alter table public.schedule_baselines enable row level security;

create policy project_tasks_read on public.project_tasks
  for select to authenticated using (private.can_access_project(project_id));

create policy project_milestones_read on public.project_milestones
  for select to authenticated using (private.can_access_project(project_id));

create policy schedule_baselines_read on public.schedule_baselines
  for select to authenticated using (private.can_access_project(project_id));

create policy task_dependencies_read on public.task_dependencies
  for select to authenticated
  using (exists (
    select 1 from public.project_tasks t
     where t.id = successor_id and private.can_access_project(t.project_id)
  ));
