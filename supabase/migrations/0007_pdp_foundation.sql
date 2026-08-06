-- 0007 — PDP Operations foundation: organisation structure, roles, and the
-- append-only audit trail.
--
-- This is the first migration of the PDP Operations & Stage-Gate Guardian
-- module. It deliberately adds no PDP business tables yet; it establishes who
-- people are, what they may do, and the guarantee that every state change is
-- recorded and cannot be erased.
--
-- The existing `projects` table is EXTENDED rather than duplicated. A project
-- is a project: the research module attaches runs to it, the PDP module
-- attaches stages and gates. That shared row is what lets a completed research
-- run be attached as evidence against a gate requirement.

-- --------------------------------------------------------------- departments ---

create table public.departments (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique check (length(trim(name)) > 0),
  code        text unique,
  head_user_id uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create trigger departments_set_updated_at
  before update on public.departments
  for each row execute function private.set_updated_at();

-- --------------------------------------------------------------------- roles ---
-- Roles are rows rather than an enum so an administrator can add one without a
-- migration. `key` is what code checks against; `name` is what users see.

create table public.roles (
  id          uuid primary key default gen_random_uuid(),
  key         text not null unique check (key ~ '^[a-z_]+$'),
  name        text not null,
  description text,
  -- Segregation of duties: whether holders may approve controlled work.
  can_approve boolean not null default false,
  -- Whether holders may act on a stage gate (approve, reject, hold).
  can_gate    boolean not null default false,
  -- Whether holders see portfolio-wide data rather than only their projects.
  is_portfolio_wide boolean not null default false,
  rank        integer not null default 0,
  created_at  timestamptz not null default now()
);

comment on column public.roles.can_approve is
  'Holders may approve requirements and documents. Enforced at the API layer '
  'and re-checked by the readiness engine; never assumed from the UI.';

insert into public.roles (key, name, description, can_approve, can_gate, is_portfolio_wide, rank) values
  ('junior_scientist',      'Junior Scientist',      'Executes assigned experimental and documentation work.',            false, false, false, 10),
  ('research_associate',    'Research Associate',    'Executes experimental work and drafts technical records.',          false, false, false, 20),
  ('scientist',             'Scientist',             'Owns technical work packages and drafts controlled documents.',     false, false, false, 30),
  ('senior_scientist',      'Senior Scientist',      'Reviews technical work and may approve within their discipline.',   true,  false, false, 40),
  ('formulation_lead',      'Formulation Lead',      'Accountable for formulation development deliverables.',             true,  false, false, 50),
  ('analytical_lead',       'Analytical Lead',       'Accountable for analytical development deliverables.',              true,  false, false, 50),
  ('project_manager',       'Project Manager',       'Owns timeline, dependencies and gate preparation.',                 true,  false, true,  60),
  ('department_head',       'Department Head',       'Accountable for departmental resource and delivery.',               true,  true,  true,  70),
  ('quality_reviewer',      'Quality Reviewer',      'Independent quality review of controlled work.',                    true,  true,  true,  70),
  ('regulatory_reviewer',   'Regulatory Reviewer',   'Independent regulatory review of controlled work.',                 true,  true,  true,  70),
  ('gate_committee_member', 'Gate Committee Member', 'Votes on stage-gate decisions.',                                    true,  true,  true,  80),
  ('training_administrator','Training Administrator','Publishes and assigns approved training.',                          true,  false, true,  50),
  ('executive',             'Executive / MD',        'Portfolio oversight and executive decisions.',                      true,  true,  true,  90),
  ('system_administrator',  'System Administrator',  'Configures templates, roles and system settings.',                  false, false, true,  95),
  ('auditor',               'Auditor',               'Read-only access to records and the audit trail.',                  false, false, true,  99);

-- ----------------------------------------------------------------- user_roles ---
-- A role may be global or scoped to one project. Project scoping is what lets
-- someone be an approver on one programme and a contributor on another.

create table public.user_roles (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  role_id     uuid not null references public.roles(id) on delete cascade,
  project_id  uuid references public.projects(id) on delete cascade,
  department_id uuid references public.departments(id) on delete set null,
  granted_by  uuid references auth.users(id) on delete set null,
  granted_at  timestamptz not null default now(),
  expires_at  timestamptz,
  -- A null project_id means the role applies everywhere. The partial unique
  -- indexes below enforce one grant per (user, role, scope) in both cases,
  -- since NULL never equals NULL in a plain unique constraint.
  constraint user_roles_scope_valid check (project_id is null or department_id is null)
);

create unique index user_roles_global_uniq
  on public.user_roles (user_id, role_id)
  where project_id is null;

create unique index user_roles_project_uniq
  on public.user_roles (user_id, role_id, project_id)
  where project_id is not null;

create index user_roles_user_idx    on public.user_roles (user_id);
create index user_roles_project_idx on public.user_roles (project_id) where project_id is not null;

-- ------------------------------------------------------- profiles extension ---

alter table public.profiles
  add column department_id uuid references public.departments(id) on delete set null,
  add column job_title     text,
  add column is_active     boolean not null default true,
  add column deactivated_at timestamptz;

comment on column public.profiles.is_active is
  'Soft deactivation. Access is denied while false, but the user row is kept so '
  'historical approvals and audit entries continue to resolve to a real person.';

-- -------------------------------------------------------- projects extension ---
-- The existing research `projects` table gains PDP fields. One table, two
-- modules: research runs and stage gates both hang off the same project.

alter table public.projects
  add column department_id     uuid references public.departments(id) on delete set null,
  add column project_manager_id uuid references auth.users(id) on delete set null,
  add column product_type       text,
  add column target_market      text,
  add column pdp_enabled        boolean not null default false,
  add column current_stage_id   uuid,
  add column planned_start_date date,
  add column planned_end_date   date,
  add column actual_start_date  date,
  add column actual_end_date    date,
  add column health             text check (health in ('green', 'amber', 'red')),
  add column archived_at        timestamptz;

comment on column public.projects.pdp_enabled is
  'True once a PDP template has been instantiated. Research-only projects stay '
  'false and never appear in PDP views.';

create index projects_pdp_idx on public.projects (pdp_enabled) where pdp_enabled;

-- ------------------------------------------------------------- audit_events ---
-- Append-only. Every controlled state change lands here.
--
-- Enforcement is threefold: UPDATE and DELETE are revoked from every role
-- including service_role; a trigger raises on any attempt that slips through a
-- future GRANT; and inserts go through private.record_audit_event() so the
-- actor cannot be forged by the caller.

create table public.audit_events (
  id            bigserial primary key,
  occurred_at   timestamptz not null default now(),

  actor_user_id uuid references auth.users(id) on delete set null,
  actor_role    text,
  -- Set when an AI agent acted. A human actor and an agent actor are both
  -- recorded when an agent acted on a human's behalf, so accountability is
  -- never ambiguous.
  actor_agent   text,
  agent_run_id  uuid,
  tool_call_id  text,

  action        text not null,
  entity_type   text not null,
  entity_id     text not null,
  project_id    uuid references public.projects(id) on delete set null,

  previous_value jsonb,
  new_value      jsonb,
  reason         text,

  -- Reference to the human approval that authorised this, where one was needed.
  human_approval_id uuid,

  source_channel text not null default 'api'
    check (source_channel in ('api', 'ui', 'agent', 'worker', 'migration', 'seed')),
  session_metadata jsonb
);

create index audit_events_entity_idx  on public.audit_events (entity_type, entity_id, occurred_at desc);
create index audit_events_project_idx on public.audit_events (project_id, occurred_at desc);
create index audit_events_actor_idx   on public.audit_events (actor_user_id, occurred_at desc);
create index audit_events_action_idx  on public.audit_events (action, occurred_at desc);

comment on table public.audit_events is
  'Append-only. UPDATE and DELETE are revoked from every role and additionally '
  'blocked by a trigger. Write through private.record_audit_event().';

-- Belt and braces: revoke, then block at the trigger level so a future GRANT
-- cannot silently reopen the hole.
revoke update, delete, truncate on public.audit_events from anon, authenticated, service_role;

create or replace function private.reject_audit_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'audit_events is append-only; % is not permitted', tg_op
    using errcode = 'insufficient_privilege';
end;
$$;

create trigger audit_events_no_update
  before update on public.audit_events
  for each row execute function private.reject_audit_mutation();

create trigger audit_events_no_delete
  before delete on public.audit_events
  for each row execute function private.reject_audit_mutation();

-- The only supported way to write an audit event. Taking the actor as an
-- explicit argument rather than reading auth.uid() lets the backend record the
-- verified user from its JWT while running under the service role.
create or replace function private.record_audit_event(
  p_action        text,
  p_entity_type   text,
  p_entity_id     text,
  p_actor_user_id uuid    default null,
  p_actor_role    text    default null,
  p_project_id    uuid    default null,
  p_previous      jsonb   default null,
  p_new           jsonb   default null,
  p_reason        text    default null,
  p_actor_agent   text    default null,
  p_agent_run_id  uuid    default null,
  p_tool_call_id  text    default null,
  p_approval_id   uuid    default null,
  p_source        text    default 'api',
  p_session       jsonb   default null
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  new_id bigint;
begin
  insert into public.audit_events (
    actor_user_id, actor_role, actor_agent, agent_run_id, tool_call_id,
    action, entity_type, entity_id, project_id,
    previous_value, new_value, reason, human_approval_id,
    source_channel, session_metadata
  ) values (
    p_actor_user_id, p_actor_role, p_actor_agent, p_agent_run_id, p_tool_call_id,
    p_action, p_entity_type, p_entity_id, p_project_id,
    p_previous, p_new, p_reason, p_approval_id,
    p_source, p_session
  )
  returning id into new_id;

  return new_id;
end;
$$;

-- --------------------------------------------------------- access predicates ---

-- Whether a user may see a project at all. Portfolio-wide roles see everything;
-- everyone else sees projects they own or hold a project-scoped role on.
create or replace function private.can_access_project(target_project_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.projects p
     where p.id = target_project_id
       and p.user_id = (select auth.uid())
  )
  or exists (
    select 1
      from public.user_roles ur
      join public.roles r on r.id = ur.role_id
     where ur.user_id = (select auth.uid())
       and (ur.expires_at is null or ur.expires_at > now())
       and (r.is_portfolio_wide or ur.project_id = target_project_id)
  );
$$;

-- Whether a user currently holds a role, optionally scoped to a project.
create or replace function private.has_role(
  role_key text,
  target_project_id uuid default null
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.user_roles ur
      join public.roles r on r.id = ur.role_id
     where ur.user_id = (select auth.uid())
       and r.key = role_key
       and (ur.expires_at is null or ur.expires_at > now())
       and (ur.project_id is null or ur.project_id = target_project_id)
  );
$$;

grant execute on function private.can_access_project(uuid) to authenticated;
grant execute on function private.has_role(text, uuid) to authenticated;

-- ------------------------------------------------------------------ policies ---

alter table public.departments  enable row level security;
alter table public.roles        enable row level security;
alter table public.user_roles   enable row level security;
alter table public.audit_events enable row level security;

-- Departments and roles are reference data: readable by any signed-in user,
-- writable only through the backend service role.
create policy departments_read on public.departments
  for select to authenticated using (true);

create policy roles_read on public.roles
  for select to authenticated using (true);

-- A user may see their own role grants, and holders of portfolio-wide roles may
-- see all of them.
create policy user_roles_read on public.user_roles
  for select to authenticated
  using (
    user_id = (select auth.uid())
    or exists (
      select 1 from public.user_roles ur
        join public.roles r on r.id = ur.role_id
       where ur.user_id = (select auth.uid()) and r.is_portfolio_wide
    )
  );

-- Audit is readable for projects you can access. It is never writable through
-- RLS at all: no INSERT, UPDATE or DELETE policy exists, so the only path is
-- private.record_audit_event() under the service role.
create policy audit_events_read on public.audit_events
  for select to authenticated
  using (project_id is null or private.can_access_project(project_id));
