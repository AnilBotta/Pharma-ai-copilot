-- 0001 — Extensions, shared helpers, and core ownership tables.
--
-- pgvector is enabled here but is used by exactly one table
-- (document_chunks.embedding). Literature and patent retrieval are structured
-- SQL queries against indexed identifier columns, never vector similarity.

create extension if not exists "pgcrypto";      -- gen_random_uuid()
create extension if not exists "vector";        -- document embeddings only

-- ---------------------------------------------------------------- helpers ---

create or replace function set_updated_at()
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

-- --------------------------------------------------------------- profiles ---
-- One row per authenticated user. Single-organisation MVP: every profile
-- belongs to the same implicit org, so there is no organisations table yet.

create table public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  full_name   text,
  title       text,
  department  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function set_updated_at();

-- Create a profile automatically whenever a user signs up.
create or replace function public.handle_new_user()
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

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- --------------------------------------------------------------- projects ---

create table public.projects (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  name         text not null check (length(trim(name)) > 0),
  code         text,
  description  text,
  molecule     text,
  indication   text,
  is_seed      boolean not null default false,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index projects_user_id_idx on public.projects (user_id, created_at desc);

create trigger projects_set_updated_at
  before update on public.projects
  for each row execute function set_updated_at();

comment on column public.projects.is_seed is
  'Marks the shipped demo project. Seeded projects contain a research question '
  'and parameters only - never pre-baked results.';
