-- 0008 — Fix infinite recursion in the user_roles RLS policy.
--
-- The 0007 policy read like this:
--
--     using (
--       user_id = auth.uid()
--       or exists (select 1 from public.user_roles ur join ... )
--     )
--
-- The subquery reads public.user_roles, which re-invokes this same policy,
-- which runs the subquery again. Postgres detects the cycle and raises
-- 42P17 infinite recursion.
--
-- It did not surface immediately because the first branch short-circuits: any
-- user who holds at least one role grant is satisfied by `user_id = auth.uid()`
-- before the EXISTS is ever evaluated. Only a user with NO grants falls through
-- to the recursive branch. That is precisely the case light testing misses,
-- and it would have failed for every new user on their first request.
--
-- The fix is to answer "is this caller portfolio-wide?" from a SECURITY DEFINER
-- function in `private`, which runs with the definer's rights and therefore
-- does not re-enter the policy.

create or replace function private.is_portfolio_wide()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.user_roles ur
      join public.roles r on r.id = ur.role_id
     where ur.user_id = (select auth.uid())
       and r.is_portfolio_wide
       and (ur.expires_at is null or ur.expires_at > now())
  );
$$;

grant execute on function private.is_portfolio_wide() to authenticated;

drop policy if exists user_roles_read on public.user_roles;

create policy user_roles_read on public.user_roles
  for select to authenticated
  using (
    user_id = (select auth.uid())
    or private.is_portfolio_wide()
  );

-- can_access_project has the same shape but was never recursive: it reads
-- user_roles from inside a SECURITY DEFINER function, so the policy does not
-- apply. Rewritten here to share the helper for consistency rather than to fix
-- a defect.
create or replace function private.can_access_project(target_project_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select
    exists (
      select 1 from public.projects p
       where p.id = target_project_id
         and p.user_id = (select auth.uid())
    )
    or private.is_portfolio_wide()
    or exists (
      select 1 from public.user_roles ur
       where ur.user_id = (select auth.uid())
         and ur.project_id = target_project_id
         and (ur.expires_at is null or ur.expires_at > now())
    );
$$;
