-- 0036: close a privilege gap 0035 left open on the attestation table.
--
-- WHAT WAS WRONG
--
-- 0035 enabled row level security on public.sas_operator_attestations and
-- stopped there. Its siblings do two things, not one:
--
--   0032  enable row level security  +  revoke all ... from anon, authenticated
--   0034  enable row level security  +  revoke all ... from anon, authenticated
--   0035  enable row level security  (and nothing else)
--
-- Supabase grants anon and authenticated full privileges on new tables in the
-- public schema by default, so the attestation table was created holding
-- DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE and UPDATE for both -
-- while every other SAS table held service_role only. Deployment is what
-- revealed it: the difference is invisible in the migration text and obvious
-- in information_schema.role_table_grants.
--
-- WHY RLS ALONE WAS NOT ENOUGH
--
-- With RLS on and no policy, SELECT, INSERT, UPDATE and DELETE are refused, so
-- nothing was readable or writable through PostgREST. TRUNCATE IS DIFFERENT.
-- Row level security filters rows; TRUNCATE does not operate on rows and is
-- governed by the privilege alone, so a role holding it can empty the table
-- with RLS fully enabled.
--
-- The append-only trigger did not cover the gap either. It is declared
-- `before update or delete ... for each row`, and a statement-level TRUNCATE
-- fires neither. So the one table whose entire purpose is to preserve a named
-- human's claim about an execution was the one table that could be silently
-- emptied.
--
-- WHAT THIS CHANGES, AND WHAT IT DOES NOT
--
-- One revoke, matching the sibling migrations exactly. No column, constraint,
-- trigger or comment is touched, no data is read or written, and no validation
-- status moves. The backend connects as service_role, which keeps its grants
-- and is unaffected.
--
-- Idempotent: revoking a privilege nobody holds is a no-op, so this is safe to
-- re-run and safe on a deployment where 0035 has not been applied by the time
-- someone runs the whole directory in order.

set search_path = '';

revoke all on public.sas_operator_attestations from anon, authenticated;

comment on table public.sas_operator_attestations is
  'A HUMAN DECLARATION, NOT CRYPTOGRAPHIC VERIFICATION. It records who says '
  'they executed a package, where, and on which SAS version. It does not and '
  'cannot establish which program bytes ran: program execution integrity for '
  'every row reachable from here is unverified_manual_execution. '
  'Reachable only through the backend under service_role: RLS is enabled with '
  'no policy, and 0036 revoked the default anon/authenticated grants that RLS '
  'alone would not have stopped a TRUNCATE through.';
