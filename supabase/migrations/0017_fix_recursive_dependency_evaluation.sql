-- 0017 — The readiness engine could recurse infinitely. Fixed.
--
-- SYMPTOM
--
--   select private.requirement_is_satisfied($1)
--   ERROR: stack depth limit exceeded
--
-- Reproduced on a requirement with evidence, acceptance and an approval, and
-- with `gate_requirement_dependencies` COMPLETELY EMPTY. A requirement with no
-- prerequisites at all recursed until the stack ran out.
--
-- CAUSE
--
-- 0014 expressed the prerequisite check as a single query with the recursive
-- call in the WHERE clause:
--
--     select count(*) into unmet_deps
--       from public.gate_requirement_dependencies d
--       join public.gate_requirements dep on dep.id = d.depends_on_id
--      where d.requirement_id = req_id
--        and dep.is_mandatory
--        and not private.requirement_is_satisfied(dep.id);   -- <-- here
--
-- The author's intent - "for each prerequisite, ask whether it is satisfied" -
-- is not what that says. SQL is declarative: the planner may apply the quals in
-- any order it likes. Given these row counts it chose to scan
-- `gate_requirements` as `dep` and apply the function filter BEFORE the join
-- restriction to `req_id`, calling requirement_is_satisfied() once per row in
-- the whole table - including on the very requirement being evaluated. That
-- call re-entered the same query, and so on down.
--
-- The comment above the query claimed "recursion terminates because the
-- dependency graph is acyclic". True, and irrelevant: the recursion was not
-- following the dependency graph at all.
--
-- Nothing was wrong with the data and nothing was wrong with the cycle trigger.
-- The bug was latent from the day 0014 shipped and surfaced only when the
-- planner's estimates changed - which is the worst property a defect in a gate
-- decision can have, because it means the engine's behaviour depends on table
-- statistics rather than on the record.
--
-- FIX
--
-- Fetch the prerequisites first, then recurse in procedural code. A plpgsql FOR
-- loop executes exactly once per row the query returned, and the planner cannot
-- hoist the call out of it. The recursion now genuinely follows the dependency
-- edges, so the acyclicity argument finally holds.
--
-- Both functions carrying this pattern are corrected.

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
  dep_id         uuid;
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

  -- (5) a current approval exists. Approvals are superseded when evidence or
  -- acceptance changes, so this also covers "the approval is still about this
  -- evidence and this claim".
  select exists (
    select 1 from public.approvals a
     where a.requirement_id = req_id
       and a.decision = 'approved'
       and a.superseded_at is null
  ) into has_approval;

  if not has_approval then
    return false;
  end if;

  -- (7) mandatory prerequisites, walked one edge at a time. The recursive call
  -- lives in the loop body, not in a WHERE clause, so it runs once per actual
  -- dependency and cannot be reordered by the planner. Termination now rests on
  -- the acyclicity the cycle trigger enforces, as intended.
  for dep_id in
    select d.depends_on_id
      from public.gate_requirement_dependencies d
      join public.gate_requirements dep on dep.id = d.depends_on_id
     where d.requirement_id = req_id
       and dep.is_mandatory
  loop
    if not private.requirement_is_satisfied(dep_id) then
      return false;
    end if;
  end loop;

  return true;
end;
$$;

-- The same pattern, the same fix.
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
  dep_id uuid;
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

  for dep_id in
    select d.depends_on_id
      from public.gate_requirement_dependencies d
      join public.gate_requirements dep on dep.id = d.depends_on_id
     where d.requirement_id = req_id
       and dep.is_mandatory
  loop
    if not private.requirement_is_satisfied(dep_id) then
      return 'awaiting_dependency';
    end if;
  end loop;

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

  -- Evidence of the wrong kind is its own problem: telling the owner to chase
  -- an approver would send them somewhere approval could not have helped.
  if req.required_evidence_type <> 'any' then
    select count(*) into typed_evidence
      from public.evidence_links
     where requirement_id = req_id
       and evidence_type = req.required_evidence_type;
    if typed_evidence = 0 then
      return 'wrong_evidence_type';
    end if;
  end if;

  if req.acceptance_confirmed_by is null then return 'awaiting_acceptance'; end if;

  return 'awaiting_approval';
end;
$$;
