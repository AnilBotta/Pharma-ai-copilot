-- 0006 — Security hardening, resolving findings from the Supabase database
-- linter after the initial schema was applied.
--
-- Two classes of finding:
--
-- 1. `extension_in_public` — pgvector was installed into `public`, putting its
--    types and operators inside the PostgREST-exposed schema. Moved to
--    `extensions`. Applied separately as 0006a so the vector column and the
--    ivfflat index could be verified intact before continuing.
--
-- 2. `anon`/`authenticated_security_definer_function_executable` — every
--    SECURITY DEFINER function in `public` is reachable as an RPC endpoint at
--    /rest/v1/rpc/<name>. None of ours is meant to be called that way: two are
--    trigger functions, two are RLS predicates, one is a maintenance routine.
--
--    They are moved to a `private` schema instead of having EXECUTE revoked.
--    PostgREST only exposes configured schemas, so nothing in `private` is
--    reachable over HTTP at all, while RLS policies and triggers can still call
--    them normally. Revoking EXECUTE would have broken the RLS predicates,
--    since policies run as the querying role.

create schema if not exists private;

revoke all on schema private from anon, authenticated;
grant usage on schema private to postgres, service_role;
-- RLS predicates are evaluated as the querying role, so `authenticated` needs
-- USAGE here. This does not expose anything: `private` is not a PostgREST
-- schema, so these functions have no HTTP surface.
grant usage on schema private to authenticated;

-- ------------------------------------------------------- trigger functions ---

create or replace function private.set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1))
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

-- ---------------------------------------------------------- RLS predicates ---

create or replace function private.owns_run(target_run_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.research_runs r
    where r.id = target_run_id and r.user_id = (select auth.uid())
  );
$$;

create or replace function private.owns_document(target_document_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.documents d
    where d.id = target_document_id and d.user_id = (select auth.uid())
  );
$$;

grant execute on function private.owns_run(uuid)      to authenticated;
grant execute on function private.owns_document(uuid) to authenticated;

-- ------------------------------------------------------------- maintenance ---

create or replace function private.purge_expired_provider_cache()
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

-- --------------------------------------------- drop the public originals ----
-- CASCADE removes the triggers and policies that depend on them; both are
-- recreated below against the private schema.

drop function if exists public.set_updated_at() cascade;
drop function if exists public.handle_new_user() cascade;
drop function if exists public.owns_run(uuid) cascade;
drop function if exists public.owns_document(uuid) cascade;
drop function if exists public.purge_expired_provider_cache() cascade;

-- ------------------------------------------------------- recreate triggers ---

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function private.set_updated_at();

create trigger projects_set_updated_at
  before update on public.projects
  for each row execute function private.set_updated_at();

create trigger research_runs_set_updated_at
  before update on public.research_runs
  for each row execute function private.set_updated_at();

create trigger agent_tasks_set_updated_at
  before update on public.agent_tasks
  for each row execute function private.set_updated_at();

create trigger run_jobs_set_updated_at
  before update on public.run_jobs
  for each row execute function private.set_updated_at();

create trigger report_sections_set_updated_at
  before update on public.report_sections
  for each row execute function private.set_updated_at();

create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function private.set_updated_at();

-- ------------------------------------------------------- recreate policies ---

create policy run_events_read on public.run_events
  for select to authenticated using (private.owns_run(run_id));

create policy agent_tasks_read on public.agent_tasks
  for select to authenticated using (private.owns_run(run_id));

create policy search_queries_read on public.search_queries
  for select to authenticated using (private.owns_run(run_id));

create policy run_jobs_read on public.run_jobs
  for select to authenticated using (private.owns_run(run_id));

create policy literature_records_read on public.literature_records
  for select to authenticated using (private.owns_run(run_id));

create policy patent_records_read on public.patent_records
  for select to authenticated using (private.owns_run(run_id));

create policy evidence_records_read on public.evidence_records
  for select to authenticated using (private.owns_run(run_id));

create policy report_sections_read on public.report_sections
  for select to authenticated using (private.owns_run(run_id));

create policy citations_read on public.citations
  for select to authenticated using (private.owns_run(run_id));

create policy run_errors_read on public.run_errors
  for select to authenticated using (private.owns_run(run_id));

create policy document_chunks_read on public.document_chunks
  for select to authenticated using (private.owns_document(document_id));
