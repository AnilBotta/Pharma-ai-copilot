-- 0031 — say who can approve a requirement, before somebody makes it nobody.
--
-- Three rules decide whether a person may approve a requirement, and each one
-- is correct on its own:
--
--   1. they must hold the role named in `approver_role_key`
--   2. they must not own the requirement            (trigger, 0013)
--   3. they must not have confirmed its acceptance  (trigger, 0013)
--
-- Together they can produce a state nobody intended. On a small team, where
-- one person may be the only holder of a role, confirming the acceptance on a
-- requirement that names *their* role removes the last eligible approver. The
-- requirement then sits at `awaiting_approval` for ever: the person with the
-- role is barred, and the person who is not barred lacks the role. It is
-- recoverable — withdraw the acceptance and let somebody else confirm it — but
-- until now nothing said so, and the two people involved could only observe
-- that the Approve button did nothing for either of them.
--
-- This function is the missing fact. It answers "who could approve this right
-- now", and — passed a hypothetical acceptor — "who would still be able to
-- approve if that person confirmed the acceptance". The first drives an
-- explanation when a requirement is already stuck; the second drives a warning
-- before it becomes stuck. Neither changes what is permitted: the triggers
-- remain the authority, and this only reports what they would decide.

create or replace function private.eligible_approvers(
  p_requirement uuid,
  p_hypothetical_acceptor uuid default null
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(jsonb_agg(t.person order by t.person ->> 'name'), '[]'::jsonb)
    from (
      select distinct jsonb_build_object(
               'user_id', ap.id,
               'name',    coalesce(ap.full_name, ap.email)
             ) as person
        from public.gate_requirements r
        join public.project_stages s on s.id = r.project_stage_id
        join public.user_roles ur    on true
        join public.roles rl         on rl.id = ur.role_id
        join public.profiles ap      on ap.id = ur.user_id
       where r.id = p_requirement
         and rl.can_approve
         -- A requirement that names no role may be approved by any approving
         -- role, which is how `_approver_role_for` reads it too.
         and (r.approver_role_key is null or rl.key = r.approver_role_key)
         and (ur.expires_at is null or ur.expires_at > now())
         and (ur.project_id is null or ur.project_id = s.project_id)
         -- The two segregation triggers, asked in advance.
         and ur.user_id is distinct from r.owner_user_id
         and ur.user_id is distinct from coalesce(p_hypothetical_acceptor,
                                                  r.acceptance_confirmed_by)
    ) t;
$$;

comment on function private.eligible_approvers(uuid, uuid) is
  'People who may approve this requirement under the segregation rules. Pass a '
  'user id as the second argument to ask who would remain eligible if that '
  'person confirmed the acceptance criteria.';

grant execute on function private.eligible_approvers(uuid, uuid) to authenticated;
