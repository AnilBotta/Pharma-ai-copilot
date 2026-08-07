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

    def __init__(self, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email

    async def send(self, *, to: str, subject: str, body: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from,
                    "to": [to],
                    "subject": subject,
                    "text": body,
                },
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
        return ResendNotifier(key.get_secret_value(), sender)
    return LoggingNotifier()


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #


async def dispatch_pending(pool: Any, notifier: Notifier, *, limit: int = 200) -> dict:
    """Deliver open, unacknowledged events to the people their rule names.

    Recipients come from the rule's role lists, resolved through user_roles,
    plus the owner of the thing the event is about. At escalation level zero the
    audience is `notify_roles`; above it, `escalate_to_roles`.

    The `unique (event_id, recipient_user_id, escalation_level)` constraint on
    deliveries is what makes this safe to run every minute: a person is told
    once per event per rung, and a re-run cannot re-send.
    """
    sent = failed = skipped = 0

    async with pool.acquire() as conn:
        pending = await conn.fetch(
            """
            with audience as (
              select e.id as event_id,
                     e.escalation_level,
                     e.severity,
                     e.title,
                     e.detail,
                     e.project_id,
                     p.id   as recipient_user_id,
                     p.email as recipient_email
                from public.notification_events e
                join public.notification_rules r on r.id = e.rule_id
                join public.user_roles ur
                  on ur.role_id in (
                       select id from public.roles
                        where key = any(
                          case when e.escalation_level = 0
                               then r.notify_roles else r.escalate_to_roles end)
                     )
                 and (ur.project_id is null or ur.project_id = e.project_id)
                 and (ur.expires_at is null or ur.expires_at > now())
                join public.profiles p on p.id = ur.user_id
               where e.resolved_at is null
                 and e.acknowledged_at is null
                 and p.is_active
            )
            select distinct a.*
              from audience a
             where not exists (
               select 1 from public.notification_deliveries d
                where d.event_id = a.event_id
                  and d.recipient_user_id = a.recipient_user_id
                  and d.escalation_level = a.escalation_level
             )
             limit $1
            """,
            limit,
        )

        for row in pending:
            subject = f"[{row['severity'].upper()}] {row['title']}"
            body = _compose(row)

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

            await conn.execute(
                """
                insert into public.notification_deliveries
                  (event_id, recipient_user_id, recipient_email, channel, status,
                   error, escalation_level, sent_at)
                values ($1,$2,$3,'email',$4,$5,$6,
                        case when $4 = 'sent' then now() else null end)
                on conflict (event_id, recipient_user_id, escalation_level)
                do nothing
                """,
                row["event_id"], row["recipient_user_id"], row["recipient_email"],
                status, error, row["escalation_level"],
            )

    return {"sent": sent, "failed": failed, "skipped": skipped,
            "considered": len(pending)}


def _compose(row: Any) -> str:
    lines = [row["title"], ""]
    if row["detail"]:
        lines += [row["detail"], ""]
    if row["escalation_level"] > 0:
        lines += [
            "This has been escalated because it was not acknowledged in time.",
            "",
        ]
    lines += [
        "This is an automated message from the Pharma R&D Copilot stage-gate "
        "module. It reports the state of the record; it is not a decision and "
        "does not replace one.",
    ]
    return "\n".join(lines)


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
