-- 0005 — Row Level Security.
--
-- The backend connects with the service role and enforces ownership explicitly
-- in app/auth.py. These policies are defence in depth: if a query ever reaches
-- the database on a user connection, or the anon key is used directly from the
-- browser, a user still cannot read another user's research.
--
-- Child tables derive ownership from their parent run or project rather than
-- carrying a duplicate user_id, so ownership cannot drift out of sync.

alter table public.profiles           enable row level security;
alter table public.projects           enable row level security;
alter table public.research_runs      enable row level security;
alter table public.run_events         enable row level security;
alter table public.agent_tasks        enable row level security;
alter table public.search_queries     enable row level security;
alter table public.run_jobs           enable row level security;
alter table public.literature_records enable row level security;
alter table public.patent_records     enable row level security;
alter table public.evidence_records   enable row level security;
alter table public.report_sections    enable row level security;
alter table public.citations          enable row level security;
alter table public.documents          enable row level security;
alter table public.document_chunks    enable row level security;
alter table public.run_errors         enable row level security;
alter table public.usage_records      enable row level security;
alter table public.provider_cache     enable row level security;

-- ---------------------------------------------------------------- helpers ---

create or replace function public.owns_run(target_run_id uuid)
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

create or replace function public.owns_document(target_document_id uuid)
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

-- --------------------------------------------------------- direct ownership ---

create policy profiles_self on public.profiles
  for all to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

create policy projects_own on public.projects
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy research_runs_own on public.research_runs
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy documents_own on public.documents
  for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy usage_records_own on public.usage_records
  for select to authenticated
  using (user_id = (select auth.uid()));

-- ------------------------------------------------------- derived from run ---
-- Read-only for users. All writes happen through the backend service role,
-- so a compromised browser token cannot forge evidence or citations.

create policy run_events_read on public.run_events
  for select to authenticated using (public.owns_run(run_id));

create policy agent_tasks_read on public.agent_tasks
  for select to authenticated using (public.owns_run(run_id));

create policy search_queries_read on public.search_queries
  for select to authenticated using (public.owns_run(run_id));

create policy run_jobs_read on public.run_jobs
  for select to authenticated using (public.owns_run(run_id));

create policy literature_records_read on public.literature_records
  for select to authenticated using (public.owns_run(run_id));

create policy patent_records_read on public.patent_records
  for select to authenticated using (public.owns_run(run_id));

create policy evidence_records_read on public.evidence_records
  for select to authenticated using (public.owns_run(run_id));

create policy report_sections_read on public.report_sections
  for select to authenticated using (public.owns_run(run_id));

create policy citations_read on public.citations
  for select to authenticated using (public.owns_run(run_id));

create policy run_errors_read on public.run_errors
  for select to authenticated using (public.owns_run(run_id));

-- -------------------------------------------------- derived from document ---

create policy document_chunks_read on public.document_chunks
  for select to authenticated using (public.owns_document(document_id));

-- ----------------------------------------------------------- deny by default ---
-- provider_cache holds only public external API responses and is accessed
-- exclusively by the backend service role. No policy is granted to
-- authenticated users, so RLS denies all access through the anon key.

comment on table public.provider_cache is
  'Backend-only. RLS is enabled with no policy, so the anon key cannot read it. '
  'Contains public external API responses only - never user content.';
