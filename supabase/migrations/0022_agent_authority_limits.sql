-- 0022 — Phase G: what an agent may not do, enforced where it cannot be argued with.
--
-- THE QUESTION THIS MIGRATION ANSWERS
--
-- The PDP Operations Agent needs to read everything, attach evidence, and offer
-- an opinion. It must never approve a requirement, pass a gate, or move a
-- baseline. Those are accountable human acts.
--
-- The weak way to guarantee that is to not give the agent those tools. That is
-- a guarantee about a prompt and a tool schema, and it lasts exactly until
-- somebody adds a convenience wrapper, or a future model composes two permitted
-- calls into a forbidden one, or an agent is handed a user's session so it can
-- "just finish the paperwork".
--
-- The strong way is to make the database refuse. An agent identifies itself for
-- the duration of its transaction; three triggers refuse the accountable acts
-- while that mark is set. It cannot be talked out of it, and an agent that
-- declined to identify itself would be a deliberate act by whoever wrote that
-- code - visible in review, not an accident.
--
-- WHY A TRANSACTION-LOCAL SETTING
--
-- Same idiom as `app.rebaselining` in 0020, inverted: that one grants a
-- narrow permission, this one withdraws several. Both are set with
-- `set_config(..., true)` so they cannot leak past the transaction, and both
-- are unforgeable in the direction that matters. An attacker who could set
-- session variables could only ever *restrict* themselves here.
--
-- WHAT THE AGENT MAY STILL DO
--
-- Everything that is reversible and everything that is only an opinion. It can
-- attach evidence, and it can write `ai_assessment` on an evidence link -
-- a column that has existed since 0013 precisely so a machine's view is stored
-- somewhere that is structurally not an approval. That assessment stays inert
-- until a person sets `human_confirmed_by`.

-- ------------------------------------------------------ pdp_agent_sessions ---

create table public.pdp_agent_sessions (
  id uuid primary key default gen_random_uuid(),

  agent      text not null check (agent in ('pdp_operations', 'manager')),
  project_id uuid references public.projects(id) on delete cascade,

  --: The human this ran for. An agent always acts on somebody's behalf; an
  --: action with no accountable person behind it is not something this system
  --: should be able to represent.
  requested_by uuid not null references auth.users(id) on delete cascade,

  objective text not null,

  status text not null default 'running'
    check (status in ('running', 'completed', 'failed')),

  --: What it concluded, and what it wants a human to do about it. Advisory by
  --: construction: nothing downstream reads this as a decision.
  findings     jsonb,
  recommendations jsonb,
  handoff_question text,

  error text,

  total_input_tokens  integer not null default 0,
  total_output_tokens integer not null default 0,
  estimated_cost_usd  numeric(10,4),

  started_at   timestamptz not null default now(),
  completed_at timestamptz
);

create index pdp_agent_sessions_project_idx
  on public.pdp_agent_sessions (project_id, started_at desc);

comment on table public.pdp_agent_sessions is
  'Agent runs against the PDP module. `recommendations` is advisory: no code '
  'path treats it as a decision, and 0022 makes the accountable acts '
  'unreachable while an agent is acting.';

-- ------------------------------------------------- the refusal, three ways ---

create or replace function private.reject_agent_authority()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  acting_agent text := nullif(current_setting('app.acting_agent', true), '');
begin
  if acting_agent is null then
    return new;  -- a person, or a background job acting on a person's decision
  end if;

  raise exception
    'agent authority: % may not perform this action. Approving a requirement, '
    'deciding a gate and setting a baseline are accountable human acts. The '
    'agent may attach evidence and record an ai_assessment instead.',
    acting_agent
    using errcode = 'insufficient_privilege';
end;
$$;

comment on function private.reject_agent_authority() is
  'Refuses the three accountable acts while app.acting_agent is set. This is '
  'the authority limit for Phase G agents - not the tool schema, which is a '
  'convention a future author could relax without noticing.';

-- An approval is the act this whole module is built around. If an agent could
-- write one, every guarantee from Phase C onwards would be decorative.
create trigger approvals_no_agent_authority
  before insert or update on public.approvals
  for each row execute function private.reject_agent_authority();

-- A gate decision. The engine may advance a stage to ready_for_human_review;
-- the four states below that line are a person's, and this keeps them so even
-- when the caller is a machine holding a valid session.
create or replace function private.reject_agent_gate_decision()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  acting_agent text := nullif(current_setting('app.acting_agent', true), '');
begin
  if acting_agent is null then
    return new;
  end if;

  -- The engine's own status recomputation runs under an agent mark when an
  -- agent's evidence write triggers it, and must stay allowed. Only the human
  -- decision states are refused.
  if new.gate_status is distinct from old.gate_status
     and new.gate_status in
         ('approved', 'conditionally_approved', 'rejected', 'on_hold') then
    raise exception
      'agent authority: % may not decide a gate. Gate decisions require a '
      'person holding gate authority.', acting_agent
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$;

create trigger project_stages_no_agent_gate_decision
  before update on public.project_stages
  for each row execute function private.reject_agent_gate_decision();

-- A baseline is a commitment. An agent proposing one is useful; an agent making
-- one is a machine committing an organisation to a date.
create trigger schedule_baselines_no_agent_authority
  before insert on public.schedule_baselines
  for each row execute function private.reject_agent_authority();

-- --------------------------------------- an assessment is not an approval ---
--
-- 0013 gave evidence_links `ai_assessment`, `ai_confidence` and
-- `human_confirmed_by`, with a comment saying an AI mapping is inert until a
-- human confirms it. Nothing enforced the wording. An agent writing
-- "approved" or "compliant" into that column would produce something that
-- reads, in a gate pack, exactly like a decision.

-- Only the verdict WORDS are banned, not phrases.
--
-- The first draft of this also caught "satisfies the requirement" and "meets
-- the requirement", and testing it showed why that was wrong: it refused
-- "unclear whether this satisfies the requirement" and would equally have
-- refused "does not satisfy the requirement". Those are the honest negative
-- findings an assessment is most useful for. A regex cannot tell "satisfies"
-- from "does not satisfy", so a phrase ban pushes the agent toward vaguer
-- language - the opposite of what this is for.
--
-- These four words have no innocent reading in a gate pack. Everything else is
-- left to the prompt, where a false positive costs a rephrasing rather than a
-- lost finding.
alter table public.evidence_links
  add constraint ai_assessment_is_not_a_verdict check (
    ai_assessment is null
    or lower(ai_assessment) !~ '\m(approved|compliant|certified|authorised|authorized)\M'
  );

comment on constraint ai_assessment_is_not_a_verdict on public.evidence_links is
  'An AI assessment may describe, and it may doubt. It may not use the four '
  'words that are read as a decision. Negative and hedged findings are '
  'deliberately unrestricted - they are the most useful kind.';

-- An agent may never confirm its own assessment: that is the human step.
create or replace function private.reject_agent_confirmation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  acting_agent text := nullif(current_setting('app.acting_agent', true), '');
begin
  if acting_agent is not null
     and new.human_confirmed_by is distinct from old.human_confirmed_by
     and new.human_confirmed_by is not null then
    raise exception
      'agent authority: % may not confirm an AI assessment. That is the human '
      'step it exists to prompt.', acting_agent
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$$;

create trigger evidence_links_no_agent_confirmation
  before update on public.evidence_links
  for each row execute function private.reject_agent_confirmation();

-- ------------------------------------------------------------------ policies ---

alter table public.pdp_agent_sessions enable row level security;

create policy pdp_agent_sessions_read on public.pdp_agent_sessions
  for select to authenticated
  using (project_id is null or private.can_access_project(project_id));
