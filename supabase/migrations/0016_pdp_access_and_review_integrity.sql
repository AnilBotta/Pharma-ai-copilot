-- 0016 — Three corrections needed before the Phase C API can be trusted.
--
-- 1. A CHECK CONSTRAINT THAT CHECKED NOTHING.
--
--    0013 declared:
--
--        constraint reviewer_is_not_owner check (true)
--
--    named as though it enforced independent review, evaluating to `true` for
--    every row. A CHECK constraint cannot reference another table, so the rule
--    was unenforceable in that form and the name was simply wrong. Anyone
--    reading the schema — including a future author of this module — would have
--    concluded that self-review was impossible. It was not. Replaced with a
--    trigger that actually enforces it.
--
-- 2. AUTHORISATION THE SERVICE ROLE CAN ASK ABOUT.
--
--    private.can_access_project() reads auth.uid(). The API connects as the
--    service role, where auth.uid() is null, so the API could not reuse the
--    rule and would have had to restate it in Python. Two copies of an access
--    rule is one copy too many: they drift, and the drift is a security bug.
--
--    The rule now lives in private.user_can_access_project(user, project), and
--    can_access_project() delegates to it with auth.uid(). RLS and the API
--    therefore enforce the same predicate by construction.
--
-- 3. AN APPROVAL THAT OUTLIVED THE CLAIM IT AGREED WITH. See the trigger at the
--    foot of this file.

-- --------------------------------------------- explicit-user access predicates ---

create or replace function private.user_can_access_project(
  p_user_id    uuid,
  p_project_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select p_user_id is not null and (
    exists (
      select 1 from public.projects p
       where p.id = p_project_id
         and p.user_id = p_user_id
    )
    or exists (
      select 1
        from public.user_roles ur
        join public.roles r on r.id = ur.role_id
       where ur.user_id = p_user_id
         and (ur.expires_at is null or ur.expires_at > now())
         and (r.is_portfolio_wide or ur.project_id = p_project_id)
    )
  );
$$;

comment on function private.user_can_access_project(uuid, uuid) is
  'Single definition of project visibility. RLS calls it with auth.uid(); the '
  'API calls it with the user id verified from the bearer token. Both paths '
  'therefore enforce the same rule.';

-- Rewritten to delegate. Behaviour for RLS is unchanged.
create or replace function private.can_access_project(target_project_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select private.user_can_access_project((select auth.uid()), target_project_id);
$$;

-- Capabilities a user holds on a project, resolved from their unexpired role
-- grants. Returned as one row rather than three functions so a caller cannot
-- check one and forget another.
create or replace function private.user_capabilities(
  p_user_id    uuid,
  p_project_id uuid
)
returns table (
  can_access        boolean,
  can_approve       boolean,
  can_gate          boolean,
  is_portfolio_wide boolean,
  is_project_owner  boolean,
  role_keys         text[]
)
language sql
stable
security definer
set search_path = ''
as $$
  with grants as (
    select r.key, r.can_approve, r.can_gate, r.is_portfolio_wide
      from public.user_roles ur
      join public.roles r on r.id = ur.role_id
     where ur.user_id = p_user_id
       and (ur.expires_at is null or ur.expires_at > now())
       -- A project-scoped grant applies only to that project; a global grant
       -- (null project_id) applies everywhere.
       and (ur.project_id is null or ur.project_id = p_project_id)
  )
  select
    private.user_can_access_project(p_user_id, p_project_id),
    coalesce(bool_or(g.can_approve), false),
    coalesce(bool_or(g.can_gate), false),
    coalesce(bool_or(g.is_portfolio_wide), false),
    exists (
      select 1 from public.projects p
       where p.id = p_project_id and p.user_id = p_user_id
    ),
    coalesce(array_agg(g.key order by g.key) filter (where g.key is not null), '{}')
  from grants g;
$$;

grant execute on function private.user_can_access_project(uuid, uuid) to authenticated;
grant execute on function private.user_capabilities(uuid, uuid)       to authenticated;

-- ------------------------------------------------- independent review, for real ---

alter table public.reviews drop constraint if exists reviewer_is_not_owner;

create or replace function private.enforce_independent_review()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  req_owner uuid;
begin
  select owner_user_id into req_owner
    from public.gate_requirements
   where id = new.requirement_id;

  if req_owner is not null and req_owner = new.reviewer_id then
    raise exception
      'independent review: the owner of a requirement cannot review it'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$;

create or replace trigger reviews_independent_reviewer
  before insert on public.reviews
  for each row execute function private.enforce_independent_review();

comment on trigger reviews_independent_reviewer on public.reviews is
  'Replaces a CHECK constraint of the same intent that evaluated to true for '
  'every row. Cross-table conditions require a trigger.';

-- ------------------------------------- acceptance withdrawal supersedes approval ---
--
-- 0014 supersedes an approval when EVIDENCE changes, closing the
-- swap-the-document-underneath-it hole. The same hole exists one step earlier.
--
-- Acceptance confirmation is one of the seven conditions: one person states the
-- criteria are met, a different person agrees. Withdrawing that statement after
-- approval left the approval row current. requirement_is_satisfied() correctly
-- returned false while acceptance was absent — but the stale approval satisfied
-- the requirement again the moment anyone re-confirmed, including a different
-- person against different criteria. The approver would then be recorded as
-- having agreed with a claim they never saw.

create or replace function private.supersede_approval_on_acceptance_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.acceptance_confirmed_by is distinct from old.acceptance_confirmed_by then
    update public.approvals
       set superseded_at = now(),
           superseded_reason =
             'Acceptance confirmation changed after approval; re-approval required.'
     where requirement_id = new.id
       and superseded_at is null
       and decision = 'approved';
  end if;
  return new;
end;
$$;

create or replace trigger acceptance_change_supersedes_approval
  after update of acceptance_confirmed_by on public.gate_requirements
  for each row execute function private.supersede_approval_on_acceptance_change();

-- ------------------------------------------------------------------- indexes ---

create index if not exists approvals_project_idx on public.approvals (project_id, approved_at desc);
create index if not exists reviews_project_idx   on public.reviews (project_id, reviewed_at desc);
