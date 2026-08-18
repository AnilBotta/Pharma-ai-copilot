-- 0025 — Stage 8: making the document tables from 0004 actually usable.
--
-- 0004 created `documents` and `document_chunks` with a full status machine
-- (pending -> extracting -> embedding -> ready | failed) and nothing ever wrote
-- to them. This migration adds the three things ingest needs and no more; the
-- schema was well designed and does not want redesigning.
--
-- WHY A STATUS COLUMN IS NOT ENOUGH ON ITS OWN
--
-- Ingest runs inside the worker tick, which on Vercel is killed at 300 s. A
-- large PDF can exhaust that part-way through extraction. Without a record of
-- WHEN a document was picked up, that row sits in `extracting` forever while
-- the interface cheerfully reports "processing" - a status that is false and
-- that never corrects itself. Nobody is told, because from the outside a stuck
-- document and a slow one are identical.
--
-- That is the same shape as the notification backlog: a row in a state that
-- looks like progress, with nothing able to move it on. `claimed_at` makes the
-- distinction observable, and `attempts` stops a file that cannot be parsed
-- from being retried every minute until the end of time.

-- ------------------------------------------------------------ the bucket ---
-- Private, and deliberately WITHOUT any policy on storage.objects.
--
-- Every access is mediated by the backend, which checks ownership and then
-- mints a short-lived signed URL; a signed URL carries its own token and does
-- not consult RLS. So there is nothing for a policy to add here, and declining
-- to write one avoids issuing DDL against a table owned by
-- supabase_storage_admin - which is the exact shape of statement that was
-- refused with 42501 when 0018 first tried `alter database ... set`.
--
-- Idempotent: if the bucket was created in the dashboard instead, this is a
-- no-op rather than an error.

insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;

-- -------------------------------------------------------- ingest bookkeeping ---

alter table public.documents
  add column if not exists claimed_at timestamptz,
  add column if not exists attempts   integer not null default 0;

comment on column public.documents.claimed_at is
  'When a worker took this document for processing. A row claimed longer ago '
  'than the reclaim window was interrupted mid-ingest and is returned to '
  'pending, rather than appearing to be in progress forever.';

comment on column public.documents.attempts is
  'Ingest attempts made. Bounded so a file that cannot be parsed fails visibly '
  'instead of being retried on every tick.';

-- Finding the next document to work on. Partial, because the queue is only
-- ever the small set that is not finished.
create index if not exists documents_ingest_queue_idx
  on public.documents (status, claimed_at)
  where status in ('pending', 'extracting', 'embedding');

-- ------------------------------------------------------- embedding backlog ---
-- Extraction writes every chunk with a null embedding and vectors are filled in
-- batches across ticks, so "which chunks still need one" is asked constantly.
-- A document is `ready` only when this returns nothing for it, which is what
-- makes readiness a fact about the data rather than a flag somebody set.

create index if not exists document_chunks_pending_idx
  on public.document_chunks (document_id)
  where embedding is null;

comment on table public.document_chunks is
  'Chunked text of an uploaded document. Written with a null embedding during '
  'extraction and filled in batches, so a large document progresses across '
  'several worker ticks instead of dying at the host function timeout. Page '
  'and heading are retained so a citation can name "filename, p. 12".';
