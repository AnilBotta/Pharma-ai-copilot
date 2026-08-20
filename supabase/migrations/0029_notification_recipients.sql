-- 0029 — Who gets told, decided from a settings page rather than a CLI.
--
-- Recipients are resolved today through `user_roles`: to be emailed you must
-- hold a role, and to hold a role somebody must run
-- `python -m app.pdp_admin grant-role` against the database. Nobody holds
-- `department_head`, which is where `requirement_overdue` escalates, so 44
-- alerts climbed a rung last night and reached nobody at all.
--
-- A RECIPIENT IS AN ADDRESS, NOT A PERSON WITH POWERS
--
-- This is deliberately NOT implemented by creating users and granting them
-- roles. `public.roles` carries `can_approve` and `can_gate`, and `user_roles`
-- is what the API and the readiness engine consult when deciding whether
-- somebody may approve a requirement or decide a gate. A design where typing an
-- email address into a settings page created a role holder would hand out
-- approval authority from a configuration screen, in a module whose entire
-- purpose is that such authority is deliberate and auditable.
--
-- So this table has no relationship to authority whatsoever. It says where mail
-- goes. Nothing reads it when deciding what anyone may do.
--
-- It ADDS to the role-based audience rather than replacing it. Somebody who
-- stops being notified because a setting changed elsewhere is exactly the
-- person accountable for the work, and they should not fall off quietly.

create table public.notification_recipients (
  id    uuid primary key default gen_random_uuid(),
  email text not null check (email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  name  text,

  --: Deactivated rather than deleted, so the audit trail keeps pointing at a
  --: row and a delivery record still resolves to a name.
  is_active boolean not null default true,

  --: Which conditions this address wants. EMPTY MEANS ALL - the common case,
  --: and the one that must not require anybody to enumerate seven values to
  --: get the obvious behaviour.
  conditions text[] not null default '{}',

  --: Immediate mail as each alert is raised.
  wants_immediate boolean not null default true,
  --: One summary a day covering every open gate.
  wants_digest    boolean not null default true,

  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- One row per address. Case-insensitive, because Anil@x.com and anil@x.com are
-- one mailbox and two rows would mean two copies of every alert.
create unique index notification_recipients_email_uniq
  on public.notification_recipients (lower(email));

create index notification_recipients_active_idx
  on public.notification_recipients (is_active) where is_active;

create trigger notification_recipients_set_updated_at
  before update on public.notification_recipients
  for each row execute function private.set_updated_at();

comment on table public.notification_recipients is
  'Addresses that receive stage-gate alerts. Purely a delivery list: holds no '
  'role, grants no authority, and is never consulted when deciding what anyone '
  'may approve or decide. Adds to the role-based audience rather than '
  'replacing it.';

comment on column public.notification_recipients.conditions is
  'Notification rule conditions this address wants. Empty means all of them.';

-- ------------------------------------------------ THE CONSTRAINT THAT MATTERS ---
--
-- `notification_deliveries` guarantees a person is told once per event per rung:
--
--     unique (event_id, recipient_user_id, escalation_level)
--
-- and that guarantee is what makes the sweep safe to run repeatedly. It does
-- not hold for the recipients this migration adds. `recipient_user_id` is null
-- for an address with no account, and in a Postgres unique constraint NULL is
-- never equal to NULL - so every row inserted for an email-only recipient is
-- distinct from every other, no conflict is ever detected, and nothing stops a
-- second insert.
--
-- The sweep runs every five minutes since 0028. Without the index below, each
-- pass would send every configured address another copy of every open alert:
-- 44 emails, then 88, then 132, for ever.
--
-- Same shape as the `skipped`-row defect in 0021 - a constraint that appears to
-- guarantee something it does not, where the gap is only visible if you think
-- about which rows it actually covers.

create unique index notification_deliveries_email_uniq
  on public.notification_deliveries (event_id, lower(recipient_email), escalation_level)
  where recipient_user_id is null;

comment on index public.notification_deliveries_email_uniq is
  'The equivalent of the (event_id, recipient_user_id, escalation_level) '
  'constraint for recipients that have no account. NULL <> NULL in a unique '
  'constraint, so without this an email-only recipient has no deduplication at '
  'all and every sweep re-sends. See 0029.';

-- ------------------------------------------------------------------ digests ---
--
-- One summary per address per day. The unique index is what makes that a fact
-- rather than an intention: the sender may run as often as it likes and the
-- second attempt for a date cannot insert.

create table public.notification_digests (
  id uuid primary key default gen_random_uuid(),

  recipient_email text not null,
  digest_date     date not null,

  --: What the digest covered, so a reader of this table can tell an empty day
  --: from a day nothing was sent.
  event_count integer not null default 0,

  status text not null default 'pending'
    check (status in ('pending', 'sent', 'failed', 'skipped')),
  error  text,

  sent_at    timestamptz,
  created_at timestamptz not null default now()
);

create unique index notification_digests_uniq
  on public.notification_digests (lower(recipient_email), digest_date);

create index notification_digests_pending_idx
  on public.notification_digests (status, digest_date) where status = 'pending';

comment on table public.notification_digests is
  'One row per address per day. Exists so "one digest a day" is enforced by a '
  'unique index rather than by the sender remembering.';

-- ---------------------------------------------------------------------- RLS ---
-- Readable by signed-in users so the settings page can show the list. Writes go
-- through the backend under the service role, matching evidence and citations
-- in 0005: a compromised browser token must not be able to redirect where
-- alerts go.

alter table public.notification_recipients enable row level security;
alter table public.notification_digests    enable row level security;

create policy notification_recipients_read on public.notification_recipients
  for select to authenticated using (true);

create policy notification_digests_read on public.notification_digests
  for select to authenticated using (true);
