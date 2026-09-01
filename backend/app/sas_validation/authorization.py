"""Who may accept oracle evidence, and how the backend can find out.

WHY THIS EXISTS AND WHY IT DID NOT BEFORE

PR #64 shut the review endpoint because the backend could not answer one
question: does authenticated application user X hold global role Y?

    private.has_role(role_key, project_id)    reads auth.uid(), which is NULL
                                              under the service role the API
                                              connects with - so it returns
                                              false for every user, always
    private.user_capabilities(user, project)  takes an explicit user, but is
                                              project-scoped by signature and
                                              cannot answer a global question

The available options were to let every signed-in user record a governed
decision, to restate the rule in Python, or to refuse. 0016 had already written
down why the second is wrong - "two copies of an access rule is one copy too
many: they drift, and the drift is a security bug" - so PR #64 refused.

Migration 0034 supplies the missing twin, `private.user_has_global_role`,
following 0016's precedent rather than adding a second mechanism. This module
is the thin layer that asks it.

WHAT AN AUTHORISED REVIEWER IS

A HUMAN holding an approved application role. Not a Supabase JWT claim, not the
service role, not a background worker, and not an AI identity - none of which
is a person, and any of which would otherwise satisfy a naive check.

The distinction is enforced twice: `ReviewerIdentity` refuses to be constructed
for a non-human actor, and the database column refuses a non-human row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

#: Roles that may record an oracle-closure decision, in the vocabulary
#: migration 0007 already seeds. No new role is invented here: `executive`
#: (rank 90) and `system_administrator` (rank 95) are the org-level roles this
#: system has, and adding a third would mean maintaining a parallel notion of
#: seniority that nothing else in the product uses.
REVIEWER_ROLE_KEYS: tuple[str, ...] = ("system_administrator", "executive")

#: JWT roles Supabase issues. Listed so they can be REFUSED explicitly: they
#: are transport-level claims, not application roles, and a check that treated
#: them as such would let every signed-in session record a governed decision.
NON_APPLICATION_ROLES = frozenset({"anon", "authenticated", "service_role"})


class ActorType(StrEnum):
    """Mirrors the `review_actor_type` enum in 0034.

    Stored rather than inferred: "was this approved by a person" must be
    answerable by reading a column, not by reasoning about which code path
    happened to write the row.
    """

    HUMAN = "human"
    AI_SYSTEM = "ai_system"
    SYSTEM = "system"


class NotAHumanReviewer(PermissionError):
    """An automated identity tried to occupy a human reviewer field."""


@dataclass(frozen=True, slots=True)
class ReviewerAuthorization:
    """The answer, with its reason - never a bare boolean.

    A refusal that cannot say why produces support tickets, and an approval
    that cannot say which role granted it cannot be audited.
    """

    authorized: bool
    user_id: str
    matched_roles: tuple[str, ...]
    reason: str

    @property
    def primary_role(self) -> str | None:
        """The role recorded on the decision. Highest-ranked wins by list order."""
        for key in REVIEWER_ROLE_KEYS:
            if key in self.matched_roles:
                return key
        return None


@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    """A human, established server-side.

    Constructed only from an authenticated request context. There is no path
    that builds one from a request body, and `for_human` refuses any actor type
    other than HUMAN - so an AI or worker identity cannot become a reviewer
    even if some future caller passes one in.
    """

    user_id: str
    role_key: str
    actor_type: ActorType = ActorType.HUMAN

    @classmethod
    def for_human(
        cls, *, user_id: str, role_key: str, actor_type: ActorType = ActorType.HUMAN
    ) -> ReviewerIdentity:
        if actor_type is not ActorType.HUMAN:
            raise NotAHumanReviewer(
                f"{actor_type.value} cannot be recorded as a human reviewer. "
                "An oracle-closure decision is a governed judgement and must "
                "be attributable to a person."
            )
        if not user_id or not user_id.strip():
            raise NotAHumanReviewer("a human reviewer needs an identity")
        return cls(user_id=user_id, role_key=role_key)


class ReviewerAuthorizationService:
    """Asks the database the one question, and refuses to guess."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def can_review_sas_validation(
        self, user_id: str
    ) -> ReviewerAuthorization:
        """Is this authenticated user allowed to record an oracle decision?

        `user_id` comes from `AuthenticatedUser.id` and nowhere else. No route
        accepts a reviewer id in a request body, and a test asserts it.
        """
        if not user_id or not user_id.strip():
            return ReviewerAuthorization(
                authorized=False,
                user_id=user_id,
                matched_roles=(),
                reason="no authenticated user",
            )

        matched: list[str] = []
        async with self._pool.acquire() as conn:
            for role_key in REVIEWER_ROLE_KEYS:
                held = await conn.fetchval(
                    "select private.user_has_global_role($1::uuid, $2)",
                    user_id,
                    role_key,
                )
                if held:
                    matched.append(role_key)

        if matched:
            return ReviewerAuthorization(
                authorized=True,
                user_id=user_id,
                matched_roles=tuple(matched),
                reason=f"holds {', '.join(matched)}",
            )

        return ReviewerAuthorization(
            authorized=False,
            user_id=user_id,
            matched_roles=(),
            reason=(
                "recording an oracle-closure decision requires one of: "
                f"{', '.join(REVIEWER_ROLE_KEYS)}. Roles are granted from the "
                "CLI only - see GRANT_INSTRUCTIONS - so that nobody can grant "
                "themselves authority through the interface."
            ),
        )


#: How to grant the first reviewer. Quoted rather than paraphrased, because a
#: wrong command in a governance document wastes an operator's afternoon.
#:
#: Nobody is granted automatically, and emphatically not the current user: a
#: system that made whoever ran it a reviewer would have no authorisation model
#: at all.
GRANT_INSTRUCTIONS = (
    "No user is granted a reviewer role automatically. To authorise the first "
    "human reviewer, run the existing admin CLI against the deployment:\n"
    "\n"
    "    python -m app.pdp_admin grant-role "
    "--email person@example.com --role system_administrator\n"
    "\n"
    "Grants are CLI-only by design, so authority cannot be self-issued through "
    "the application. Confirm the grant with:\n"
    "\n"
    "    python -m app.pdp_admin who --email person@example.com"
)


def describe_authorization_state(authorized_reviewers: int) -> str:
    """What to tell an operator who finds the controls unavailable.

    A greyed-out button with no explanation reads as a broken product;
    `requirement-labels.tsx` records that this actually happened during
    testing. Naming the roles required, and how to obtain one, is the
    difference between a dead end and a next step.
    """
    if authorized_reviewers:
        return f"{authorized_reviewers} authorised reviewer(s) configured."
    return (
        "No user currently holds a reviewer role, so no oracle-closure "
        "decision can be recorded yet.\n\n" + GRANT_INSTRUCTIONS
    )


__all__ = [
    "GRANT_INSTRUCTIONS",
    "NON_APPLICATION_ROLES",
    "REVIEWER_ROLE_KEYS",
    "ActorType",
    "NotAHumanReviewer",
    "ReviewerAuthorization",
    "ReviewerAuthorizationService",
    "ReviewerIdentity",
    "describe_authorization_state",
]
