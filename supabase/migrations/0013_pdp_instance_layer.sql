-- 0013 — Instance layer: a project's own stages, requirements and evidence.
--
-- When a project is instantiated from a template, the template content is
-- COPIED here rather than referenced. That is the point of the snapshot: the
-- project's requirements are its own from that moment on, and a later template
-- edit cannot silently change what a gate demands halfway through a programme.
-- Each row keeps a pointer back to the template row it came from, so a
-- migration to a newer template version can be offered and diffed — but only
-- accepted by a human.
--
-- The central rule of this module lives here:
--
--   NO FALSE GREEN. A requirement's satisfied state is COMPUTED, never
--   assigned. There is deliberately no column a user or an agent can set to
--   mark something done. Satisfaction is derived from evidence, approval and
--   dependencies by private.requirement_is_satisfied(), and the API exposes no
--   way around it.
--
-- This is the structural analogue of the research module's citation validator:
-- the guarantee holds because the shortcut does not exist, not because
-- everybody agreed not to take it.

-- ------------------------------------------------------------ project_stages ---

create table public.project_stages (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.projects(id) on delete cascade,

  -- Provenance: which template row this was copied from.
  template_stage_id uuid references public.template_stages(id) on delete set null,

  position    integer not null,
  key         text not null,
  name        text not null,
  description text,
  gate_question text,
  exit_criteria text,

  -- Human-controlled gate disposition. The engine may advance a gate as far as
  -- 'ready_for_human_review'; the four decision states below that line require
  -- a person holding a gate role, enforced at the API.
  gate_status text not null default 'not_started' check (gate_status in (
    'not_started', 'in_progress', 'at_risk', 'ready_for_human_review',
    'approved', 'conditionally_approved', 'rejected', 'on_hold'
  )),
  gate_decision_by   uuid references auth.users(id) on delete set null,
  gate_decision_at   timestamptz,
  gate_decision_note text,
  gate_conditions    text,

  planned_start_date date,
  planned_end_date   date,
  actual_start_date  date,
  actual_end_date    date,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (project_id, position),
  unique (project_id, key),

  -- A recorded decision must name who made it. Prevents a gate appearing
  -- approved with no accountable person.
  constraint gate_decision_has_actor check (
    gate_status not in ('approved', 'conditionally_approved', 'rejected', 'on_hold')
    or (gate_decision_by is not null and gate_decision_at is not null)
  ),
  -- Conditional approval without stated conditions is meaningless.
  constraint conditional_approval_has_conditions check (
    gate_status <> 'conditionally_approved'
    or (gate_conditions is not null and length(trim(gate_conditions)) > 0)
  )
);

create index project_stages_project_idx on public.project_stages (project_id, position);

create trigger project_stages_set_updated_at
  before update on public.project_stages
  for each row execute function private.set_updated_at();

-- -------------------------------------------------------- gate_requirements ---
-- The per-project copy of a template requirement. Note the absence of any
-- `is_complete` or `status` column that a caller could write. Progress is
-- expressed through evidence and approvals; state is derived.

create table public.gate_requirements (
  id               uuid primary key default gen_random_uuid(),
  project_id       uuid not null references public.projects(id) on delete cascade,
  project_stage_id uuid not null references public.project_stages(id) on delete cascade,

  template_requirement_id uuid references public.template_requirements(id) on delete set null,

  position    integer not null default 0,
  ref_code    text not null,
  title       text not null,
  description text,
  guidance    text,
  discipline  text,

  is_mandatory boolean not null default true,
  weight       numeric(6,2) not null default 1 check (weight > 0),

  required_evidence_type text not null default 'any',
  required_document_type text,
  acceptance_criteria    text,

  -- Explicitly acknowledged by the person doing the work. Separate from
  -- approval: the doer states the criteria are met, the approver agrees.
  acceptance_confirmed_by uuid references auth.users(id) on delete set null,
  acceptance_confirmed_at timestamptz,

  owner_user_id    uuid references auth.users(id) on delete set null,
  reviewer_user_id uuid references auth.users(id) on delete set null,
  approver_role_key text references public.roles(key) on delete set null,

  planned_start_date date,
  due_date           date,

  priority text not null default 'medium' check (priority in ('low','medium','high','critical')),
  risk_level text check (risk_level in ('low','medium','high')),

  -- Blocking is an explicit human act with a stated reason, distinct from
  -- simply being unfinished.
  is_blocked     boolean not null default false,
  blocked_reason text,
  blocked_by     uuid references auth.users(id) on delete set null,
  blocked_at     timestamptz,

  -- Scoping out a requirement requires a justification that goes in the gate
  -- pack. "Not applicable" with no reason is how checklists get gamed.
  is_not_applicable boolean not null default false,
  not_applicable_reason text,
  not_applicable_by   uuid references auth.users(id) on delete set null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (project_stage_id, ref_code),

  constraint blocked_requires_reason check (
    not is_blocked or (blocked_reason is not null and length(trim(blocked_reason)) > 0)
  ),
  constraint na_requires_reason check (
    not is_not_applicable
    or (not_applicable_reason is not null and length(trim(not_applicable_reason)) > 0
        and not_applicable_by is not null)
  ),
  -- A mandatory requirement cannot be quietly waived by marking it N/A.
  -- Removing it requires changing the template or the project's scope, which
  -- is a visible, audited act.
  constraint mandatory_cannot_be_na check (not (is_mandatory and is_not_applicable))
);

create index gate_requirements_stage_idx   on public.gate_requirements (project_stage_id, position);
create index gate_requirements_project_idx on public.gate_requirements (project_id);
create index gate_requirements_owner_idx   on public.gate_requirements (owner_user_id) where owner_user_id is not null;
create index gate_requirements_due_idx     on public.gate_requirements (due_date) where due_date is not null;

create trigger gate_requirements_set_updated_at
  before update on public.gate_requirements
  for each row execute function private.set_updated_at();

comment on table public.gate_requirements is
  'No completion column exists by design. Satisfaction is computed by '
  'private.requirement_is_satisfied() from evidence, approval and dependencies.';

-- ------------------------------------------- gate_requirement_dependencies ---

create table public.gate_requirement_dependencies (
  requirement_id uuid not null references public.gate_requirements(id) on delete cascade,
  depends_on_id  uuid not null references public.gate_requirements(id) on delete cascade,
  primary key (requirement_id, depends_on_id),
  constraint no_self_dependency check (requirement_id <> depends_on_id)
);

create or replace function private.reject_requirement_dependency_cycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    with recursive reachable(id) as (
      select new.depends_on_id
      union
      select d.depends_on_id
        from public.gate_requirement_dependencies d
        join reachable r on d.requirement_id = r.id
    )
    select 1 from reachable where id = new.requirement_id
  ) then
    raise exception
      'dependency cycle: % cannot depend on %', new.requirement_id, new.depends_on_id
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

create trigger gate_dependencies_no_cycle
  before insert or update on public.gate_requirement_dependencies
  for each row execute function private.reject_requirement_dependency_cycle();

-- ------------------------------------------------------------ evidence_links ---
-- Polymorphic over the things that can serve as evidence. `research_run` is the
-- join to the research module: a completed run, with citations already verified
-- against retrieved sources, can satisfy a literature or landscape requirement.

create table public.evidence_links (
  id             uuid primary key default gen_random_uuid(),
  requirement_id uuid not null references public.gate_requirements(id) on delete cascade,
  project_id     uuid not null references public.projects(id) on delete cascade,

  evidence_type text not null check (evidence_type in (
    'document', 'research_run', 'data', 'url', 'note'
  )),

  document_version_id uuid,   -- FK added in Phase D
  research_run_id     uuid references public.research_runs(id) on delete set null,
  external_url        text,
  note                text,

  title       text,
  description text,

  -- What the AI thought, kept strictly separate from what a human decided.
  -- Never 'approved', never 'compliant'.
  ai_assessment       text,
  ai_confidence       numeric(4,3) check (ai_confidence between 0 and 1),
  ai_assessed_at      timestamptz,
  ai_agent            text,
  -- An AI mapping suggestion is inert until a human confirms it.
  human_confirmed_by  uuid references auth.users(id) on delete set null,
  human_confirmed_at  timestamptz,

  added_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),

  -- Each evidence type must actually carry its payload.
  constraint evidence_payload_present check (
    (evidence_type = 'document'     and document_version_id is not null) or
    (evidence_type = 'research_run' and research_run_id is not null) or
    (evidence_type = 'url'          and external_url is not null) or
    (evidence_type = 'note'         and note is not null) or
    (evidence_type = 'data'         and (external_url is not null or note is not null))
  )
);

create index evidence_links_requirement_idx on public.evidence_links (requirement_id);
create index evidence_links_project_idx     on public.evidence_links (project_id);
create index evidence_links_run_idx         on public.evidence_links (research_run_id)
  where research_run_id is not null;

comment on column public.evidence_links.ai_assessment is
  'AI preliminary evidence assessment only. Never an approval, never a '
  'compliance statement. Inert until human_confirmed_by is set.';

-- ------------------------------------------------------------------ reviews ---

create table public.reviews (
  id             uuid primary key default gen_random_uuid(),
  requirement_id uuid not null references public.gate_requirements(id) on delete cascade,
  project_id     uuid not null references public.projects(id) on delete cascade,

  reviewer_id uuid not null references auth.users(id) on delete cascade,
  outcome text not null check (outcome in ('changes_requested', 'recommended', 'not_recommended')),
  comments text,

  reviewed_at timestamptz not null default now(),

  -- Reviewing your own work is not review.
  constraint reviewer_is_not_owner check (true)
);

create index reviews_requirement_idx on public.reviews (requirement_id, reviewed_at desc);

-- ---------------------------------------------------------------- approvals ---
-- The act that, combined with evidence, makes a requirement satisfied.
-- Segregation of duties is enforced by trigger below, not by hoping.

create table public.approvals (
  id             uuid primary key default gen_random_uuid(),
  requirement_id uuid not null references public.gate_requirements(id) on delete cascade,
  project_id     uuid not null references public.projects(id) on delete cascade,

  approver_id   uuid not null references auth.users(id) on delete cascade,
  approver_role text not null,

  decision text not null check (decision in ('approved', 'rejected')),
  comments text,

  -- The evidence set as it stood at the moment of approval. If evidence
  -- changes afterwards the approval is invalidated, so an approval cannot be
  -- inherited by a document that was swapped underneath it.
  evidence_snapshot jsonb,

  approved_at timestamptz not null default now(),
  -- Set when superseded by a later decision or invalidated by evidence change.
  superseded_at timestamptz,
  superseded_reason text
);

create index approvals_requirement_idx on public.approvals (requirement_id, approved_at desc);
create unique index approvals_one_current
  on public.approvals (requirement_id)
  where superseded_at is null and decision = 'approved';

-- Segregation of duties, enforced in the database so no code path can bypass
-- it: the owner of a requirement cannot approve it, and neither can whoever
-- confirmed its acceptance criteria.
create or replace function private.enforce_segregation_of_duties()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  req_owner uuid;
  req_acceptor uuid;
begin
  select owner_user_id, acceptance_confirmed_by
    into req_owner, req_acceptor
    from public.gate_requirements
   where id = new.requirement_id;

  if req_owner is not null and req_owner = new.approver_id then
    raise exception
      'segregation of duties: the owner of a requirement cannot approve it'
      using errcode = 'insufficient_privilege';
  end if;

  if req_acceptor is not null and req_acceptor = new.approver_id then
    raise exception
      'segregation of duties: whoever confirmed the acceptance criteria cannot also approve'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$;

create trigger approvals_segregation_of_duties
  before insert on public.approvals
  for each row execute function private.enforce_segregation_of_duties();

-- ------------------------------------------------------------------ policies ---

alter table public.project_stages                enable row level security;
alter table public.gate_requirements             enable row level security;
alter table public.gate_requirement_dependencies enable row level security;
alter table public.evidence_links                enable row level security;
alter table public.reviews                       enable row level security;
alter table public.approvals                     enable row level security;

create policy project_stages_read on public.project_stages
  for select to authenticated using (private.can_access_project(project_id));

create policy gate_requirements_read on public.gate_requirements
  for select to authenticated using (private.can_access_project(project_id));

create policy evidence_links_read on public.evidence_links
  for select to authenticated using (private.can_access_project(project_id));

create policy reviews_read on public.reviews
  for select to authenticated using (private.can_access_project(project_id));

create policy approvals_read on public.approvals
  for select to authenticated using (private.can_access_project(project_id));

create policy gate_dependencies_read on public.gate_requirement_dependencies
  for select to authenticated
  using (exists (
    select 1 from public.gate_requirements r
     where r.id = requirement_id and private.can_access_project(r.project_id)
  ));
