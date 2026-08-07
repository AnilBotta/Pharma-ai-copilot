-- 0019 — Phase D: the controlled document register.
--
-- WHY THIS UNBLOCKS EVERYTHING
--
-- 43 of the 50 seeded requirements demand `document` evidence and 37 of those
-- are mandatory, so every gate has at least one. Until this table exists, no
-- gate in the system can reach is_ready. Phase C was complete but not pilotable.
--
-- NOT `public.documents`
--
-- That table already exists and means something else entirely: a file somebody
-- uploaded for retrieval, with a mime type, a byte count and vector embeddings.
-- A controlled document is a different object - it has a number, a version
-- history, an approval, an effective date, and a defined status - so it gets
-- its own name rather than being crammed into a table built for uploads.
--
-- THE FILE IS NOT COPIED HERE
--
-- `storage_url` is a link. The file of record stays in SharePoint, or wherever
-- the organisation already controls it. Copying the bytes would create a second
-- authoritative copy, and two authoritative copies of a controlled document is
-- precisely the failure this kind of system exists to prevent: the day they
-- disagree, nobody can say which one the gate was approved against.
--
-- What is stored is the metadata a gate decision depends on - which version,
-- what status, effective when, approved by whom - plus a checksum so a
-- substitution can at least be detected.
--
-- THE SEVENTH CONDITION FINALLY BECOMES REAL
--
-- The readiness engine documents seven conditions for a satisfied requirement.
-- The third - "any document evidence is on a current, non-superseded version" -
-- has never been enforced, because there was nothing to enforce it against. It
-- was a comment describing an intention. This migration makes it code: evidence
-- pointing at a superseded, obsolete, draft or expired version no longer
-- satisfies anything, and superseding a version invalidates the approvals that
-- rested on it.

-- ------------------------------------------------------ controlled_documents ---

create table public.controlled_documents (
  id          uuid primary key default gen_random_uuid(),

  -- Null means an organisation-wide document (an SOP, a policy) rather than one
  -- belonging to a single programme.
  project_id  uuid references public.projects(id) on delete cascade,

  -- The number people cite in meetings and in other documents. Unique because
  -- two documents sharing one number is how the wrong file gets approved.
  document_number text not null,
  title           text not null check (length(trim(title)) > 0),

  document_type text not null default 'other' check (document_type in (
    'protocol', 'report', 'specification', 'method', 'sop', 'batch_record',
    'risk_assessment', 'plan', 'summary', 'certificate', 'drawing', 'other'
  )),
  discipline text,
  description text,

  owner_user_id uuid references auth.users(id) on delete set null,

  -- False for working documents that are tracked but not under change control.
  -- A requirement can still cite one; the register simply does not pretend it
  -- carries the same weight.
  is_controlled boolean not null default true,

  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (document_number)
);

create index controlled_documents_project_idx
  on public.controlled_documents (project_id);
create index controlled_documents_owner_idx
  on public.controlled_documents (owner_user_id) where owner_user_id is not null;

create trigger controlled_documents_set_updated_at
  before update on public.controlled_documents
  for each row execute function private.set_updated_at();

comment on table public.controlled_documents is
  'The document register. Files are NOT stored here - storage_url on each '
  'version links to the file of record. See 0019 for why.';

-- ----------------------------------------------- controlled_document_versions ---

create table public.controlled_document_versions (
  id          uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.controlled_documents(id) on delete cascade,

  -- Free text because organisations number versions differently: "1.0",
  -- "Rev B", "v3 draft". Ordering comes from created_at, not from parsing this.
  version_label text not null check (length(trim(version_label)) > 0),

  -- The lifecycle. Only `approved` and `effective` may satisfy a requirement.
  status text not null default 'draft' check (status in (
    'draft', 'in_review', 'approved', 'effective', 'superseded', 'obsolete'
  )),

  --: A link, never a copy. See the header of this migration.
  storage_url text not null check (storage_url ~ '^https?://'),
  --: Checksum of the file as it stood when recorded, so a silent substitution
  --: in the external store can be detected later. Optional: many teams will
  --: not have one, and demanding it would only produce invented values.
  checksum text,

  effective_date date,
  --: A document past its review date is not current, whatever its status says.
  expiry_date   date,

  superseded_by_version_id uuid references public.controlled_document_versions(id)
    on delete set null,
  superseded_at timestamptz,

  approved_by uuid references auth.users(id) on delete set null,
  approved_at timestamptz,

  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (document_id, version_label),

  -- A version claiming approval must name who approved it and when. Without
  -- this, 'approved' is a word rather than a record.
  constraint approved_version_has_approver check (
    status not in ('approved', 'effective')
    or (approved_by is not null and approved_at is not null)
  ),
  constraint superseded_version_has_timestamp check (
    status <> 'superseded' or superseded_at is not null
  ),
  constraint expiry_after_effective check (
    effective_date is null or expiry_date is null or expiry_date >= effective_date
  )
);

-- At most one effective version per document. Two simultaneously effective
-- versions is the same disease as two documents sharing a number.
create unique index controlled_document_versions_one_effective
  on public.controlled_document_versions (document_id)
  where status = 'effective';

create index controlled_document_versions_doc_idx
  on public.controlled_document_versions (document_id, created_at desc);
create index controlled_document_versions_status_idx
  on public.controlled_document_versions (status);

create trigger controlled_document_versions_set_updated_at
  before update on public.controlled_document_versions
  for each row execute function private.set_updated_at();

-- Close the reference 0013 left open with `-- FK added in Phase D`.
alter table public.evidence_links
  add constraint evidence_document_version_fk
  foreign key (document_version_id)
  references public.controlled_document_versions(id) on delete restrict;

comment on constraint evidence_document_version_fk on public.evidence_links is
  'ON DELETE RESTRICT, not CASCADE: deleting a document version that a gate '
  'decision was based on must fail loudly rather than quietly erase the '
  'evidence behind an approval.';

create index evidence_links_document_version_idx
  on public.evidence_links (document_version_id) where document_version_id is not null;

-- --------------------------------------------------- is this version usable? ---

create or replace function private.document_version_is_usable(p_version_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.controlled_document_versions v
     where v.id = p_version_id
       and v.status in ('approved', 'effective')
       and (v.expiry_date is null or v.expiry_date >= current_date)
  );
$$;

comment on function private.document_version_is_usable(uuid) is
  'A version may support a requirement only while it is approved or effective '
  'and not past its expiry. Draft, in_review, superseded, obsolete and expired '
  'versions all fail.';

grant execute on function private.document_version_is_usable(uuid) to authenticated;

-- ------------------------------------------- the third condition, enforced ---

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
  unusable_docs  integer;
  has_approval   boolean;
  dep_id         uuid;
begin
  select * into req from public.gate_requirements where id = req_id;
  if not found then
    return false;
  end if;

  if req.is_not_applicable then
    return true;
  end if;

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

  -- (3) document evidence must be on a version that may still be relied on.
  --
  -- New in 0019. Until the register existed this condition was documented but
  -- unenforceable, so a requirement stayed satisfied after the document behind
  -- it was superseded. ANY unusable document link fails the requirement, not
  -- merely the absence of a usable one: a gate pack that cites an obsolete
  -- version is wrong even if it also cites a current one.
  select count(*) into unusable_docs
    from public.evidence_links e
   where e.requirement_id = req_id
     and e.evidence_type = 'document'
     and (
       e.document_version_id is null
       or not private.document_version_is_usable(e.document_version_id)
     );

  if unusable_docs > 0 then
    return false;
  end if;

  -- (5) a current approval exists
  select exists (
    select 1 from public.approvals a
     where a.requirement_id = req_id
       and a.decision = 'approved'
       and a.superseded_at is null
  ) into has_approval;

  if not has_approval then
    return false;
  end if;

  -- (7) mandatory prerequisites, walked one edge at a time.
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

-- ------------------------------------------------- and reported actionably ---

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
  unusable_docs integer;
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
    if req.due_date is not null and req.due_date < current_date then
      return 'overdue';
    end if;
    return case when req.owner_user_id is null then 'not_started' else 'in_progress' end;
  end if;

  -- Checked before acceptance and approval: re-approving will not help while
  -- the document behind the requirement is not one that may be relied on. A
  -- blocker nobody can act on is nearly as bad as no blocker.
  select count(*) into unusable_docs
    from public.evidence_links e
   where e.requirement_id = req_id
     and e.evidence_type = 'document'
     and (
       e.document_version_id is null
       or not private.document_version_is_usable(e.document_version_id)
     );

  if unusable_docs > 0 then
    return 'superseded_document';
  end if;

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
      when 'superseded_document' then
        'The document version cited is not approved, effective and in date. '
        'Attach the current version.'
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
     when 'superseded_document' then 3
     when 'wrong_evidence_type' then 4
     when 'overdue'             then 5
     when 'awaiting_approval'   then 6
     when 'awaiting_acceptance' then 7
     when 'awaiting_dependency' then 8
     else 9
   end,
   r.position;
$$;

-- ------------------------------- superseding a version invalidates approvals ---
--
-- The same rule 0014 applies to evidence changes and 0016 to acceptance
-- changes. An approval is a statement about a specific document version; once
-- that version is superseded the statement no longer describes anything anyone
-- can act on. requirement_is_satisfied() already returns false, but leaving the
-- approval row current would let the requirement spring back the moment the new
-- version was attached - approved, on paper, by someone who never saw it.

create or replace function private.supersede_approvals_on_document_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status is distinct from old.status
     and new.status in ('superseded', 'obsolete') then
    update public.approvals a
       set superseded_at = now(),
           superseded_reason =
             'The document version behind this approval was '
             || new.status || '; re-approval against the current version is required.'
     where a.superseded_at is null
       and a.decision = 'approved'
       and exists (
         select 1 from public.evidence_links e
          where e.requirement_id = a.requirement_id
            and e.document_version_id = new.id
       );
  end if;
  return new;
end;
$$;

create or replace trigger document_version_status_supersedes_approvals
  after update of status on public.controlled_document_versions
  for each row execute function private.supersede_approvals_on_document_change();

-- ------------------------------------------------------------------ policies ---

alter table public.controlled_documents         enable row level security;
alter table public.controlled_document_versions enable row level security;

-- Project documents follow project access; organisation-wide documents
-- (project_id is null) are readable by any signed-in user, which is what an SOP
-- is for.
create policy controlled_documents_read on public.controlled_documents
  for select to authenticated
  using (project_id is null or private.can_access_project(project_id));

create policy controlled_document_versions_read on public.controlled_document_versions
  for select to authenticated
  using (exists (
    select 1 from public.controlled_documents d
     where d.id = document_id
       and (d.project_id is null or private.can_access_project(d.project_id))
  ));
