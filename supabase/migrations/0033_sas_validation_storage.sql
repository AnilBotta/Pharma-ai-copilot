-- 0033 — give SAS validation somewhere to put bytes.
--
-- 0032 modelled packages, runs and artifacts but stored no files: a package
-- existed as a manifest and a `files` jsonb, and an artifact carried a
-- `storage_ref` pointing at a bucket that did not exist. This adds the bucket
-- and the columns the archive needs, and nothing else — 0032's structures are
-- otherwise used as they stand.
--
-- WHY A STORED ARCHIVE RATHER THAN REGENERATION ON DOWNLOAD
--
-- `build_package` is deterministic, so regenerating on each download would
-- usually produce identical bytes. Usually is the problem. The generator reads
-- the model specification from be-stats, and a version bump would silently
-- change what a customer downloads under a package id that is supposed to be
-- immutable — the one property the whole scheme rests on.
--
-- So the archive is built once, hashed, and stored. Every later download
-- returns the exact stored bytes. A package's identity and its contents then
-- cannot drift apart, whatever happens to the code that made it.

set search_path = '';

-- ------------------------------------------------------------ the bucket ---
-- Private, and deliberately WITHOUT any policy on storage.objects — the same
-- reasoning as 0025's `documents` bucket, and for the same practical reason:
-- DDL against a table owned by supabase_storage_admin is refused with 42501
-- in this deployment.
--
-- Every access is mediated by the backend under the service role, which checks
-- authorization and then mints a short-lived signed URL. A signed URL carries
-- its own token and does not consult RLS, so a policy would add nothing.
--
-- Idempotent: if the bucket was created in the dashboard, this is a no-op.
--
-- `public` is FALSE and must stay false. These objects are regulatory
-- validation evidence and customer-run SAS output; a permanently public URL
-- for any of it would be a disclosure that cannot be withdrawn.
insert into storage.buckets (id, name, public)
values ('sas-validation', 'sas-validation', false)
on conflict (id) do nothing;

-- ------------------------------------------------------ archive columns ---

alter table public.sas_validation_packages
  add column if not exists archive_storage_path text,
  add column if not exists archive_sha256       text,
  add column if not exists archive_bytes        bigint;

comment on column public.sas_validation_packages.archive_storage_path is
  'Object key in the private sas-validation bucket. The archive is built once '
  'at generation and never rebuilt: every download returns these exact bytes, '
  'so a package''s identity and its contents cannot drift apart.';

comment on column public.sas_validation_packages.archive_sha256 is
  'SHA-256 of the ZIP as stored. Recorded so a downloaded archive can be '
  'checked against what was generated, and quoted in the download audit event.';

-- A package row without its archive is a half-finished generation, and a
-- caller must never be handed one as though it were downloadable. Either all
-- three are present or none are.
alter table public.sas_validation_packages
  drop constraint if exists sas_validation_packages_archive_is_complete;

alter table public.sas_validation_packages
  add constraint sas_validation_packages_archive_is_complete check (
    (archive_storage_path is null and archive_sha256 is null
       and archive_bytes is null)
    or (archive_storage_path is not null and archive_sha256 is not null
       and archive_bytes is not null and archive_bytes > 0)
  );

alter table public.sas_validation_packages
  drop constraint if exists sas_validation_packages_archive_hash_is_a_hash;

alter table public.sas_validation_packages
  add constraint sas_validation_packages_archive_hash_is_a_hash check (
    archive_sha256 is null or archive_sha256 ~ '^[0-9a-f]{64}$'
  );

-- ---------------------------------------------- the immutability trigger ---
--
-- 0032 made packages append-only with a BEFORE UPDATE OR DELETE trigger that
-- raises unconditionally. That is still what we want for every column it was
-- written to protect — but the archive columns are written AFTER the row, in
-- the same generation call, because the archive's storage path is only known
-- once the bytes exist.
--
-- The narrow exception: the three archive columns may be filled in ONCE, from
-- null. Nothing else may change, and a filled archive may not be replaced —
-- which is the property that matters, since replacing it would change what a
-- package contains without changing its id.
create or replace function private.sas_packages_are_immutable()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception
      'sas_validation_packages is append-only. Historical validation evidence '
      'must outlive the code that produced it.';
  end if;

  -- Every column except the three archive ones must be untouched.
  if (to_jsonb(new) - 'archive_storage_path' - 'archive_sha256' - 'archive_bytes')
     is distinct from
     (to_jsonb(old) - 'archive_storage_path' - 'archive_sha256' - 'archive_bytes')
  then
    raise exception
      'sas_validation_packages is append-only. A change to the dataset, the '
      'program, the model or the engine version produces a NEW package id; it '
      'does not modify an existing one.';
  end if;

  -- The archive may be attached once, and never swapped.
  if old.archive_storage_path is not null
     and new.archive_storage_path is distinct from old.archive_storage_path
  then
    raise exception
      'the archive for this package is already stored. Replacing it would '
      'change what the package contains without changing its id.';
  end if;

  return new;
end;
$$;

-- ------------------------------------------------------------- artifacts ---
--
-- IDEMPOTENT UPLOAD.
--
-- The same bytes uploaded twice for the same run is the same evidence, not two
-- pieces of it. Without this, a customer who clicks upload twice — or retries
-- after a timeout that actually succeeded — produces two artifact rows with
-- identical hashes, and a reviewer has to work out whether that means anything.
--
-- Scoped to (run, kind, hash) rather than to the hash alone: the same file
-- legitimately appearing under two different runs is two pieces of evidence,
-- about two different questions.
create unique index if not exists sas_validation_artifacts_unique_upload
  on public.sas_validation_artifacts (run_id, kind, content_sha256);

comment on index public.sas_validation_artifacts_unique_upload is
  'Re-uploading identical bytes for the same run and kind is idempotent: the '
  'existing artifact is returned rather than a duplicate created. Different '
  'bytes for the same run and kind are a new artifact — evidence is never '
  'overwritten.';
