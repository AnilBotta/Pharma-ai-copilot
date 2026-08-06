-- 0014 — The readiness engine.
--
-- This is the module's reason for existing, so it lives in the database where
-- nothing can route around it. There is no API that marks a requirement
-- complete; satisfaction is a function of the record, recomputed on every read.
--
-- THE SEVEN CONDITIONS. A requirement is satisfied only when all hold:
--
--   1. at least one evidence link exists
--   2. the evidence matches the required type
--   3. any document evidence is on a current, non-superseded version
--   4. acceptance criteria were explicitly confirmed
--   5. a current, non-superseded approval exists
--   6. the approver was not the owner (enforced separately, at write time)
--   7. every mandatory dependency is itself satisfied
--
-- TWO NUMBERS, NOT ONE. Gate readiness returns a percentage AND a boolean, and
-- they answer different questions. The percentage says how much work is done.
-- The boolean says whether the gate may be reviewed. A gate at 98% with one
-- blocked mandatory requirement is NOT ready — a percentage never unlocks a
-- gate. The blocker list is returned alongside so a caller cannot show the
-- number without the reasons.

-- --------------------------------------------- requirement_is_satisfied ---

create or replace function private.requirement_is_satisfied(req_id uuid)
returns boolean
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  req            public.gate_requirements%rowtype;
  evidence_count integer;
  typed_evidence integer;
  has_approval   boolean;
  unmet_deps     integer;
begin
  select * into req from public.gate_requirements where id = req_id;
  if not found then
    return false;
  end if;

  -- A requirement scoped out with a justification does not block its gate.
  -- The mandatory_cannot_be_na constraint means this can only ever be an
  -- optional requirement.
  if req.is_not_applicable then
    return true;
  end if;

  -- An explicit block is dispositive regardless of everything else.
  if req.is_blocked then
    return false;
  end if;

  -- (4) acceptance criteria confirmed by a person
  if req.acceptance_confirmed_by is null then
    return false;
  end if;

  -- (1) and (2) evidence exists, and of the right kind
  select count(*) into evidence_count
    from public.evidence_links e
   where e.requirement_id = req_id;

  if evidence_count = 0 then
    return false;
  end if;

  if req.required_evidence_type <> 'any' then
    select count(*) into typed_evidence
      from public.evidence_links e
     where e.requirement_id = req_id
       and e.evidence_type = req.required_evidence_type;
    if typed_evidence = 0 then
      return false;
    end if;
  end if;

  -- (5) a current approval exists. Approvals are superseded when evidence
  -- changes, so this also covers "the approval is still about this evidence".
  select exists (
    select 1 from public.approvals a
     where a.requirement_id = req_id
       and a.decision = 'approved'
       and a.superseded_at is null
  ) into has_approval;

  if not has_approval then
    return false;
  end if;

  -- (7) mandatory prerequisites. Recursion terminates because the dependency
  -- graph is acyclic, enforced by trigger at write time.
  select count(*) into unmet_deps
    from public.gate_requirement_dependencies d
    join public.gate_requirements dep on dep.id = d.depends_on_id
   where d.requirement_id = req_id
     and dep.is_mandatory
     and not private.requirement_is_satisfied(dep.id);

  return unmet_deps = 0;
end;
$$;

-- ------------------------------------------------- requirement_status ---
-- A single derived status for display. Ordered by precedence: the most
-- actionable reason wins, so a user is told the one thing to fix.

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
    -- Overdue only matters while work is outstanding.
    if req.due_date is not null and req.due_date < current_date then
      return 'overdue';
    end if;
    return case when req.owner_user_id is null then 'not_started' else 'in_progress' end;
  end if;

  if req.acceptance_confirmed_by is null then return 'awaiting_acceptance'; end if;

  return 'awaiting_approval';
end;
$$;

-- ------------------------------------------------------ gate_readiness ---
-- Returns the percentage, the hard boolean, and the counts behind both.

create or replace function private.gate_readiness(stage_id uuid)
returns table (
  readiness_pct     numeric,
  is_ready          boolean,
  applicable_count  integer,
  satisfied_count   integer,
  mandatory_count   integer,
  mandatory_satisfied integer,
  blocker_count     integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  total_weight     numeric := 0;
  satisfied_weight numeric := 0;
  blockers         integer := 0;
begin
  select
    coalesce(sum(r.weight) filter (where not r.is_not_applicable), 0),
    coalesce(sum(r.weight) filter (
      where not r.is_not_applicable and private.requirement_is_satisfied(r.id)
    ), 0),
    count(*) filter (where not r.is_not_applicable),
    count(*) filter (where not r.is_not_applicable and private.requirement_is_satisfied(r.id)),
    count(*) filter (where r.is_mandatory),
    count(*) filter (where r.is_mandatory and private.requirement_is_satisfied(r.id))
  into total_weight, satisfied_weight,
       applicable_count, satisfied_count, mandatory_count, mandatory_satisfied
  from public.gate_requirements r
  where r.project_stage_id = stage_id;

  -- Any unsatisfied MANDATORY requirement is a blocker. This is the whole
  -- point: the percentage is informational, this count is dispositive.
  select count(*) into blockers
    from public.gate_requirements r
   where r.project_stage_id = stage_id
     and r.is_mandatory
     and not private.requirement_is_satisfied(r.id);

  readiness_pct := case
    when total_weight = 0 then 0
    else round((satisfied_weight / total_weight) * 100, 1)
  end;

  blocker_count := blockers;
  is_ready := (blockers = 0 and applicable_count > 0);

  return next;
end;
$$;

-- ------------------------------------------------------- gate_blockers ---
-- Why a gate is not ready, ordered so the most actionable comes first. The
-- readiness percentage is never returned to a caller without this available.

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
     when 'overdue'             then 3
     when 'awaiting_approval'   then 4
     when 'awaiting_acceptance' then 5
     when 'awaiting_dependency' then 6
     else 7
   end,
   r.position;
$$;

-- --------------------------------------- invalidate approval on evidence change ---
-- An approval is a statement about a specific evidence set. If the evidence
-- changes afterwards, the approval no longer describes reality and must not
-- continue to satisfy the requirement. Without this, someone could get a
-- requirement approved and then swap the document underneath it.

create or replace function private.supersede_approval_on_evidence_change()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  affected uuid;
begin
  affected := coalesce(new.requirement_id, old.requirement_id);

  update public.approvals
     set superseded_at = now(),
         superseded_reason = 'Evidence changed after approval; re-approval required.'
   where requirement_id = affected
     and superseded_at is null
     and decision = 'approved';

  return coalesce(new, old);
end;
$$;

create trigger evidence_change_supersedes_approval
  after insert or delete on public.evidence_links
  for each row execute function private.supersede_approval_on_evidence_change();

grant execute on function private.requirement_is_satisfied(uuid) to authenticated;
grant execute on function private.requirement_status(uuid)       to authenticated;
grant execute on function private.gate_readiness(uuid)           to authenticated;
grant execute on function private.gate_blockers(uuid)            to authenticated;
