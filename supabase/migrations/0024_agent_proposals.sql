-- 0024 — The agent prepares; a person decides.
--
-- WHAT THIS IS FOR
--
-- Migration 0022 refuses an agent the four accountable acts. That is right and
-- it stays. But "you cannot do this" is not the same as "this cannot be helped
-- with": a director who says "approve G1-QA-001" is asking for something
-- reasonable, and the useful answer is not a refusal, it is the act prepared
-- and put in front of them.
--
-- So the agent writes a proposal. A person confirms it, and the confirmation
-- executes the act under THEIR identity with no agent mark, which is honest -
-- at that moment they are the actor and the accountability is theirs.
--
-- THE HAZARD THIS TABLE IS SHAPED AROUND
--
-- It is not the agent overreaching. It is the opposite: a one-click Approve
-- button next to an AI recommendation is precisely how rubber-stamping
-- happens, and rubber-stamping is this module's own failure mode - a gate
-- reported better than it is - wearing a new coat.
--
-- Two mechanisms exist for that, and only one of them is here:
--
--   * `premise` records the state the agent reasoned from. If that state has
--     moved by the time somebody clicks, the confirmation is REFUSED. You may
--     not confirm a conclusion whose basis has changed.
--   * the confirmation card renders freshly fetched state rather than the
--     agent's summary of it. That one lives in the UI, because it is about
--     what a person sees.
--
-- `expires_at` is the cruder version of the same idea: a proposal is a
-- statement about a moment, and a moment does not last a week.

create table public.agent_proposals (
  id uuid primary key default gen_random_uuid(),

  conversation_id uuid
    references public.manager_conversations(id) on delete cascade,
  --: The message that produced it. An action whose reasoning cannot be
  --: reconstructed is what the audit trail exists to prevent, and a proposal
  --: with no exchange behind it is exactly that.
  message_id bigint references public.manager_messages(id) on delete set null,

  --: The person the agent was acting for. NOT NULL: a proposal nobody asked
  --: for is not something this system should be able to represent.
  requested_by uuid not null references auth.users(id) on delete cascade,
  project_id   uuid references public.projects(id) on delete cascade,

  --: Constrained rather than free text. An action type this server does not
  --: know how to execute must fail when it is WRITTEN, not discovered at
  --: confirmation time when somebody is waiting.
  action_type text not null check (action_type in (
    'approve_requirement',
    'decide_gate',
    'attach_evidence',
    'add_document_version',
    'set_acceptance',
    'rebaseline'
  )),

  params    jsonb not null,
  --: Why the agent thinks this. Shown subordinate to the evidence, never as
  --: grounds for approving.
  rationale text not null,

  --: The state this was reasoned from. Checked again at confirmation.
  premise jsonb not null,

  status text not null default 'pending'
    check (status in ('pending', 'confirmed', 'rejected', 'expired', 'failed')),

  expires_at timestamptz not null default now() + interval '24 hours',

  confirmed_by    uuid references auth.users(id) on delete set null,
  confirmed_at    timestamptz,
  rejected_reason text,

  result jsonb,
  error  text,

  created_at timestamptz not null default now()
);

create index agent_proposals_pending_idx
  on public.agent_proposals (requested_by, created_at desc)
  where status = 'pending';

create index agent_proposals_project_idx
  on public.agent_proposals (project_id, created_at desc);

-- A confirmed proposal without a confirmer is the thing this whole table
-- exists to make impossible, so it is asserted rather than assumed.
alter table public.agent_proposals
  add constraint confirmed_proposals_name_their_confirmer check (
    status <> 'confirmed'
    or (confirmed_by is not null and confirmed_at is not null)
  );

-- ------------------------------------------- an agent may not confirm one ---
--
-- Mirrors `private.reject_agent_confirmation` on evidence_links. Without it
-- the entire gate is one convenience wrapper away from being decorative: an
-- agent that could both write and confirm a proposal has simply been given the
-- accountable act back through a longer route.

create or replace function private.reject_agent_proposal_confirmation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  acting_agent text := nullif(current_setting('app.acting_agent', true), '');
begin
  if acting_agent is not null
     and new.status = 'confirmed'
     and old.status is distinct from 'confirmed' then
    raise exception
      'agent authority: % may not confirm a proposal. Preparing an act and '
      'deciding to take it are different things, and the second is a person''s.',
      acting_agent
      using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$$;

create trigger agent_proposals_no_agent_confirmation
  before update on public.agent_proposals
  for each row execute function private.reject_agent_proposal_confirmation();

-- ------------------------------------------------ confirmed once, or not ---
--
-- Re-confirming would execute the underlying act twice. For approve_requirement
-- that is merely noisy; for rebaseline it silently commits an organisation to a
-- date twice over.

create or replace function private.proposals_are_decided_once()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.status <> 'pending' and new.status <> old.status then
    raise exception
      'This proposal was already %; it cannot be decided again.', old.status
      using errcode = 'invalid_transaction_state';
  end if;
  return new;
end;
$$;

create trigger agent_proposals_decided_once
  before update on public.agent_proposals
  for each row execute function private.proposals_are_decided_once();

-- ------------------------------------------------------------------ policies ---

alter table public.agent_proposals enable row level security;

create policy agent_proposals_read on public.agent_proposals
  for select to authenticated
  using (
    requested_by = (select auth.uid())
    or (project_id is not null and private.user_can_access_project((select auth.uid()), project_id))
  );

comment on table public.agent_proposals is
  'Accountable acts prepared by an agent for a person to confirm. The premise '
  'column records the state each was reasoned from; confirmation is refused if '
  'that state has moved, because a conclusion whose basis has changed is not '
  'the conclusion that was reviewed.';
