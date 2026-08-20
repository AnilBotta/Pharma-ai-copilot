"""The notification recipient roster.

Every mutation is audited through the same `private.record_audit_event` the
stage-gate module uses. That is not ceremony: redirecting where alerts go is a
control, and "who stopped the alerts reaching Priya" is a question somebody will
eventually need answered. The audit trail answers it whether or not the page is
ever restricted to a role.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.repository import NotFound

logger = logging.getLogger(__name__)

#: Conditions a recipient may subscribe to. Kept in step with the CHECK
#: constraint on `notification_rules.condition`; an unknown value is refused
#: rather than silently subscribing somebody to nothing.
KNOWN_CONDITIONS = (
    "requirement_overdue",
    "requirement_awaiting_approval",
    "document_expiring",
    "document_expired_in_use",
    "task_overdue",
    "critical_task_slipping",
    "gate_ready_for_review",
    "gate_unattended",
)


class RecipientRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def _audit(
        self,
        conn,
        *,
        actor: str,
        action: str,
        entity_id: str,
        previous: dict | None = None,
        new: dict | None = None,
    ) -> None:
        await conn.fetchval(
            """
            select private.record_audit_event(
                p_action        => $1,
                p_entity_type   => 'notification_recipient',
                p_entity_id     => $2,
                p_actor_user_id => $3,
                p_previous      => $4,
                p_new           => $5,
                p_actor_agent   => nullif(current_setting('app.acting_agent', true), ''),
                p_source        => 'api'
            )
            """,
            action, str(entity_id), actor,
            json.dumps(previous) if previous is not None else None,
            json.dumps(new) if new is not None else None,
        )

    async def list_alert_types(self) -> list[dict]:
        """The conditions a recipient can subscribe to.

        Read from `notification_rules` rather than hardcoded anywhere, so a
        deactivated rule stops being offered and a new one appears without a
        code change on either side.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "select condition, name, description, severity, is_active "
                "from public.notification_rules order by severity desc, name"
            )
        return [dict(r) for r in rows]

    async def list_all(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select r.*,
                       (select count(*) from public.notification_deliveries d
                         where lower(d.recipient_email) = lower(r.email)
                           and d.status = 'sent') as sent_count,
                       (select max(d.sent_at) from public.notification_deliveries d
                         where lower(d.recipient_email) = lower(r.email)
                           and d.status = 'sent') as last_sent_at
                  from public.notification_recipients r
              order by r.is_active desc, lower(r.email)
                """
            )
        return [dict(r) for r in rows]

    async def create(
        self,
        actor: str,
        *,
        email: str,
        name: str | None,
        conditions: list[str],
        wants_immediate: bool,
        wants_digest: bool,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                "select id, is_active from public.notification_recipients "
                "where lower(email) = lower($1)",
                email,
            )
            if existing is not None:
                # Re-adding an address that was deactivated is what somebody
                # means when they type it in again. Refusing with "already
                # exists" for a row they cannot see in the active list would be
                # obstructive and slightly untrue.
                row = await conn.fetchrow(
                    """
                    update public.notification_recipients
                       set is_active = true, name = coalesce($2, name),
                           conditions = $3, wants_immediate = $4, wants_digest = $5
                     where id = $1
                    returning *
                    """,
                    existing["id"], name, conditions, wants_immediate, wants_digest,
                )
                await self._audit(
                    conn, actor=actor, action="notification_recipient.reactivated",
                    entity_id=str(existing["id"]),
                    previous={"is_active": existing["is_active"]},
                    new={"email": email, "conditions": conditions},
                )
                return dict(row)

            row = await conn.fetchrow(
                """
                insert into public.notification_recipients
                    (email, name, conditions, wants_immediate, wants_digest, created_by)
                values ($1,$2,$3,$4,$5,$6)
                returning *
                """,
                email, name, conditions, wants_immediate, wants_digest, actor,
            )
            await self._audit(
                conn, actor=actor, action="notification_recipient.added",
                entity_id=str(row["id"]),
                new={
                    "email": email,
                    "conditions": conditions,
                    "wants_immediate": wants_immediate,
                    "wants_digest": wants_digest,
                },
            )
        return dict(row)

    async def update(self, actor: str, recipient_id: str, changes: dict) -> dict:
        if not changes:
            return await self.get(recipient_id)

        allowed = {
            "name", "conditions", "wants_immediate", "wants_digest", "is_active",
        }
        fields = {k: v for k, v in changes.items() if k in allowed}
        if not fields:
            return await self.get(recipient_id)

        assignments = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
        async with self._pool.acquire() as conn, conn.transaction():
            before = await conn.fetchrow(
                "select * from public.notification_recipients where id = $1",
                recipient_id,
            )
            if before is None:
                raise NotFound(f"Recipient {recipient_id} not found.")

            row = await conn.fetchrow(
                f"update public.notification_recipients set {assignments} "  # noqa: S608
                "where id = $1 returning *",
                recipient_id, *fields.values(),
            )
            await self._audit(
                conn, actor=actor,
                action=(
                    "notification_recipient.deactivated"
                    if fields.get("is_active") is False
                    else "notification_recipient.updated"
                ),
                entity_id=str(recipient_id),
                previous={k: _plain(before[k]) for k in fields},
                new={k: _plain(v) for k, v in fields.items()},
            )
        return dict(row)

    async def get(self, recipient_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.notification_recipients where id = $1",
                recipient_id,
            )
        if row is None:
            raise NotFound(f"Recipient {recipient_id} not found.")
        return dict(row)

    async def delete(self, actor: str, recipient_id: str) -> None:
        """Deactivate rather than remove.

        A deleted row would orphan the delivery history that names it, and
        "this address used to receive gate alerts" is exactly the kind of thing
        an auditor asks about after the fact.
        """
        await self.update(actor, recipient_id, {"is_active": False})


def _plain(value: Any) -> Any:
    """Values as JSON can carry them, for the audit payload."""
    if isinstance(value, list):
        return list(value)
    return value


__all__ = ["KNOWN_CONDITIONS", "RecipientRepository"]
