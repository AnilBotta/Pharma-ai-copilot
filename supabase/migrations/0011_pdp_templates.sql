-- 0011 — PDP template layer: the reusable stage-gate blueprint.
--
-- Two ideas carry the design.
--
-- VERSIONING. A template row *is* a version. `template_key` groups versions and
-- `version` orders them, so "sterile injectable v3" is a distinct row from v2.
-- Projects are instantiated from a specific version row and remember which one.
-- Editing a template therefore cannot reach back and mutate a live project; a
-- newer version is published and existing projects are offered a migration they
-- must accept. Silent mutation of a project mid-flight is exactly what would
-- destroy trust in a gate decision.
--
-- APPROVAL BEFORE USE. A template cannot be instantiated until a human has
-- approved it. The seeded Gate 0-7 content is structurally complete but is
-- scaffolding, not regulatory advice: which requirements are genuinely mandatory
-- for a given product is domain knowledge that must come from the organisation's
-- scientific, quality and regulatory people. Enforcing approval in the schema
-- makes that a gate rather than a suggestion.

-- -------------------------------------------------------------- pdp_templates ---

create table public.pdp_templates (
  id            uuid primary key default gen_random_uuid(),

  -- Groups versions of the same logical template.
  template_key  text not null check (template_key ~ '^[a-z0-9_]+$'),
  version       integer not null default 1 check (version > 0),

  name          text not null check (length(trim(name)) > 0),
  description   text,

  product_type  text not null default 'general' check (product_type in (
    'general', 'new_chemical_entity', 'generic', 'peptide', 'biologic',
    'tablet_capsule', 'sterile_injectable', 'depot_injection',
    'modified_release', 'topical', 'combination_product', 'other'
  )),

  status text not null default 'draft' check (status in ('draft', 'active', 'archived')),

  -- A template is unusable until a human with authority approves it.
  approved_by uuid references auth.users(id) on delete set null,
  approved_at timestamptz,
  approval_note text,

  is_default  boolean not null default false,
  created_by  uuid references auth.users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  unique (template_key, version),

  constraint template_active_requires_approval check (
    status <> 'active' or (approved_by is not null and approved_at is not null)
  )
);

-- At most one active version per template key.
create unique index pdp_templates_one_active
  on public.pdp_templates (template_key)
  where status = 'active';

-- At most one default template overall, used when a project names none.
create unique index pdp_templates_one_default
  on public.pdp_templates ((true))
  where is_default and status = 'active';

create index pdp_templates_product_type_idx on public.pdp_templates (product_type, status);

create trigger pdp_templates_set_updated_at
  before update on public.pdp_templates
  for each row execute function private.set_updated_at();

comment on constraint template_active_requires_approval on public.pdp_templates is
  'A template cannot become active without a recorded human approval. Seeded '
  'content is scaffolding, not regulatory advice, and must be reviewed by the '
  'organisation before use.';

-- ------------------------------------------------------------ template_stages ---

create table public.template_stages (
  id           uuid primary key default gen_random_uuid(),
  template_id  uuid not null references public.pdp_templates(id) on delete cascade,

  position     integer not null check (position >= 0),
  key          text not null check (key ~ '^[a-z0-9_]+$'),
  name         text not null,
  description  text,

  -- The decision this gate exists to make. Shown at the top of the gate
  -- workspace, because a gate without a stated question becomes a checklist
  -- ritual.
  gate_question text,
  exit_criteria text,

  created_at   timestamptz not null default now(),

  unique (template_id, position),
  unique (template_id, key)
);

create index template_stages_template_idx on public.template_stages (template_id, position);

-- ------------------------------------------------------ template_requirements ---

create table public.template_requirements (
  id                uuid primary key default gen_random_uuid(),
  template_stage_id uuid not null references public.template_stages(id) on delete cascade,

  position          integer not null default 0,
  -- Stable human-readable reference such as G1-FD-003. Survives renaming and is
  -- what people cite in meetings.
  ref_code          text not null check (ref_code ~ '^[A-Z0-9-]+$'),

  title             text not null check (length(trim(title)) > 0),
  description       text,
  guidance          text,

  discipline text check (discipline in (
    'formulation', 'analytical', 'quality', 'regulatory', 'clinical',
    'nonclinical', 'manufacturing', 'intellectual_property', 'commercial',
    'project_management', 'other'
  )),

  is_mandatory boolean not null default true,
  weight       numeric(6,2) not null default 1 check (weight > 0),

  -- What kind of evidence satisfies this. 'research_run' is the join to the
  -- research module: a completed run with verified citations can satisfy a
  -- literature or landscape requirement.
  required_evidence_type text not null default 'any' check (required_evidence_type in (
    'any', 'document', 'research_run', 'data', 'url', 'note'
  )),
  required_document_type text,
  acceptance_criteria    text,

  -- Due date offset in days from the stage start, used when instantiating.
  default_lead_days integer,

  -- Which role may approve this requirement. Null means any approver role.
  approver_role_key text references public.roles(key) on delete set null,

  created_at timestamptz not null default now(),

  unique (template_stage_id, ref_code)
);

create index template_requirements_stage_idx
  on public.template_requirements (template_stage_id, position);

-- ------------------------------------------ template_requirement_dependencies ---
-- A requirement may depend on others completing first. The readiness engine
-- walks this graph, so a cycle would make it non-terminating. The trigger below
-- rejects cycles at write time rather than leaving the engine to defend itself.

create table public.template_requirement_dependencies (
  requirement_id uuid not null references public.template_requirements(id) on delete cascade,
  depends_on_id  uuid not null references public.template_requirements(id) on delete cascade,
  primary key (requirement_id, depends_on_id),
  constraint no_self_dependency check (requirement_id <> depends_on_id)
);

create or replace function private.reject_template_dependency_cycle()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Walk forward from the proposed prerequisite. If we can reach the dependant,
  -- adding this edge would close a loop.
  if exists (
    with recursive reachable(id) as (
      select new.depends_on_id
      union
      select d.depends_on_id
        from public.template_requirement_dependencies d
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

create trigger template_dependencies_no_cycle
  before insert or update on public.template_requirement_dependencies
  for each row execute function private.reject_template_dependency_cycle();

-- ------------------------------------------------------------------ policies ---
-- Templates are organisation-wide reference data: any signed-in user may read
-- them, but all writes go through the backend service role so that template
-- changes are audited and approval is enforced in one place.

alter table public.pdp_templates                       enable row level security;
alter table public.template_stages                     enable row level security;
alter table public.template_requirements               enable row level security;
alter table public.template_requirement_dependencies   enable row level security;

create policy pdp_templates_read on public.pdp_templates
  for select to authenticated using (true);

create policy template_stages_read on public.template_stages
  for select to authenticated using (true);

create policy template_requirements_read on public.template_requirements
  for select to authenticated using (true);

create policy template_dependencies_read on public.template_requirement_dependencies
  for select to authenticated using (true);
