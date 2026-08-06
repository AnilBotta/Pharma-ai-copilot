-- 0009 — Restrict system-level audit events to portfolio-wide roles.
--
-- The 0007 policy read:
--
--     using (project_id is null or private.can_access_project(project_id))
--
-- The `project_id is null` branch was intended for system events such as
-- migrations and configuration changes, but it made every one of them readable
-- by any signed-in user, including someone holding no role at all. Verified:
-- an outsider with zero projects and zero grants could still read the audit
-- trail.
--
-- System events reveal configuration history, template changes and
-- administrative actions. Those belong to auditors and portfolio-wide roles,
-- not to every account.

drop policy if exists audit_events_read on public.audit_events;

create policy audit_events_read on public.audit_events
  for select to authenticated
  using (
    case
      -- Project-scoped: visible to anyone who can see that project.
      when project_id is not null then private.can_access_project(project_id)
      -- System-scoped: portfolio-wide roles only (auditor, QA, exec, admin...).
      else private.is_portfolio_wide()
    end
  );
