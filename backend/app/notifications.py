"""Notification delivery.

The engine that decides WHAT to say lives in the database (migration 0021), so
that conditions are recomputed from the record rather than accumulated in a
queue. This module only decides who to tell and puts it in front of them.

WHY DELIVERY IS DELIBERATELY DUMB

A notification is a pointer to state, never the state itself. If mail is down
for a week nothing is lost: the gate still knows it is blocked, the requirement
still knows it is unsatisfied, and the next sweep still finds them. That is why
a failed send marks one delivery row failed and moves on, rather than retrying
in a way that could stall the sweep or double-send.

NO SILENT NO-OP

With no email provider configured, deliveries are recorded as `skipped` with the
reason on the row. The alternative - quietly doing nothing - would let an
operator believe notifications were going out for months. Silence with a stated
reason beats silence.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Somewhere to send a message.

    Kept to one method so swapping Resend for SES, SMTP or a Teams webhook is a
    class rather than a refactor.
    """

    @property
    def name(self) -> str: ...

    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class LoggingNotifier:
    """The default. Records the intent, sends nothing.

    Used when no provider is configured. Every delivery it handles is marked
    `skipped`, not `sent`, so the record never claims a message went out.
    """

    name = "logging"

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("[notification not sent - no provider] to=%s subject=%s", to, subject)


class ResendNotifier:
    """Email via Resend.

    Chosen for a simple HTTP API and no SDK. Any provider with a POST endpoint
    would slot in the same way.
    """

    name = "resend"

    def __init__(
        self, api_key: str, from_email: str, reply_to: str | None = None
    ) -> None:
        self._api_key = api_key
        self._from = from_email
        # These messages come from a no-reply sender, so a reply lands nowhere
        # unless somebody says otherwise. Somebody who hits reply on an overdue
        # requirement is trying to deal with it, and silence is a poor answer.
        self._reply_to = reply_to

    async def send(self, *, to: str, subject: str, body: str) -> None:
        import httpx

        payload: dict[str, Any] = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            if response.status_code >= 400:
                # Body, not just status: a 422 from Resend names the field.
                raise RuntimeError(
                    f"Resend rejected the message ({response.status_code}): "
                    f"{response.text[:300]}"
                )


def build_notifier(settings: Any) -> Notifier:
    """Pick a notifier from configuration, preferring a real one."""
    key = getattr(settings, "resend_api_key", None)
    sender = getattr(settings, "notification_from_email", None)
    if key and sender:
        return ResendNotifier(
            key.get_secret_value(),
            sender,
            reply_to=getattr(settings, "email_reply_to", None),
        )
    return LoggingNotifier()


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


async def dispatch_pending(
    pool: Any, notifier: Notifier, *, limit: int = 200, base_url: str | None = None
) -> dict:
    """Deliver open, unacknowledged events to the people who should hear them.

    Two audiences, unioned:

    * ROLE HOLDERS, resolved through user_roles. At escalation level zero the
      rule's `notify_roles`; above it, `escalate_to_roles`.
    * CONFIGURED ADDRESSES from `notification_recipients`, which hold no role
      and no authority - they are a delivery list maintained from the settings
      page. Added to the role audience rather than replacing it, so the person
      accountable for the work does not stop being told because a setting
      changed somewhere else.

    Deduplication differs between the two and both matter. For a role holder it
    is the `unique (event_id, recipient_user_id, escalation_level)` constraint.
    For an address with no account `recipient_user_id` is null, NULL is never
    equal to NULL in a unique constraint, and 0029 adds a partial unique index
    on the email instead - without which every sweep would re-send.
    """
    sent = failed = skipped = 0

    async with pool.acquire() as conn:
        pending = await conn.fetch(
            """
            with events as (
              select e.id as event_id,
                     e.escalation_level,
                     e.severity,
                     e.title,
                     e.detail,
                     e.project_id,
                     e.subject_type,
                     r.condition,
                     r.notify_roles,
                     r.escalate_to_roles,
                     --: When this event reached the rung it is on now. Used to
                     --: decide whether a newly added recipient should hear
                     --: about it.
                     coalesce(e.last_escalated_at, e.raised_at) as arrived_at,
                     -- 0021 gave events a subject "so the UI can link to it".
                     -- Nothing ever did, and the emails went out with no way to
                     -- act on them: 44 messages naming requirements and
                     -- offering no route to any of them.
                     --
                     -- A requirement's link has to point at its GATE, because
                     -- that is the page a person works on, so the stage is
                     -- resolved here rather than by a second round trip per
                     -- recipient.
                     case
                       when e.subject_type = 'gate_requirement' then (
                         select gr.project_stage_id::text
                           from public.gate_requirements gr
                          where gr.id::text = e.subject_id
                       )
                       when e.subject_type = 'project_stage' then e.subject_id
                     end as stage_id
                from public.notification_events e
                join public.notification_rules r on r.id = e.rule_id
               where e.resolved_at is null
                 and e.acknowledged_at is null
            ),
            audience as (
              select ev.event_id, ev.escalation_level, ev.severity, ev.title,
                     ev.detail, ev.project_id, ev.subject_type, ev.stage_id,
                     p.id    as recipient_user_id,
                     p.email as recipient_email
                from events ev
                join public.user_roles ur
                  on ur.role_id in (
                       select id from public.roles
                        where key = any(
                          case when ev.escalation_level = 0
                               then ev.notify_roles else ev.escalate_to_roles end)
                     )
                 and (ur.project_id is null or ur.project_id = ev.project_id)
                 and (ur.expires_at is null or ur.expires_at > now())
                join public.profiles p on p.id = ur.user_id
               where p.is_active

              union all

              -- Addresses configured on the settings page. An empty
              -- `conditions` array means every condition, which is the common
              -- case and must not require anybody to tick seven boxes to get
              -- the obvious behaviour.
              select ev.event_id, ev.escalation_level, ev.severity, ev.title,
                     ev.detail, ev.project_id, ev.subject_type, ev.stage_id,
                     null::uuid as recipient_user_id,
                     nr.email   as recipient_email
                from events ev
                join public.notification_recipients nr
                  on nr.is_active
                 and nr.wants_immediate
                 and (cardinality(nr.conditions) = 0
                      or ev.condition = any(nr.conditions))
                 -- Only what happened AFTER they were added. Otherwise adding
                 -- an address delivers the entire standing backlog in one go -
                 -- 44 emails at present - which is the flood this design exists
                 -- to avoid, arriving as somebody's first impression of the
                 -- system. `arrived_at` is when the event reached its current
                 -- rung, so an escalation still reaches a recent addition.
                 --
                 -- They are not left ignorant of the backlog: the daily digest
                 -- describes everything currently open, which is precisely the
                 -- job it exists to do.
                 and ev.arrived_at >= nr.created_at
            )
            -- One row per address per event, even when the same person is both
            -- a role holder and on the roster - which is likely, since the
            -- people configuring this are the people already in the system.
            -- `nulls last` keeps the role-based row, so the delivery is
            -- attributed to the account rather than to a bare address.
            select distinct on (a.event_id, lower(a.recipient_email))
                   a.event_id, a.escalation_level, a.severity, a.title,
                   a.detail, a.project_id, a.subject_type, a.stage_id,
                   a.recipient_user_id, a.recipient_email
              from audience a
             where not exists (
               select 1 from public.notification_deliveries d
                where d.event_id = a.event_id
                  and d.escalation_level = a.escalation_level
                  -- `skipped` means nothing left the building, so it must not
                  -- count as delivered. Excluding only real attempts is what
                  -- lets a backlog raised before any email provider existed be
                  -- sent once one does.
                  --
                  -- Without this the constraint that makes re-running safe also
                  -- makes those alerts permanently undeliverable: 44 rows in
                  -- production, every one `skipped`, every one silently
                  -- unsendable forever. A table full of deliveries that never
                  -- happened is exactly the kind of thing that reads as
                  -- coverage.
                  and d.status <> 'skipped'
                  and (
                    (a.recipient_user_id is not null
                     and d.recipient_user_id = a.recipient_user_id)
                    or
                    (a.recipient_user_id is null
                     and d.recipient_user_id is null
                     and lower(d.recipient_email) = lower(a.recipient_email))
                  )
             )
             order by a.event_id, lower(a.recipient_email),
                      a.recipient_user_id nulls last
             limit $1
            """,
            limit,
        )

        for row in pending:
            subject = f"[{row['severity'].upper()}] {row['title']}"
            body = _compose(row, base_url)

            status, error = "sent", None
            if isinstance(notifier, LoggingNotifier):
                # Be explicit rather than pretending. An operator reading this
                # table should see immediately that nothing left the building.
                status = "skipped"
                error = "No email provider configured; nothing was sent."
                skipped += 1
            else:
                try:
                    await notifier.send(
                        to=row["recipient_email"], subject=subject, body=body
                    )
                    sent += 1
                except Exception as exc:
                    # Broad on purpose: one bad address must not stop the rest
                    # of the batch, and the state a notification points at is
                    # safe in the database whether or not the mail arrives.
                    logger.warning(
                        "Notification delivery failed for %s: %s",
                        row["recipient_email"], exc,
                    )
                    status, error = "failed", str(exc)[:500]
                    failed += 1

            # Two conflict targets, because two different indexes protect the
            # two kinds of recipient and a statement may name only one. The
            # `where` clause on each is identical: only a `skipped` row may be
            # overwritten, and only by an attempt that actually happened, so the
            # guarantee that a person is told once per event per rung survives.
            insert_sql = """
                insert into public.notification_deliveries
                  (event_id, recipient_user_id, recipient_email, channel, status,
                   error, escalation_level, sent_at)
                values ($1,$2,$3,'email',$4,$5,$6,
                        case when $4 = 'sent' then now() else null end)
                on conflict {target}
                do update set status     = excluded.status,
                              error      = excluded.error,
                              sent_at    = excluded.sent_at,
                              created_at = now()
                 where public.notification_deliveries.status = 'skipped'
                   and excluded.status <> 'skipped'
            """
            target = (
                "(event_id, recipient_user_id, escalation_level)"
                if row["recipient_user_id"] is not None
                # The partial index from 0029. Named by its predicate rather
                # than by name so Postgres infers it, and so the expression is
                # visible here - a reader who changes one must change the other.
                else (
                    "(event_id, lower(recipient_email), escalation_level) "
                    "where recipient_user_id is null"
                )
            )
            await conn.execute(
                # `target` is one of two literals chosen above, never caller
                # input, so the format call cannot carry anything injectable.
                insert_sql.format(target=target),
                row["event_id"], row["recipient_user_id"], row["recipient_email"],
                status, error, row["escalation_level"],
            )

    return {"sent": sent, "failed": failed, "skipped": skipped,
            "considered": len(pending)}


def _link_for(row: Any, base_url: str | None) -> str | None:
    """Where a person should go to deal with this.

    Without a base URL there is no link. That is deliberate: a relative path in
    an email is not clickable, and a guessed origin would send people somewhere
    that may not exist.
    """
    if not base_url or not row["project_id"]:
        return None

    project = row["project_id"]
    subject = row["subject_type"]

    if subject in ("gate_requirement", "project_stage"):
        stage = row["stage_id"]
        # A requirement whose stage could not be resolved still gets the
        # programme, which beats nothing.
        return (
            f"{base_url}/programmes/{project}/gates/{stage}"
            if stage
            else f"{base_url}/programmes/{project}"
        )
    if subject == "controlled_document_version":
        return f"{base_url}/programmes/{project}/documents"
    if subject == "project_task":
        return f"{base_url}/programmes/{project}/schedule"
    return f"{base_url}/programmes/{project}"


def _compose(row: Any, base_url: str | None = None) -> str:
    lines = [row["title"], ""]
    if row["detail"]:
        lines += [row["detail"], ""]
    if row["escalation_level"] > 0:
        lines += [
            "This has been escalated because it was not acknowledged in time.",
            "",
        ]

    link = _link_for(row, base_url)
    if link:
        lines += [link, ""]

    lines += [
        "This is an automated message from the Pharma R&D Copilot stage-gate "
        "module. It reports the state of the record; it is not a decision and "
        "does not replace one.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The daily digest
# --------------------------------------------------------------------------- #
#
# Immediate mail is for the person who must act. The digest is for everybody
# else: one message a day describing every open gate, so "everyone knows the
# gate status" does not mean "everyone receives forty-four emails".
#
# That distinction is the whole reason this exists. 0021's own header says a
# system that reports everything produces the same outcome as one that reports
# nothing, because people stop reading. A CEO who gets one summary reads it; a
# CEO who gets forty-four filters the sender.


async def digest_due(pool: Any, *, on_date: Any = None) -> list[dict]:
    """Addresses that want a digest and have not had one today.

    The `unique (lower(recipient_email), digest_date)` index in 0029 is what
    makes "once a day" true. This query only avoids doing pointless work; the
    index is what makes a double send impossible.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            select r.email, r.name, r.conditions
              from public.notification_recipients r
             where r.is_active and r.wants_digest
               and not exists (
                 select 1 from public.notification_digests d
                  where lower(d.recipient_email) = lower(r.email)
                    and d.digest_date = coalesce($1::date, current_date)
                    and d.status <> 'failed'
               )
          order by lower(r.email)
            """,
            on_date,
        )
    return [dict(r) for r in rows]


async def gather_digest(pool: Any, *, conditions: list[str] | None = None) -> list[dict]:
    """Every open alert, grouped by programme and gate.

    One query rather than one per recipient: the content is identical for
    everybody, and only the filtering differs.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            select p.name as project_name,
                   e.project_id,
                   r.condition,
                   e.severity,
                   e.title,
                   e.escalation_level,
                   e.raised_at,
                   case
                     when e.subject_type = 'gate_requirement' then (
                       select s.name from public.gate_requirements gr
                         join public.project_stages s on s.id = gr.project_stage_id
                        where gr.id::text = e.subject_id
                     )
                     when e.subject_type = 'project_stage' then (
                       select s.name from public.project_stages s
                        where s.id::text = e.subject_id
                     )
                   end as gate_name
              from public.notification_events e
              join public.notification_rules r on r.id = e.rule_id
              left join public.projects p on p.id = e.project_id
             where e.resolved_at is null
               and e.acknowledged_at is null
               and ($1::text[] is null or cardinality($1::text[]) = 0
                    or r.condition = any($1::text[]))
          order by p.name, gate_name nulls last, e.severity desc, e.raised_at
            """,
            conditions,
        )
    return [dict(r) for r in rows]


def compose_digest(rows: list[dict], *, base_url: str | None = None) -> tuple[str, str]:
    """Subject and body for one digest. No model call; this is a report."""
    if not rows:
        return (
            "Stage gates: nothing outstanding",
            "No gate has an open alert against it today.\n\n"
            "This is an automated summary from the Pharma R&D Copilot stage-gate "
            "module.",
        )

    by_project: dict[str, list[dict]] = {}
    for row in rows:
        by_project.setdefault(row["project_name"] or "Unassigned", []).append(row)

    critical = sum(1 for r in rows if r["severity"] == "critical")
    escalated = sum(1 for r in rows if (r["escalation_level"] or 0) > 0)

    subject = (
        f"Stage gates: {len(rows)} open alert(s) across {len(by_project)} programme(s)"
    )

    lines = [
        f"{len(rows)} open alert(s) across {len(by_project)} programme(s).",
    ]
    if critical:
        lines.append(f"{critical} are critical.")
    if escalated:
        # Naming this matters: an escalated alert is one nobody acknowledged in
        # time, which is a different fact from it merely being open.
        lines.append(f"{escalated} escalated because nobody acknowledged them.")
    lines.append("")

    for project, items in by_project.items():
        lines.append(f"## {project}")
        by_gate: dict[str, list[dict]] = {}
        for item in items:
            by_gate.setdefault(item["gate_name"] or "Not tied to a gate", []).append(item)

        for gate, gate_items in by_gate.items():
            lines.append(f"  {gate} — {len(gate_items)} open")
            # Bounded, so a programme with sixty alerts does not produce an
            # unreadable email. The count above stays truthful either way.
            for item in gate_items[:8]:
                flag = "!" if item["severity"] == "critical" else "-"
                age = _days_since(item["raised_at"])
                lines.append(f"    {flag} {item['title']} ({age})")
            if len(gate_items) > 8:
                lines.append(f"    … and {len(gate_items) - 8} more")

        if base_url and items[0]["project_id"]:
            lines.append(f"  {base_url}/programmes/{items[0]['project_id']}")
        lines.append("")

    lines += [
        "This is an automated summary from the Pharma R&D Copilot stage-gate "
        "module. It reports the state of the record; it is not a decision and "
        "does not replace one.",
    ]
    return subject, "\n".join(lines)


def _days_since(when: Any) -> str:
    """How long this has been open, in the words a reader thinks in.

    "9 days open" is the number that makes somebody act; a timestamp is not.
    """
    if when is None:
        return "age unknown"
    from datetime import UTC, datetime

    if getattr(when, "tzinfo", None) is None:
        return "age unknown"
    days = (datetime.now(UTC) - when).days
    if days <= 0:
        return "today"
    return f"{days} day{'s' if days != 1 else ''} open"


async def send_digests(
    pool: Any, notifier: Notifier, *, base_url: str | None = None
) -> dict:
    """One summary per address per day."""
    due = await digest_due(pool)
    if not due:
        return {"due": 0, "sent": 0, "failed": 0, "skipped": 0}

    # Gathered ONCE, then filtered per recipient. Two reasons: the content is
    # identical for everybody so re-querying is waste, and acquiring a second
    # connection inside a loop that already holds one is how a pool deadlocks
    # under load.
    everything = await gather_digest(pool)

    sent = failed = skipped = 0
    async with pool.acquire() as conn:
        for recipient in due:
            wanted = set(recipient.get("conditions") or [])
            rows = (
                everything
                if not wanted
                else [r for r in everything if r["condition"] in wanted]
            )
            subject, body = compose_digest(rows, base_url=base_url)

            status, error = "sent", None
            if isinstance(notifier, LoggingNotifier):
                status = "skipped"
                error = "No email provider configured; nothing was sent."
                skipped += 1
            else:
                try:
                    await notifier.send(
                        to=recipient["email"], subject=subject, body=body
                    )
                    sent += 1
                except Exception as exc:
                    logger.warning(
                        "Digest failed for %s: %s", recipient["email"], exc
                    )
                    status, error = "failed", str(exc)[:500]
                    failed += 1

            await conn.execute(
                """
                insert into public.notification_digests
                    (recipient_email, digest_date, event_count, status, error, sent_at)
                values ($1, current_date, $2, $3, $4,
                        case when $3 = 'sent' then now() else null end)
                on conflict (lower(recipient_email), digest_date)
                do update set status = excluded.status,
                              error  = excluded.error,
                              sent_at = excluded.sent_at,
                              event_count = excluded.event_count
                 where public.notification_digests.status in ('pending', 'skipped')
                   and excluded.status <> 'skipped'
                """,
                recipient["email"], len(rows), status, error,
            )

    return {"due": len(due), "sent": sent, "failed": failed, "skipped": skipped}


async def sweep_all_projects(pool: Any) -> dict:
    """Recompute conditions for every PDP project, then escalate.

    Detection is a query over current state, so this is idempotent: running it
    every minute raises nothing new when nothing has changed.
    """
    raised = resolved = 0

    async with pool.acquire() as conn:
        projects = await conn.fetch(
            "select id from public.projects where pdp_enabled and archived_at is null"
        )
        for project in projects:
            row = await conn.fetchrow(
                "select * from private.sweep_notifications($1)", project["id"]
            )
            raised += row["raised"]
            resolved += row["resolved"]

        escalated = await conn.fetchval("select private.escalate_notifications()")

    return {
        "projects": len(projects),
        "raised": raised,
        "resolved": resolved,
        "escalated": escalated,
    }
