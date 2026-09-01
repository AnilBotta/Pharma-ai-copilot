"""Only an authorized human may record an oracle-closure decision.

WHAT CHANGED SINCE PR #64

PR #64 shut the endpoint because the backend could not answer "does user X hold
global role Y". `private.has_role()` reads `auth.uid()`, which is null under
the service role the API connects with, so it returned false for everyone.

Migration 0034 adds `private.user_has_global_role(p_user_id, p_role_key)` -
the explicit-user twin 0016 established the precedent for. These tests exercise
the layer that asks it, with a fake connection standing in for the database:
what is under test is the AUTHORISATION LOGIC, not asyncpg.
"""

from __future__ import annotations

import pytest

from app.sas_validation.authorization import (
    GRANT_INSTRUCTIONS,
    NON_APPLICATION_ROLES,
    REVIEWER_ROLE_KEYS,
    ActorType,
    NotAHumanReviewer,
    ReviewerAuthorizationService,
    ReviewerIdentity,
    describe_authorization_state,
)


class FakePool:
    """Answers `user_has_global_role` from a dict of granted roles."""

    def __init__(self, grants: dict[str, set[str]]) -> None:
        self.grants = grants
        self.questions: list[tuple[str, str]] = []

    def acquire(self):
        pool = self

        class Connection:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetchval(self, query: str, user_id: str, role_key: str):
                assert "user_has_global_role" in query
                pool.questions.append((user_id, role_key))
                return role_key in pool.grants.get(user_id, set())

        return Connection()


def service(grants: dict[str, set[str]]) -> ReviewerAuthorizationService:
    return ReviewerAuthorizationService(FakePool(grants))


# ------------------------------------------------------ who may review ---


@pytest.mark.asyncio
async def test_an_ordinary_authenticated_user_cannot_review():
    """The default answer is no. Being signed in is not authority."""
    result = await service({}).can_review_sas_validation("user-1")

    assert result.authorized is False
    assert result.matched_roles == ()
    assert "system_administrator" in result.reason
    assert "executive" in result.reason


@pytest.mark.asyncio
async def test_a_system_administrator_may_review():
    result = await service(
        {"admin-1": {"system_administrator"}}
    ).can_review_sas_validation("admin-1")

    assert result.authorized is True
    assert result.matched_roles == ("system_administrator",)
    assert result.primary_role == "system_administrator"


@pytest.mark.asyncio
async def test_an_executive_may_review():
    result = await service({"exec-1": {"executive"}}).can_review_sas_validation(
        "exec-1"
    )
    assert result.authorized is True
    assert result.primary_role == "executive"


@pytest.mark.asyncio
async def test_an_unknown_role_confers_nothing():
    """Holding some other seeded role is not holding a reviewer role."""
    result = await service(
        {"user-1": {"auditor", "gate_committee_member"}}
    ).can_review_sas_validation("user-1")
    assert result.authorized is False


@pytest.mark.asyncio
async def test_only_the_two_reviewer_roles_are_ever_asked_about():
    """No role is invented, and none is quietly added.

    A third key appearing here would mean a parallel notion of seniority that
    nothing else in the product uses.
    """
    pool = FakePool({})
    await ReviewerAuthorizationService(pool).can_review_sas_validation("u")

    asked = {role for _, role in pool.questions}
    assert asked == set(REVIEWER_ROLE_KEYS)
    assert asked == {"system_administrator", "executive"}


@pytest.mark.asyncio
async def test_a_missing_user_id_is_refused_without_asking_the_database():
    pool = FakePool({})
    result = await ReviewerAuthorizationService(pool).can_review_sas_validation("")

    assert result.authorized is False
    assert pool.questions == [], "an empty identity should not be looked up"


# ------------------------------------------ what is not a human reviewer ---


@pytest.mark.parametrize("jwt_role", sorted(NON_APPLICATION_ROLES))
def test_a_transport_level_jwt_role_is_not_an_application_role(jwt_role: str):
    """Supabase issues `authenticated` and `service_role` in the token.

    Treating either as an application role would let every signed-in session -
    and the backend's own database identity - record a governed decision.
    """
    assert jwt_role not in REVIEWER_ROLE_KEYS


@pytest.mark.parametrize(
    "actor", [ActorType.AI_SYSTEM, ActorType.SYSTEM]
)
def test_an_automated_identity_cannot_become_a_human_reviewer(actor):
    with pytest.raises(NotAHumanReviewer, match="cannot be recorded"):
        ReviewerIdentity.for_human(
            user_id="bot-1", role_key="system_administrator", actor_type=actor
        )


def test_a_human_reviewer_needs_an_identity():
    with pytest.raises(NotAHumanReviewer):
        ReviewerIdentity.for_human(user_id="  ", role_key="executive")


def test_a_constructed_reviewer_is_always_human():
    identity = ReviewerIdentity.for_human(
        user_id="human-1", role_key="executive"
    )
    assert identity.actor_type is ActorType.HUMAN


# -------------------------------------------- the grant path is CLI-only ---


def test_nobody_is_granted_a_reviewer_role_automatically():
    """Not the current user, and not on first run.

    A system that made whoever ran it a reviewer would have no authorisation
    model at all.
    """
    state = describe_authorization_state(authorized_reviewers=0)
    assert "No user currently holds a reviewer role" in state
    assert "pdp_admin grant-role" in state


def test_the_grant_instructions_name_the_existing_cli_exactly():
    """A wrong command in a governance document wastes an operator's afternoon."""
    assert "python -m app.pdp_admin grant-role" in GRANT_INSTRUCTIONS
    assert "--email" in GRANT_INSTRUCTIONS
    assert "--role system_administrator" in GRANT_INSTRUCTIONS
    # And how to confirm it worked.
    assert "pdp_admin who" in GRANT_INSTRUCTIONS


def test_the_instructions_explain_why_grants_are_cli_only():
    assert "self-issued" in GRANT_INSTRUCTIONS


def test_an_authorised_state_reports_the_count():
    assert "2 authorised reviewer(s)" in describe_authorization_state(2)


# ------------------------------------------------- the SQL function shape ---


def test_the_role_function_does_not_read_auth_uid():
    """The whole reason it exists.

    `private.has_role()` reads auth.uid(), which is null under the service
    role. A twin that did the same would be a second copy of a broken check.
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/0034_sas_validation_review.sql"
    ).read_text(encoding="utf-8")

    start = migration.index("create or replace function private.user_has_global_role")
    end = migration.index("comment on function private.user_has_global_role")
    body = migration[start:end]

    assert "auth.uid()" not in body
    assert "p_user_id" in body
    assert "set search_path = ''" in body
    assert "security definer" in body
    # Global means project_id is null - the scope 0007's unique index models.
    assert "project_id is null" in body
    # An expired grant confers nothing.
    assert "expires_at" in body
    # No dynamic SQL.
    assert "execute" not in body.lower()


def test_the_role_function_is_not_exposed_to_the_browser():
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/0034_sas_validation_review.sql"
    ).read_text(encoding="utf-8")

    assert "revoke all on function private.user_has_global_role" in migration
    assert (
        "grant execute on function private.user_has_global_role" not in migration
    )
