-- 0015 — Report the wrong-evidence-type case distinctly.
--
-- Found while verifying the engine. A requirement demanding a document, given
-- only a note, was correctly NOT satisfied — but its status read
-- 'awaiting_approval', which tells the owner to chase an approver when the real
-- problem is that the evidence is the wrong kind. Approving it would not help;
-- the engine would still refuse.
--
-- The engine was right and the explanation was wrong, which is its own kind of
-- failure: a blocker nobody can act on is nearly as bad as no blocker at all.

create or replace function private.requirement_status(req_id uuid)
returns text
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  req public.gate_requirements%rowtype;
  evidence_count integer;
  typed_evidence integer;
  latest_decision text;
  unmet_deps integer;
begin
  select * into req from public.gate_requirements where id = req_id;
  if not found then return 'unknown'; end if;

  if req.is_not_applicable then return 'not_applicable'; end if;
  if req.is_blocked        then return 'blocked';        end if;

  select decision into latest_decision
    from public.approvals
   where requirement_id = req_id and superseded_at is null
   order by approved_at desc limit 1;

  if latest_decision = 'rejected' then return 'changes_requested'; end if;

  select count(*) into unmet_deps
    from public.gate_requirement_dependencies d
    join public.gate_requirements dep on dep.id = d.depends_on_id
   where d.requirement_id = req_id
     and dep.is_mandatory
     and not private.requirement_is_satisfied(dep.id);

  if unmet_deps > 0 then return 'awaiting_dependency'; end if;

  if private.requirement_is_satisfied(req_id) then return 'approved'; end if;

  select count(*) into evidence_count
    from public.evidence_links where requirement_id = req_id;

  if evidence_count = 0 then
    if req.due_date is not null and req.due_date < current_date then
      return 'overdue';
    end if;
    return case when req.owner_user_id is null then 'not_started' else 'in_progress' end;
  end if;

  -- Evidence exists but none of it is the required kind. Checked before the
  -- acceptance and approval states so the owner is told the actionable thing.
  if req.required_evidence_type <> 'any' then
    select count(*) into typed_evidence
      from public.evidence_links e
     where e.requirement_id = req_id
       and e.evidence_type = req.required_evidence_type;
    if typed_evidence = 0 then
      return 'wrong_evidence_type';
    end if;
  end if;

  if req.acceptance_confirmed_by is null then return 'awaiting_acceptance'; end if;

  return 'awaiting_approval';
end;
$$;

create or replace function private.gate_blockers(stage_id uuid)
returns table (
  requirement_id uuid,
  ref_code       text,
  title          text,
  status         text,
  reason         text,
  owner_user_id  uuid,
  due_date       date
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    r.id,
    r.ref_code,
    r.title,
    private.requirement_status(r.id),
    case private.requirement_status(r.id)
      when 'blocked'             then coalesce(r.blocked_reason, 'Blocked.')
      when 'changes_requested'   then 'Approver requested changes.'
      when 'awaiting_dependency' then 'A prerequisite requirement is not yet satisfied.'
      when 'wrong_evidence_type' then
        'Evidence attached is not of the required type ('
        || r.required_evidence_type || '). Approving will not satisfy this.'
      when 'awaiting_approval'   then 'Evidence attached and accepted; awaiting approval.'
      when 'awaiting_acceptance' then 'Evidence attached; acceptance criteria not yet confirmed.'
      when 'overdue'             then 'Past its due date with no evidence attached.'
      when 'not_started'         then 'Not started; no owner assigned.'
      else 'In progress; required evidence not yet complete.'
    end,
    r.owner_user_id,
    r.due_date
  from public.gate_requirements r
 where r.project_stage_id = stage_id
   and r.is_mandatory
   and not private.requirement_is_satisfied(r.id)
 order by
   case private.requirement_status(r.id)
     when 'blocked'             then 1
     when 'changes_requested'   then 2
     when 'wrong_evidence_type' then 3
     when 'overdue'             then 4
     when 'awaiting_approval'   then 5
     when 'awaiting_acceptance' then 6
     when 'awaiting_dependency' then 7
     else 8
   end,
   r.position;
$$;
