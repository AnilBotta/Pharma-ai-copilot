-- 0004 — User document uploads, and the observability / caching tables.

-- --------------------------------------------------------------- documents ---

create table public.documents (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.projects(id) on delete cascade,

  filename   text not null,
  mime_type  text not null check (mime_type in ('application/pdf', 'text/plain', 'text/markdown')),
  size_bytes bigint not null check (size_bytes > 0),
  storage_path text,
  sha256     text,

  page_count      integer,
  extracted_chars integer,

  status text not null default 'pending' check (status in (
    'pending', 'extracting', 'embedding', 'ready', 'failed'
  )),
  error text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index documents_user_idx    on public.documents (user_id, created_at desc);
create index documents_project_idx on public.documents (project_id);

create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function set_updated_at();

comment on table public.documents is
  'User-supplied internal evidence. Never treated as verified, and its text is '
  'passed to models as untrusted data, never as instructions.';

-- ---------------------------------------------------------- document_chunks ---
-- The only place pgvector is used. Page and heading metadata are retained so a
-- citation can point at "filename, p. 12" rather than at the document as a whole.

create table public.document_chunks (
  id          uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  chunk_index integer not null,
  content     text not null,
  page_number integer,
  section_heading text,
  token_count integer,
  embedding   vector(1536),
  created_at  timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create index document_chunks_doc_idx on public.document_chunks (document_id, chunk_index);

-- IVFFlat needs training data to be worth building; on an empty table it would
-- be counterproductive. Created here with a small list count suitable for the
-- MVP corpus size, using cosine distance to match the embedding model.
create index document_chunks_embedding_idx
  on public.document_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- Now that document_chunks exists, close the evidence back-reference.
alter table public.evidence_records
  add constraint evidence_document_chunk_fk
  foreign key (document_chunk_id)
  references public.document_chunks(id) on delete cascade;

-- -------------------------------------------------------------- run_errors ---

create table public.run_errors (
  id       uuid primary key default gen_random_uuid(),
  run_id   uuid not null references public.research_runs(id) on delete cascade,
  node     text,
  provider text,
  error_type text not null check (error_type in (
    'provider_failure', 'rate_limit', 'provider_unavailable', 'validation',
    'verification', 'timeout', 'model_error', 'unknown'
  )),
  message     text not null,
  detail      jsonb,
  retry_count integer not null default 0,
  is_fatal    boolean not null default false,
  created_at  timestamptz not null default now()
);

create index run_errors_run_idx on public.run_errors (run_id, created_at);

comment on table public.run_errors is
  'Honest failure record. A provider failure is logged here and surfaced to the '
  'user; it never results in substituted or invented results.';

-- ------------------------------------------------------------ usage_records ---

create table public.usage_records (
  id      uuid primary key default gen_random_uuid(),
  run_id  uuid references public.research_runs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,

  node    text,
  purpose text,
  model   text not null,

  input_tokens     integer not null default 0,
  output_tokens    integer not null default 0,
  reasoning_tokens integer not null default 0,
  cached_tokens    integer not null default 0,

  estimated_cost_usd numeric(12,6) not null default 0,
  duration_ms        integer,

  created_at timestamptz not null default now()
);

create index usage_run_idx  on public.usage_records (run_id);
create index usage_user_idx on public.usage_records (user_id, created_at desc);

-- ----------------------------------------------------------- provider_cache ---
-- Keyed cache of external API responses. Not user-scoped: responses from
-- PubMed, Europe PMC and EPO are public data, and sharing them across users
-- reduces quota consumption. No user content is stored here.

create table public.provider_cache (
  cache_key  text primary key,
  provider   text not null,
  response   jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create index provider_cache_expiry_idx on public.provider_cache (expires_at);

create or replace function public.purge_expired_provider_cache()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  deleted integer;
begin
  delete from public.provider_cache where expires_at < now();
  get diagnostics deleted = row_count;
  return deleted;
end;
$$;
