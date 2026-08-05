-- 0010 — Lock down the LangGraph checkpoint tables, and pin a function's
-- search_path.
--
-- SECURITY FIX.
--
-- `AsyncPostgresSaver.setup()` creates checkpoints, checkpoint_blobs,
-- checkpoint_writes and checkpoint_migrations in `public` with no RLS. Because
-- `public` is PostgREST-exposed, that made them readable with the anon key —
-- the same publishable key that ships in the browser bundle by design.
--
-- Verified before the fix: the anon role could read 11 checkpoints, 102 writes
-- and 45 blobs. Checkpoint blobs contain the serialised graph state of a
-- research run: retrieved evidence, agent findings and draft report text. This
-- was a genuine data exposure, not a theoretical one.
--
-- The tables were created by a library at runtime rather than by a migration,
-- which is why they escaped the RLS applied in 0005. Anything a library
-- auto-creates in `public` needs the same treatment.
--
-- RLS is enabled with NO policy: deny-all. Only the worker touches these, and
-- it connects as service_role, which bypasses RLS. Nothing legitimate breaks.

alter table public.checkpoints           enable row level security;
alter table public.checkpoint_blobs      enable row level security;
alter table public.checkpoint_writes     enable row level security;
alter table public.checkpoint_migrations enable row level security;

revoke all on public.checkpoints           from anon, authenticated;
revoke all on public.checkpoint_blobs      from anon, authenticated;
revoke all on public.checkpoint_writes     from anon, authenticated;
revoke all on public.checkpoint_migrations from anon, authenticated;

comment on table public.checkpoints is
  'LangGraph workflow checkpoints. Backend-only: RLS enabled with no policy, so '
  'deny-all through the anon and authenticated keys. Contains serialised graph '
  'state including retrieved evidence and draft report text.';

-- ------------------------------------------------------------------ 0011 lint ---
-- private.reject_audit_mutation was created without `set search_path`. Every
-- other function in `private` pins it; this one was missed. A mutable
-- search_path in a function that runs on every audit write is worth closing
-- even though this particular body only raises.

create or replace function private.reject_audit_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception
    'audit_events is append-only; % is not permitted', tg_op
    using errcode = 'insufficient_privilege';
end;
$$;
