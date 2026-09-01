-- 0034 — who may accept oracle evidence, and what the AI is allowed to be.
--
-- THE GOVERNANCE RULE THIS SCHEMA ENFORCES
--
--     AI MAY RECOMMEND. AI MUST NOT BE THE FINAL APPROVER.
--
-- That is not a policy written in a comment and hoped for. The two kinds of
-- output live in SEPARATE TABLES with SEPARATE ENUMS, and there is no value an
-- AI review can hold that a human decision can also hold. An AI cannot
-- accidentally express acceptance because the vocabulary to express it does
-- not exist on its side of the line.
--
-- WHY A NEW ROLE FUNCTION, AND WHY IT LOOKS LIKE 0016's
--
-- 0016 already recorded the problem, in its own words:
--
--     "private.can_access_project() reads auth.uid(). The API connects as the
--      service role, where auth.uid() is null, so the API could not reuse the
--      rule and would have had to restate it in Python. Two copies of an
--      access rule is one copy too many: they drift, and the drift is a
--      security bug."
--
-- `private.has_role()` from 0007 has exactly that shape: it reads auth.uid()
-- and is granted to `authenticated`. The backend connects as the service role,
-- so it returns false for every user, always. `private.user_capabilities()` is
-- project-scoped by signature and cannot answer a global question at all.
--
-- So PR #64 shut the review endpoint rather than restating the rule in Python.
-- This migration supplies the missing twin, following the precedent 0016 set
-- rather than inventing a second authorisation mechanism.

set search_path = '';

-- ------------------------------------------------------- actor types ---
--
-- A human decision and an automated one must never be indistinguishable in the
-- record. `actor_type` is stored, not inferred, so "was this approved by a
-- person" is answerable by reading a column rather than by reasoning about
-- which code path wrote the row.
create type public.review_actor_type as enum ('human', 'ai_system', 'system');

-- --------------------------------------------- the AI's vocabulary ---
--
-- DELIBERATELY DISJOINT from the human decision enum below. There is no
-- 'accepted' here and no 'acceptable_for_human_review' there. An AI can say
-- the evidence looks fit for a person to consider; it has no way to say the
-- evidence is accepted, because that word is not in its language.
create type public.ai_review_recommendation as enum (
  'acceptable_for_human_review',
  'reject_recommended',
  'insufficient_evidence',
  'escalate_to_statistician'
);

create type public.ai_review_confidence as enum ('low', 'medium', 'high');

-- ----------------------------------------- the human's vocabulary ---
create type public.oracle_closure_decision as enum (
  'oracle_closure_accepted',
  'oracle_closure_rejected'
);

-- ------------------------------------------- explicit-user role check ---
--
-- Takes the user id rather than reading auth.uid(), so the backend can ask it
-- while connected as the service role. Same rule, one copy, callable from both
-- sides — which is the whole point of 0016's twin pattern.
--
-- Deliberately narrow: it answers one boolean about one user and one role. It
-- cannot list users, cannot list a user's roles, and cannot be coaxed into
-- either, so a caller that leaked its result leaks one bit about one question
-- it already had to know to ask.
--
-- GLOBAL means project_id is null — the scope 0007's `user_roles_global_uniq`
-- index already models. An expired grant does not count.
create or replace function private.user_has_global_role(
  p_user_id uuid,
  p_role_key text
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
     where ur.user_id = p_user_id
       and r.key = p_role_key
       and ur.project_id is null
       and (ur.expires_at is null or ur.expires_at > now())
  );
$$;

comment on function private.user_has_global_role(uuid, text) is
  'Does this specific user hold this role globally? Takes an explicit user id '
  'rather than reading auth.uid(), so the backend can ask it under the service '
  'role — the twin pattern 0016 established. Returns a boolean only: it cannot '
  'enumerate users or roles.';

-- Not granted to `anon` or `authenticated`. The browser never asks this
-- question directly; the backend asks it and acts on the answer.
revoke all on function private.user_has_global_role(uuid, text) from public;

-- ------------------------------------------------------- AI reviews ---
--
-- ADVISORY ANALYSIS, never a validation decision. Stored separately from human
-- review so that no query, and no future refactor, can mistake one for the
-- other.
create table public.sas_ai_reviews (
  id                      uuid primary key default gen_random_uuid(),
  tenant_id               uuid not null,
  run_id                  uuid not null references public.sas_validation_runs(id),

  -- Always 'ai_system'. Present as a column rather than implied by the table
  -- name, so a joined view of all review activity still distinguishes them.
  actor_type              public.review_actor_type not null default 'ai_system',

  model_provider          text,
  model_name              text,
  model_version           text,
  prompt_version          text not null,

  -- What the model was shown. Non-deterministic output is only interpretable
  -- against the evidence that produced it, so the snapshot is hashed and the
  -- hash stored beside the response.
  evidence_snapshot_hash  text not null,
  response                jsonb,
  response_hash           text,

  recommendation          public.ai_review_recommendation,
  confidence              public.ai_review_confidence,

  -- An unavailable model is a state, not an error to swallow. A row with
  -- succeeded = false records that the attempt happened and what went wrong,
  -- so a reviewer sees "the assistant could not run" rather than nothing.
  succeeded               boolean not null default true,
  failure_reason          text,

  generated_at            timestamptz not null default now(),
  requested_by            uuid references public.profiles(id),

  constraint sas_ai_reviews_successful_has_a_recommendation check (
    succeeded = false or (recommendation is not null and response is not null)
  ),
  constraint sas_ai_reviews_failure_has_a_reason check (
    succeeded = true or failure_reason is not null
  ),
  constraint sas_ai_reviews_hash_is_a_hash check (
    evidence_snapshot_hash ~ '^[0-9a-f]{64}$'
  )
);

create index sas_ai_reviews_run_idx
  on public.sas_ai_reviews (run_id, generated_at desc);

-- VERSIONED, NOT OVERWRITTEN.
--
-- Model versions change and output is non-deterministic, so re-running an
-- analysis produces a genuinely different artefact. Replacing the old one
-- would destroy the record of what a human reviewer actually read.
create or replace function private.sas_ai_reviews_are_append_only()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  raise exception
    'sas_ai_reviews is append-only. Re-running the assistant creates a new '
    'version; it does not replace the analysis a reviewer may already have '
    'read.';
end;
$$;

create trigger sas_ai_reviews_no_update
  before update or delete on public.sas_ai_reviews
  for each row execute function private.sas_ai_reviews_are_append_only();

-- ---------------------------------------------------- human reviews ---
create table public.sas_human_reviews (
  id                      uuid primary key default gen_random_uuid(),
  tenant_id               uuid not null,
  run_id                  uuid not null references public.sas_validation_runs(id),

  -- Enforced 'human' by a check, not by convention. An AI or background
  -- identity writing here would be the single most serious failure this
  -- schema can have, so the column refuses the value rather than trusting the
  -- caller.
  actor_type              public.review_actor_type not null default 'human',
  reviewer_user_id        uuid not null references public.profiles(id),
  reviewer_role_key       text not null,

  decision                public.oracle_closure_decision not null,

  -- Never empty. An accepted oracle closure with no recorded reasoning is not
  -- reviewable evidence, and the constraint is here as well as in the API
  -- because the API is not the only thing that will ever write this table.
  notes                   text not null,

  -- The acknowledgement, stored as text AND hash AND version, so "what
  -- exactly did this person agree to" survives a later edit to the wording.
  acknowledgement_version text not null,
  acknowledgement_text    text not null,
  acknowledgement_hash    text not null,

  -- WHAT EXACTLY WAS APPROVED.
  --
  -- A decision that referenced only a run id would be uninterpretable once
  -- anything about the run was re-read. The snapshot fixes the evidence as it
  -- stood at the moment of the decision.
  evidence_snapshot       jsonb not null,
  evidence_snapshot_hash  text not null,

  -- Which AI analysis, if any, was available when the human decided. Null is
  -- meaningful: it records that the assistant was unavailable and the person
  -- decided on the deterministic evidence alone.
  ai_review_id            uuid references public.sas_ai_reviews(id),
  ai_recommendation_at_time public.ai_review_recommendation,

  decided_at              timestamptz not null default now(),

  constraint sas_human_reviews_actor_is_human check (actor_type = 'human'),
  constraint sas_human_reviews_notes_not_empty check (length(btrim(notes)) > 0),
  constraint sas_human_reviews_hashes_are_hashes check (
    acknowledgement_hash ~ '^[0-9a-f]{64}$'
    and evidence_snapshot_hash ~ '^[0-9a-f]{64}$'
  )
);

create index sas_human_reviews_run_idx
  on public.sas_human_reviews (run_id, decided_at desc);

-- IMMUTABLE, AND VERSIONED BY APPENDING.
--
-- A second authorised reviewer looking at the same run creates a SEPARATE
-- record. Two people disagreeing is information; overwriting the first opinion
-- destroys it.
create or replace function private.sas_human_reviews_are_append_only()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  raise exception
    'sas_human_reviews is append-only. A later review by another authorised '
    'reviewer is a NEW record: a governed decision, its reasoning and the '
    'evidence it was made against must outlive any subsequent opinion.';
end;
$$;

create trigger sas_human_reviews_no_update
  before update or delete on public.sas_human_reviews
  for each row execute function private.sas_human_reviews_are_append_only();

-- ------------------------------------------------------------- RLS ---
--
-- Deny-all, service role only — the pattern 0010 established and 0032 followed.
-- These tables hold governed regulatory decisions and the identity of the
-- people who made them.
alter table public.sas_ai_reviews    enable row level security;
alter table public.sas_human_reviews enable row level security;

revoke all on public.sas_ai_reviews    from anon, authenticated;
revoke all on public.sas_human_reviews from anon, authenticated;

comment on table public.sas_ai_reviews is
  'ADVISORY ANALYSIS, not a validation decision. Its recommendation enum is '
  'deliberately disjoint from the human decision enum: an AI has no vocabulary '
  'in which to express acceptance.';

comment on table public.sas_human_reviews is
  'The governed decision. Accepting a run as oracle evidence does NOT change '
  'any method validation status, and does not set partial_oracle_ready — it '
  'records that this SAS run is accepted as suitable evidence for a separate '
  'statistical implementation and validation task.';
