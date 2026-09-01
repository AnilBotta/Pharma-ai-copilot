-- 0035: who ran the SAS, and whether this run is evidence at all.
--
-- TWO THINGS THAT MUST BE DECLARED RATHER THAN INFERRED
--
-- 1. THE OPERATOR ATTESTATION
--
--    Manual execution happens in an environment this application has no access
--    to, so the exact SAS program bytes executed cannot be verified. That is
--    permanent for the manual path and no column here changes it. What an
--    attestation adds is an ACCOUNTABLE HUMAN CLAIM beside the evidence: who
--    says they ran it, in which organisation, on which SAS version, against
--    which archive hash.
--
--    `program_execution_integrity` stays `unverified_manual_execution`. The
--    check constraint at the bottom of the attestation table enforces exactly
--    that, so an attestation cannot be mistaken for - or quietly upgraded into
--    - a verification.
--
-- 2. THE EVIDENCE ORIGIN
--
--    A fixture CSV and a real SAS CSV are the same shape; that is what makes a
--    fixture useful. So nothing about a file distinguishes an operational dry
--    run from regulatory evidence, and the origin is recorded by the caller at
--    upload rather than guessed from content. "It parsed, so it must be real"
--    is precisely how a dry-run artefact ends up in a regulatory record.
--
-- WHAT THIS MIGRATION DOES NOT DO
--
-- It changes no validation status, implements no statistical method, and sets
-- no oracle flag. FDA_REPLICATE_STANDARD_ABE_PARTIAL remains NOT_IMPLEMENTED.

set search_path = '';

-- ------------------------------------------------------- evidence origin ---

create type public.sas_evidence_origin as enum (
  -- An operational exercise. Never regulatory evidence, whatever it contains.
  'test_fixture',
  -- The real path in this release: a licensed SAS environment we do not
  -- operate, run by someone else, returning files.
  'manual_external_sas',
  -- Reserved. No managed service exists; the value is here so the vocabulary
  -- does not have to change when one does.
  'managed_sas'
);

comment on type public.sas_evidence_origin is
  'Where a run''s evidence came from. DECLARED at upload, never inferred from '
  'file content - a fixture and a real SAS result are the same shape.';

-- Defaulted to the honest answer for anything already stored: a run created
-- before this column existed was an operational exercise, because no licensed
-- SAS result has been collected yet.
alter table public.sas_validation_runs
  add column if not exists evidence_origin public.sas_evidence_origin
    not null default 'test_fixture';

comment on column public.sas_validation_runs.evidence_origin is
  'test_fixture rows are NOT regulatory evidence and must never be reported '
  'as such. Only manual_external_sas is real SAS output in this release.';

create index sas_validation_runs_origin_idx
  on public.sas_validation_runs (tenant_id, evidence_origin, uploaded_at desc);

-- --------------------------------------------------- operator attestation ---

create table public.sas_operator_attestations (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null,
  run_id                   uuid not null references public.sas_validation_runs(id),

  -- WHICH PACKAGE, BY HASH. An attestation that did not name the archive would
  -- not identify which bytes the operator says they ran.
  package_id               text not null references public.sas_validation_packages(id),
  archive_sha256           text not null,

  -- DECLARED OPERATOR IDENTITY.
  --
  -- Text, not a reference to public.profiles, and deliberately so. The person
  -- with the licensed SAS environment is usually in the client organisation
  -- and has no account here. Minting a user id for them would put a fiction in
  -- the audit trail that every later reader would have to un-learn.
  operator_name            text not null,
  operator_organization    text not null,
  operator_email           text,

  -- Optional because an operator may legitimately not know these, and a
  -- required field people fill with 'unknown' is worse than an absent one.
  sas_version              text,
  operating_environment    text,
  executed_at              timestamptz,

  -- The claim itself, stored as text AND hash AND version, so "what exactly
  -- did this operator affirm" survives a later edit to the wording.
  attestation_version      text not null,
  attestation_text         text not null,
  attestation_hash         text not null,
  attested_at              timestamptz not null default now(),

  -- WHO SUBMITTED IT HERE, which is not who ran SAS. An account manager
  -- entering a client's details is the ordinary case, and conflating the two
  -- would attribute the claim to the wrong person.
  submitted_by             uuid references public.profiles(id),

  constraint sas_operator_attestations_operator_named check (
    length(btrim(operator_name)) > 0
    and length(btrim(operator_organization)) > 0
  ),
  constraint sas_operator_attestations_hashes_are_hashes check (
    attestation_hash ~ '^[0-9a-f]{64}$'
    and archive_sha256 ~ '^[0-9a-f]{64}$'
  )
);

comment on table public.sas_operator_attestations is
  'A HUMAN DECLARATION, NOT CRYPTOGRAPHIC VERIFICATION. It records who says '
  'they executed a package, where, and on which SAS version. It does not and '
  'cannot establish which program bytes ran: program execution integrity for '
  'every row reachable from here is unverified_manual_execution.';

create index sas_operator_attestations_run_idx
  on public.sas_operator_attestations (run_id, attested_at desc);

-- APPEND-ONLY, like every other evidence table in this module. A correction is
-- a second attestation, because "what did they claim, and when" is the whole
-- point and an edited claim answers neither half.
create or replace function private.sas_attestations_are_append_only()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  raise exception
    'sas_operator_attestations is append-only. A correction is a NEW '
    'attestation; the original claim and its timestamp are the record.';
end;
$$;

create trigger sas_operator_attestations_no_update
  before update or delete on public.sas_operator_attestations
  for each row execute function private.sas_attestations_are_append_only();

-- Deny-all, like 0032/0033/0034. Every read and write goes through the backend
-- under the service role, which checks authorization first. RLS with no policy
-- means the browser reaches nothing directly, which is the intent.
alter table public.sas_operator_attestations enable row level security;

comment on column public.sas_operator_attestations.attestation_hash is
  'SHA-256 of attestation_text. Identifies the wording affirmed; it says '
  'nothing whatever about the SAS program that ran.';
