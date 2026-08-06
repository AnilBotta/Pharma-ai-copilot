-- 0003 — Retrieved records, the evidence table, and the report.
--
-- evidence_records is the citation source of truth. Rows are written by
-- provider adapters BEFORE any synthesis node runs, and each is assigned a
-- stable marker (E1, E2, ...). Synthesis prompts receive only that marker list,
-- and the evidence reviewer rejects any marker in generated text that has no
-- corresponding row. A citation to a source that was never retrieved is
-- therefore structurally impossible rather than merely discouraged.

-- ------------------------------------------------------ literature_records ---

create table public.literature_records (
  id       uuid primary key default gen_random_uuid(),
  run_id   uuid not null references public.research_runs(id) on delete cascade,
  provider text not null check (provider in ('pubmed', 'europepmc', 'crossref', 'openalex')),

  title            text not null,
  abstract         text,
  authors          text[] not null default '{}',
  journal          text,
  publication_date date,
  publication_year integer,

  -- Identifiers. At least one must be present: a record we cannot point at is
  -- not usable as evidence.
  doi   text,
  pmid  text,
  pmcid text,
  url   text,

  publication_types text[] not null default '{}',
  is_preprint    boolean not null default false,
  is_open_access boolean not null default false,
  has_full_text  boolean not null default false,
  full_text      text,

  -- Extraction (populated by the literature agent)
  evidence_category text check (evidence_category in (
    'review', 'in_vitro', 'in_vivo', 'clinical', 'formulation',
    'toxicology', 'manufacturing', 'analytical', 'other'
  )),
  study_objective text,
  methods         text,
  materials       text,
  key_findings    text[] not null default '{}',
  limitations     text[] not null default '{}',
  relevance_note  text,
  relevance_score numeric(4,3) check (relevance_score between 0 and 1),

  raw          jsonb,
  retrieved_at timestamptz not null default now(),

  constraint literature_has_identifier check (
    doi is not null or pmid is not null or pmcid is not null or url is not null
  ),
  constraint full_text_requires_content check (
    not has_full_text or full_text is not null
  )
);

create index literature_run_idx  on public.literature_records (run_id, relevance_score desc nulls last);
create index literature_doi_idx  on public.literature_records (run_id, doi)  where doi is not null;
create index literature_pmid_idx on public.literature_records (run_id, pmid) where pmid is not null;

comment on constraint full_text_requires_content on public.literature_records is
  'Prevents claiming full text was reviewed when only an abstract was retrieved.';

-- ---------------------------------------------------------- patent_records ---

create table public.patent_records (
  id       uuid primary key default gen_random_uuid(),
  run_id   uuid not null references public.research_runs(id) on delete cascade,
  provider text not null check (provider in ('epo_ops', 'uspto')),

  title    text,
  abstract text,

  publication_number text not null,
  application_number text,
  family_id          text,
  kind_code          text,
  jurisdiction       text,

  -- The distinction the spec requires us to preserve and display.
  record_type text not null default 'published_application' check (record_type in (
    'published_application', 'granted_patent', 'family_record'
  )),

  priority_date    date,
  filing_date      date,
  publication_date date,

  applicants text[] not null default '{}',
  inventors  text[] not null default '{}',

  cpc_classifications text[] not null default '{}',
  ipc_classifications text[] not null default '{}',

  legal_status      text,
  legal_status_date date,

  url text,

  -- Comparison axes required by the patent agent
  technical_summary   text,
  formulation         text,
  material            text,
  delivery_route      text,
  release_mechanism   text,
  claimed_application text,

  relevance_score numeric(4,3) check (relevance_score between 0 and 1),
  raw             jsonb,
  retrieved_at    timestamptz not null default now()
);

create index patent_run_idx    on public.patent_records (run_id, relevance_score desc nulls last);
create index patent_family_idx on public.patent_records (run_id, family_id) where family_id is not null;
create unique index patent_pubnum_uniq on public.patent_records (run_id, publication_number);

comment on column public.patent_records.legal_status is
  'Indicative only. Never the basis of a freedom-to-operate or validity conclusion.';

-- -------------------------------------------------------- evidence_records ---

create table public.evidence_records (
  id     uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.research_runs(id) on delete cascade,

  -- Stable citation marker, unique within a run. Rendered as [E12].
  marker text not null check (marker ~ '^E[0-9]+$'),

  source_type text not null check (source_type in ('literature', 'patent', 'internal_document')),
  provider    text not null,

  title   text not null,
  authors text[] not null default '{}',

  identifier_type text check (identifier_type in (
    'doi', 'pmid', 'pmcid', 'patent_number', 'document', 'url'
  )),
  identifier text,

  publication_date date,
  url              text,

  retrieved_text text,

  -- What we actually had access to. Displayed in the UI and honoured in prose.
  access_level text not null check (access_level in (
    'full_text', 'abstract_only', 'metadata_only'
  )),

  evidence_category text,
  relevance_score   numeric(4,3) check (relevance_score between 0 and 1),
  retrieved_by_agent text not null,

  confidence text check (confidence in ('high', 'moderate', 'low')),
  claims_supported text[] not null default '{}',

  -- Back-references to the full retrieved record
  literature_record_id uuid references public.literature_records(id) on delete cascade,
  patent_record_id     uuid references public.patent_records(id) on delete cascade,
  document_chunk_id    uuid,

  retrieved_at timestamptz not null default now(),

  unique (run_id, marker)
);

create index evidence_run_idx  on public.evidence_records (run_id, marker);
create index evidence_type_idx on public.evidence_records (run_id, source_type);

comment on table public.evidence_records is
  'Citation source of truth. Populated from retrieved provider records before '
  'synthesis. The model selects markers from this table; it never invents them.';

-- ---------------------------------------------------------- report_sections ---

create table public.report_sections (
  id       uuid primary key default gen_random_uuid(),
  run_id   uuid not null references public.research_runs(id) on delete cascade,

  section_key text not null,
  position    integer not null,
  title       text not null,
  body_markdown text not null,

  -- Derived from evidence coverage and consistency, not model self-assessment.
  confidence text check (confidence in (
    'high', 'moderate', 'low', 'insufficient_evidence'
  )),
  confidence_rationale text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (run_id, section_key)
);

create index report_sections_run_idx on public.report_sections (run_id, position);

create trigger report_sections_set_updated_at
  before update on public.report_sections
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------- citations ---
-- Join between a report section and the evidence it cites. `verified` is set
-- by the evidence reviewer only after the marker is confirmed to resolve.

create table public.citations (
  id                uuid primary key default gen_random_uuid(),
  run_id            uuid not null references public.research_runs(id) on delete cascade,
  report_section_id uuid not null references public.report_sections(id) on delete cascade,
  evidence_id       uuid not null references public.evidence_records(id) on delete cascade,
  marker            text not null,
  verified          boolean not null default false,
  created_at        timestamptz not null default now(),
  unique (report_section_id, evidence_id)
);

create index citations_run_idx      on public.citations (run_id);
create index citations_evidence_idx on public.citations (evidence_id);
