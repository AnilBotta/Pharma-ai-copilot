-- 0032 — SAS validation: an optional independent check, stored as evidence.
--
-- WHAT THIS IS FOR
--
-- be-stats is the calculator of record. Every regulatory result this product
-- produces comes from the Python engine, and a customer with no SAS — which
-- today is every customer — must be able to use every supported calculation.
-- SAS validation sits beside that engine as an optional service.
--
-- The first mode that works end to end connects to nothing at all: we generate
-- an immutable package, the customer runs it inside their own SAS, and they
-- upload what SAS wrote. That is why this migration stores no credential
-- anywhere. The columns for connected modes exist, and hold a REFERENCE into
-- Supabase Vault rather than a value.
--
-- PREPARED FOR TENANT ISOLATION; THIS DEPLOYMENT IS SINGLE-ORGANISATION.
--
-- 0001 records that this is a single-organisation MVP: every profile belongs to
-- the same implicit org and there is no organisations table. So `tenant_id`
-- below is not yet a foreign key to anything, and today it holds one value.
--
-- What follows is therefore a tenant-scoped DATA MODEL with isolation
-- invariants, not runtime multi-tenancy. There is no identity-to-organisation
-- mapping to resolve against, and nothing here should be described as
-- isolating one live customer from another until there is.
--
-- It is present anyway for one reason: retrofitting a tenant column onto tables
-- that already hold customer credentials and regulatory evidence is exactly the
-- migration nobody wants to write, and getting it wrong leaks one customer's
-- SAS environment to another. The column, the indexes and the isolation
-- predicate are cheap now and expensive later. When an organisations table
-- arrives, this becomes a foreign key and the predicate tightens; nothing above
-- it has to move.
--
-- ACCESS CONTROL
--
-- Deny-all RLS with no policy, plus revoke from anon and authenticated — the
-- pattern 0010 established for `checkpoints` and `provider_cache`. These tables
-- hold secret references and regulatory evidence, and every access goes through
-- the backend as the service role, which applies the tenant predicate itself.
-- The anti-pattern to avoid is `notification_recipients`, whose permissive
-- select is justified only because it holds nothing sensitive. This does.

set search_path = '';

-- ------------------------------------------------------------- enums ---

-- Named after WHO OWNS AND OPERATES the environment, not after a credential
-- shape. An earlier sketch called every mode "API key", which is wrong three
-- times over: Viya authenticates by OAuth against the customer's tenant, an
-- enterprise installation may use Kerberos or a service account, and the
-- manual route has no credential at all because nothing ever connects.
create type public.sas_integration_mode as enum (
  'not_configured',
  'managed',
  'customer_viya',
  'customer_remote',
  'manual_upload'
);

-- Every value names what happened to a FILE or to a COMPARISON. None of them
-- names a regulatory conclusion, and there is deliberately no 'validated':
-- if such a state existed, something would eventually set it and something
-- downstream would eventually read it as the fact it is not.
create type public.sas_validation_run_status as enum (
  'uploaded',
  'parsed',
  'hash_mismatch',
  'incomplete',
  'comparison_pending',
  'match',
  'mismatch',
  'review_required',
  'reviewed_accepted',
  'reviewed_rejected'
);

-- Recorded separately from the run status because they answer different
-- questions. A run can be 'match' while a reviewer still declines to close the
-- oracle — agreement on one dataset from one SAS version is not a resolved
-- regulatory question. Only a later statistical PR may act on this.
create type public.sas_oracle_closure as enum (
  'not_assessed',
  'oracle_closure_accepted',
  'oracle_closure_rejected'
);

-- Designed, not implemented, and carrying no prices. Whatever managed SAS
-- costs depends on commercial terms this organisation has not agreed, and a
-- number written here now would be quoted back later as though it had been.
create type public.sas_billing_mode as enum (
  'not_applicable',
  'included_in_plan',
  'pay_per_validation',
  'validation_credit',
  'enterprise_included'
);

-- ------------------------------------------------------ integrations ---

create table public.sas_integrations (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null,

  mode                   public.sas_integration_mode not null default 'not_configured',

  -- Non-secret configuration. Safe to return from a GET, safe to audit.
  environment_name       text,
  organization_name      text,
  base_url               text,
  auth_type              text,
  tenant_ref             text,          -- the SAS-side tenant, not ours
  host                   text,
  port                   integer,
  authentication_method  text,
  username               text,

  -- SECRETS LIVE IN VAULT. These are secret NAMES, never values. A GET answers
  -- `configured: true` and never returns one, not even masked — a mask still
  -- discloses length and there is no reason to send it.
  client_id_secret_name       text,
  client_secret_name          text,
  access_token_secret_name    text,
  refresh_token_secret_name   text,
  credential_secret_name      text,

  -- Managed-service placeholder state. No vendor is bound.
  managed_provider            text,
  managed_service_region      text,
  managed_billing_mode        public.sas_billing_mode not null default 'not_applicable',
  managed_usage_limit         integer,
  managed_runs_remaining      integer,
  managed_price_reference     text,      -- a reference, never an amount
  managed_connection_status   text not null default 'not_provisioned',

  -- An ACKNOWLEDGEMENT that the organisation may connect this environment.
  -- Not a licence verification: this application cannot check anyone's SAS
  -- entitlement and does not claim to. It records that a named person said so.
  authorisation_acknowledged_by  uuid references public.profiles(id),
  authorisation_acknowledged_at  timestamptz,
  authorisation_text             text,

  created_at             timestamptz not null default now(),
  created_by             uuid references public.profiles(id),
  updated_at             timestamptz not null default now(),

  -- One integration per tenant. Two would mean two answers to "where does this
  -- organisation's validation run", and nothing would say which won.
  constraint sas_integrations_one_per_tenant unique (tenant_id),

  -- A connected mode without an acknowledgement is a configuration we should
  -- never have accepted. Enforced here as well as in the API, because the API
  -- is not the only thing that will ever write this table.
  constraint sas_integrations_connected_modes_are_acknowledged check (
    mode not in ('customer_viya', 'customer_remote')
    or authorisation_acknowledged_at is not null
  ),

  -- Guard against a secret VALUE being written where a reference belongs.
  -- A Vault secret name is a short identifier; a token is not.
  constraint sas_integrations_secret_names_are_references check (
    (client_id_secret_name     is null or length(client_id_secret_name)     <= 128)
    and (client_secret_name        is null or length(client_secret_name)        <= 128)
    and (access_token_secret_name  is null or length(access_token_secret_name)  <= 128)
    and (refresh_token_secret_name is null or length(refresh_token_secret_name) <= 128)
    and (credential_secret_name    is null or length(credential_secret_name)    <= 128)
  )
);

create index sas_integrations_tenant_idx on public.sas_integrations (tenant_id);

-- --------------------------------------------------------- packages ---

-- IMMUTABLE. `id` is the SHA-256 of the manifest, which covers the dataset,
-- the program, the model specification, the engine version and the commit.
-- Change any of those and you get a different package — never an edited one,
-- because the record of what was run must outlive the thing that ran it.
create table public.sas_validation_packages (
  id                          text primary key,   -- sha256 of the manifest
  tenant_id                   uuid not null,

  case_id                     text not null,
  regulatory_method           text not null,

  dataset_sha256              text not null,
  program_sha256              text not null,
  model_specification_sha256  text not null,

  manifest                    jsonb not null,
  files                       jsonb not null,

  be_stats_version            text not null,
  git_sha                     text not null,

  generated_at                timestamptz not null,
  generated_by                uuid references public.profiles(id),

  constraint sas_validation_packages_id_is_a_hash check (id ~ '^[0-9a-f]{64}$')
);

create index sas_validation_packages_tenant_idx
  on public.sas_validation_packages (tenant_id, generated_at desc);

-- Immutability enforced, not merely intended. Evidence that can be edited is
-- not evidence.
create or replace function private.sas_packages_are_immutable()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  raise exception
    'sas_validation_packages is append-only. A change to the dataset, the '
    'program, the model or the engine version produces a NEW package id; it '
    'does not modify an existing one.';
end;
$$;

create trigger sas_validation_packages_no_update
  before update or delete on public.sas_validation_packages
  for each row execute function private.sas_packages_are_immutable();

-- ------------------------------------------------------------- runs ---

create table public.sas_validation_runs (
  id                       uuid primary key default gen_random_uuid(),
  tenant_id                uuid not null,

  package_id               text not null references public.sas_validation_packages(id),
  case_id                  text not null,

  sas_mode                 public.sas_integration_mode not null,
  sas_environment_name     text,
  sas_version              text,

  execution_timestamp      timestamptz,
  uploaded_at              timestamptz not null default now(),
  uploaded_by              uuid references public.profiles(id),

  -- What the uploader's own copy of the package claimed. Compared with the
  -- package row above: evidence for a different dataset or a different program
  -- is not weak evidence, it is evidence about a different question.
  declared_dataset_sha256  text,
  declared_program_sha256  text,

  -- What SAS reported. Not what is true — what SAS reported.
  estimate_log             double precision,
  estimate_ratio           double precision,
  standard_error           double precision,
  denominator_df           double precision,
  ci_lower_log             double precision,
  ci_upper_log             double precision,
  ci_lower_ratio           double precision,
  ci_upper_ratio           double precision,
  covariance_parameters    jsonb,

  convergence_status       text,
  warnings                 jsonb,

  status                   public.sas_validation_run_status not null default 'uploaded',
  comparison               jsonb,

  -- A reviewer's decision, separate from the comparison's outcome.
  review_status            public.sas_oracle_closure not null default 'not_assessed',
  reviewed_by              uuid references public.profiles(id),
  reviewed_at              timestamptz,
  review_notes             text,

  constraint sas_validation_runs_review_is_attributed check (
    review_status = 'not_assessed'
    or (reviewed_by is not null and reviewed_at is not null)
  )
);

create index sas_validation_runs_tenant_idx
  on public.sas_validation_runs (tenant_id, uploaded_at desc);
create index sas_validation_runs_package_idx
  on public.sas_validation_runs (package_id);

-- -------------------------------------------------------- artifacts ---

-- The raw upload, kept whole. Parsed numbers must link back to the file they
-- came from: retaining only the JSON would leave a reviewer unable to check
-- what the parser did, which for regulatory evidence is not good enough.
create table public.sas_validation_artifacts (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null,
  run_id         uuid not null references public.sas_validation_runs(id) on delete restrict,

  kind           text not null check (kind in ('result_file', 'sas_log', 'other')),
  filename       text not null,
  content_sha256 text not null,
  byte_size      bigint not null,
  storage_ref    text not null,

  uploaded_at    timestamptz not null default now(),
  uploaded_by    uuid references public.profiles(id),

  constraint sas_validation_artifacts_hash_is_a_hash
    check (content_sha256 ~ '^[0-9a-f]{64}$')
);

create index sas_validation_artifacts_run_idx
  on public.sas_validation_artifacts (run_id);

create or replace function private.sas_artifacts_are_immutable()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  raise exception
    'sas_validation_artifacts is append-only. The original SAS output is the '
    'evidence; superseding it means uploading another artifact, not editing '
    'this one.';
end;
$$;

create trigger sas_validation_artifacts_no_update
  before update or delete on public.sas_validation_artifacts
  for each row execute function private.sas_artifacts_are_immutable();

-- ------------------------------------------------------------- RLS ---

-- Deny-all, no policy, service role only — the `checkpoints` pattern from
-- 0010. `sas_integrations` holds secret references; the rest holds regulatory
-- evidence. Neither should be reachable by a browser session under any
-- predicate we could write today, because the tenant predicate has nothing to
-- resolve against until there is an organisations table.
alter table public.sas_integrations           enable row level security;
alter table public.sas_validation_packages    enable row level security;
alter table public.sas_validation_runs        enable row level security;
alter table public.sas_validation_artifacts   enable row level security;

revoke all on public.sas_integrations         from anon, authenticated;
revoke all on public.sas_validation_packages  from anon, authenticated;
revoke all on public.sas_validation_runs      from anon, authenticated;
revoke all on public.sas_validation_artifacts from anon, authenticated;

-- ----------------------------------------------------- tenant scope ---

-- The isolation predicate, in one place so there is one definition to tighten
-- when tenancy arrives rather than a dozen inline comparisons to find.
create or replace function private.sas_tenant_matches(
  p_row_tenant uuid,
  p_caller_tenant uuid
)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p_row_tenant is not distinct from p_caller_tenant
     and p_caller_tenant is not null;
$$;

comment on function private.sas_tenant_matches(uuid, uuid) is
  'Tenant-scoping predicate for SAS validation. PREPARED FOR TENANT '
  'ISOLATION; this deployment is single-organisation - every row shares one '
  'implicit org (see 0001), so today this compares a column that has one '
  'value and is not yet isolating live customers from one another. It exists '
  'now so the check has a single home: when an organisations table arrives '
  'this tightens, and no caller changes. The caller tenant must then be '
  'derived from authenticated server-side identity, never from a '
  'client-supplied value.';

comment on column public.sas_integrations.tenant_id is
  'Not yet a foreign key — 0001 records that this is a single-organisation '
  'MVP. Present from the start because retrofitting a tenant column onto a '
  'table holding SAS credentials is the migration that leaks one customer''s '
  'environment to another.';

comment on table public.sas_validation_packages is
  'Immutable validation packages. The id is the SHA-256 of the manifest, so a '
  'change to the dataset, program, model, engine version or commit yields a '
  'new package rather than an edited one.';

comment on table public.sas_validation_runs is
  'External SAS validation evidence. No status here means a method is '
  'validated: promotion of a regulatory validation status is a governed '
  'statistical change and cannot be reached from this table.';
