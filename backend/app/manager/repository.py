"""Conversation storage for the Manager Agent.

A NOTE ON JSONB

The pool registers a codec whose ENCODER is `json.dumps` (see `app.db`), so a
Python object handed to a jsonb parameter is serialised for you. Passing
`json.dumps(x)` instead means the string gets serialised again, and the column
ends up holding a JSON string that contains JSON. It reads back as `str`, and
the failure surfaces a long way away - as a response-validation error on an
endpoint that looks correct.

So: pass objects to jsonb parameters here, never pre-serialised text.
"""

from __future__ import annotations

import json
from typing import Any

from app.pdp.repository import NotFound

#: Anything larger is stored as a marker rather than truncated mid-string,
#: because half a JSON document is not a JSON document.
_MAX_JSON_BYTES = 200_000


def _jsonb(value: Any) -> Any:
    """Prepare a value for a jsonb column, bounded in size."""
    if value is None:
        return None
    encoded = json.dumps(value, default=str)
    if len(encoded) > _MAX_JSON_BYTES:
        return {
            "truncated": True,
            "reason": f"Value exceeded {_MAX_JSON_BYTES} bytes and was not stored.",
            "preview": encoded[:2000],
        }
    # Round-trips through the encoder so that anything `default=str` had to
    # coerce - a UUID, a date - is stored as the string the codec would have
    # produced, rather than failing inside asyncpg.
    return json.loads(encoded)


class ManagerRepository:
    """Chat threads and their messages.

    Every method takes ``user_id`` and filters on it. The RLS policy in 0023
    says the same thing, but this repository runs on a pooled service
    connection where that policy is not what stops a mistake - the where clause
    is.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ------------------------------------------------------- conversations ---

    async def create_conversation(self, user_id: str, title: str | None = None) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into public.manager_conversations (user_id, title)
                values ($1, coalesce($2, 'New conversation'))
                returning *
                """,
                user_id,
                title,
            )
        return dict(row)

    async def list_conversations(self, user_id: str, limit: int = 40) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select c.*,
                       (select count(*) from public.manager_messages m
                         where m.conversation_id = c.id and m.role <> 'tool')
                         as message_count
                  from public.manager_conversations c
                 where c.user_id = $1 and c.archived_at is null
              order by c.updated_at desc
                 limit $2
                """,
                user_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.manager_conversations "
                "where id = $1 and user_id = $2 and archived_at is null",
                conversation_id,
                user_id,
            )
        if row is None:
            raise NotFound(f"Conversation {conversation_id} not found.")
        return dict(row)

    async def archive_conversation(self, user_id: str, conversation_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "update public.manager_conversations set archived_at = now() "
                "where id = $1 and user_id = $2 and archived_at is null",
                conversation_id,
                user_id,
            )
        if result.endswith(" 0"):
            raise NotFound(f"Conversation {conversation_id} not found.")

    async def set_title(self, user_id: str, conversation_id: str, title: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "update public.manager_conversations set title = $3 "
                "where id = $1 and user_id = $2",
                conversation_id,
                user_id,
                title[:120],
            )

    # ------------------------------------------------------------ messages ---

    async def list_messages(
        self, user_id: str, conversation_id: str, *, include_tools: bool = True
    ) -> list[dict]:
        await self.get_conversation(user_id, conversation_id)
        query = """
            select * from public.manager_messages
             where conversation_id = $1
        """
        if not include_tools:
            query += " and role <> 'tool'"
        query += " order by id"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, conversation_id)
        return [dict(r) for r in rows]

    async def add_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_arguments: dict | None = None,
        tool_result: Any = None,
        truncated: bool = False,
        truncated_reason: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: Any = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                insert into public.manager_messages (
                    conversation_id, role, content, tool_name, tool_arguments,
                    tool_result, truncated, truncated_reason,
                    input_tokens, output_tokens, estimated_cost_usd
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                returning id
                """,
                conversation_id,
                role,
                content,
                tool_name,
                _jsonb(tool_arguments),
                _jsonb(tool_result),
                truncated,
                truncated_reason,
                input_tokens,
                output_tokens,
                estimated_cost_usd,
            )

    # ----------------------------------------------------------- proposals ---

    async def create_proposal(
        self,
        *,
        conversation_id: str | None,
        requested_by: str,
        project_id: str | None,
        action_type: str,
        params: dict,
        rationale: str,
        premise: dict,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into public.agent_proposals (
                    conversation_id, requested_by, project_id,
                    action_type, params, rationale, premise
                ) values ($1,$2,$3,$4,$5,$6,$7)
                returning *
                """,
                conversation_id,
                requested_by,
                project_id,
                action_type,
                _jsonb(params),
                rationale,
                _jsonb(premise),
            )
        return dict(row)

    async def list_proposals(
        self, user_id: str, *, status: str = "pending", limit: int = 25
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select p.* from public.agent_proposals p
                 where p.requested_by = $1
                   and ($2 = 'all' or p.status = $2)
              order by p.created_at desc
                 limit $3
                """,
                user_id,
                status,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_proposal(self, user_id: str, proposal_id: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from public.agent_proposals "
                "where id = $1 and requested_by = $2",
                proposal_id,
                user_id,
            )
        if row is None:
            raise NotFound(f"Proposal {proposal_id} not found.")
        return dict(row)

    async def settle_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        confirmed_by: str | None = None,
        rejected_reason: str | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Record the outcome.

        The `decided once` trigger in 0024 refuses a second transition, so a
        double-click executes the underlying act once and reports the second
        attempt honestly rather than silently doing it twice.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update public.agent_proposals
                   set status          = $2,
                       confirmed_by    = $3,
                       confirmed_at    = case when $2 = 'confirmed' then now() end,
                       rejected_reason = $4,
                       result          = $5,
                       error           = $6
                 where id = $1
                """,
                proposal_id,
                status,
                confirmed_by,
                rejected_reason,
                _jsonb(result),
                error,
            )

    async def expire_stale_proposals(self, user_id: str) -> int:
        """Mark anything past its window expired, before it can be confirmed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "update public.agent_proposals set status = 'expired' "
                "where requested_by = $1 and status = 'pending' and expires_at < now()",
                user_id,
            )
        return int(result.rsplit(" ", 1)[-1] or 0)

    async def transcript_for_model(
        self, conversation_id: str, *, max_turns: int = 24
    ) -> list[dict]:
        """The conversation as Responses API input items.

        Tool rows are NOT replayed. They are kept for the record, but feeding
        every historical tool result back into the context would grow the turn
        cost without bound down a long thread - and the agent can call a tool
        again if it needs current data, which after twenty turns it probably
        should anyway.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select role, content from public.manager_messages
                 where conversation_id = $1 and role in ('user', 'assistant')
                       and content is not null
              order by id desc
                 limit $2
                """,
                conversation_id,
                max_turns,
            )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
