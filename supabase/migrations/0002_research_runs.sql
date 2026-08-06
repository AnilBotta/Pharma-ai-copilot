-- 0002 — Research run lifecycle: runs, progress events, agent tasks,
-- search queries, and the durable job queue.

create type public.run_status as enum (
  'queued', 'running', 'awaiting_review', 'completed', 'failed', 'cancelled'
);

create type public.task_status as enum (
  'pending', 'running', 'completed', 'failed', 'skipped'
);

-- ---------------------------------------------------------- research_runs ---

create table public.research_runs (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references public.projects(id) on delete cascade,
  user_id       uuid not null references auth.users(id) on delete cascade,
  status        public.run_status not null default 'queued',

  -- Raw user input
  original_question       text not null check (length(trim(original_question)) > 0),
  molecule                text,
  indication              text,
  dosage_form             text,
  route_of_administration text,
  delivery_technology     text,
  development_stage       text,
  jurisdictions           text[] not null default '{}',
  date_from               integer,
  date_to                 integer,
  max_results             integer not null default 50 check (max_results between 1 and 200),
  additional_instructions text,

  -- Supervisor-derived structure (populated by the graph, not the user)
  structured_objective  jsonb,
  research_scope        jsonb,
  inclusion_criteria    jsonb,
  exclusion_criteria    jsonb,
  research_plan         jsonb,

  -- Cross-cutting findings
  contradictions      jsonb not null default '[]'::jsonb,
  evidence_gaps       jsonb not null default '[]'::jsonb,
  warnings            jsonb not null default '[]'::jsonb,
  section_confidence  jsonb not null default '{}'::jsonb,

  -- Lifecycle
  current_node      text,
  progress_pct      integer not null default 0 check (progress_pct between 0 and 100),
  error_message     text,
  cancel_requested  boolean not null default false,

  -- Usage rollups, maintained from usage_records
  total_input_tokens   bigint  not null default 0,
  total_output_tokens  bigint  not null default 0,
  estimated_cost_usd   numeric(12,6) not null default 0,

  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint date_range_ordered check (
    date_from is null or date_to is null or date_from <= date_to
  )
);

create index research_runs_user_idx    on public.research_runs (user_id, created_at desc);
create index research_runs_project_idx on public.research_runs (project_id, created_at desc);
create index research_runs_status_idx  on public.research_runs (status)
  where status in ('queued', 'running');

create trigger research_runs_set_updated_at
  before update on public.research_runs
  for each row execute function set_updated_at();

comment on column public.research_runs.cancel_requested is
  'Cooperative cancellation flag. The worker checks it between graph nodes.';

-- -------------------------------------------------------------- run_events ---
-- Append-only progress log. This is the real replacement for the prototype's
-- setTimeout step animation: the UI renders only what the worker actually
-- recorded. Tailed over SSE with `where id > $last_seen order by id`.

create table public.run_events (
  id          bigserial primary key,
  run_id      uuid not null references public.research_runs(id) on delete cascade,
  node        text,
  agent_id    text,
  event_type  text not null check (event_type in (
                'run_started', 'node_started', 'node_completed', 'node_failed',
                'tool_call', 'provider_result', 'evidence_stored',
                'warning', 'error', 'status', 'run_completed'
              )),
  message     text not null,
  data        jsonb,
  created_at  timestamptz not null default now()
);

create index run_events_run_id_idx on public.run_events (run_id, id);

comment on table public.run_events is
  'Append-only. Contains task summaries, tool activity and statuses only - '
  'never model reasoning tokens.';

-- ------------------------------------------------------------- agent_tasks ---

create table public.agent_tasks (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references public.research_runs(id) on delete cascade,
  node          text not null,
  agent_id      text not null,
  status        public.task_status not null default 'pending',
  summary       text,
  output        jsonb,
  model         text,
  input_tokens  integer not null default 0,
  output_tokens integer not null default 0,
  duration_ms   integer,
  retry_count   integer not null default 0,
  error         text,
  started_at    timestamptz,
  completed_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (run_id, node)
);

create index agent_tasks_run_idx on public.agent_tasks (run_id);

create trigger agent_tasks_set_updated_at
  before update on public.agent_tasks
  for each row execute function set_updated_at();

-- ----------------------------------------------------------- search_queries ---
-- Every query sent to every provider, so the user can see exactly what was
-- searched rather than a claim that something was searched.

create table public.search_queries (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid not null references public.research_runs(id) on delete cascade,
  node         text,
  provider     text not null,
  query_text   text not null,
  filters      jsonb,
  result_count integer,
  from_cache   boolean not null default false,
  duration_ms  integer,
  status       text not null default 'ok' check (status in ('ok', 'failed', 'rate_limited', 'unavailable')),
  error        text,
  created_at   timestamptz not null default now()
);

create index search_queries_run_idx on public.search_queries (run_id, created_at);

-- ---------------------------------------------------------------- run_jobs ---
-- Durable queue. The worker claims work with
--   select ... for update skip locked
-- so multiple workers can run without Redis or an external broker.

create table public.run_jobs (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references public.research_runs(id) on delete cascade,
  status        text not null default 'queued'
                  check (status in ('queued', 'claimed', 'done', 'failed')),
  attempts      integer not null default 0,
  max_attempts  integer not null default 3,
  claimed_by    text,
  claimed_at    timestamptz,
  available_at  timestamptz not null default now(),
  last_error    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index run_jobs_claimable_idx
  on public.run_jobs (available_at)
  where status = 'queued';

create index run_jobs_run_idx on public.run_jobs (run_id);

create trigger run_jobs_set_updated_at
  before update on public.run_jobs
  for each row execute function set_updated_at();
