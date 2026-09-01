"""Recording an oracle closure is a governed decision, not a signed-in action.

WHY THIS FILE CHANGED IN PR #66

PR #64 shut this endpoint entirely, and said why: migration 0007 seeds a real
role vocabulary, but nothing let THIS BACKEND check it.

    private.has_role(role_key, project_id)   reads auth.uid(), which is NULL
                                             when the backend connects as the
                                             service role
    private.user_capabilities(user, project) is project-scoped by signature and
                                             cannot answer "is this user an
                                             executive" globally

That left three options: let every signed-in user record an oracle closure,
invent a parallel permission system, or refuse. PR #64 refused.

Migration 0034 removes the reason for the refusal. `private.user_has_global_role
(p_user_id, p_role_key)` - the explicit-user twin migration 0016 established the
precedent for - answers the question without auth.uid(), so the check is now a
real question with a real answer.

WHAT DID NOT CHANGE

The default answer is still no. Being signed in is still not authority. A role
claim in the JWT is still not an application role. The reviewer's identity still
comes from the authenticated server context and can never come from the request
body. What changed is only that a user who genuinely holds `system_administrator`
or `executive` can now get through - and that the refusal is now 403, because it
is about the caller rather than the deployment.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import AuthenticatedUser
from app.sas_validation import routes
from app.sas_validation.authorization import ReviewerAuthorizationService


def user(role: str = "authenticated") -> AuthenticatedUser:
    return AuthenticatedUser(id="user-1", email="someone@example.com", role=role)


class FakePool:
    """Answers `user_has_global_role` from a dict of granted roles."""

    def __init__(self, grants: dict[str, set[str]]) -> None:
        self.grants = grants

    def acquire(self):
        pool = self

        class Connection:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetchval(self, query: str, user_id: str, role_key: str):
                assert "user_has_global_role" in query
                return role_key in pool.grants.get(user_id, set())

        return Connection()


def authorization(grants: dict[str, set[str]] | None = None):
    return ReviewerAuthorizationService(FakePool(grants or {}))


# ------------------------------------------------- the door is still shut ---


@pytest.mark.asyncio
async def test_an_ordinary_authenticated_user_cannot_record_an_oracle_closure():
    """The default answer is no, and it is enforced at the boundary."""
    with pytest.raises(HTTPException) as error:
        await routes.require_reviewer(user(), authorization())

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "NOT_AN_AUTHORIZED_REVIEWER"


@pytest.mark.asyncio
async def test_the_refusal_is_now_403_because_the_check_exists():
    """PR #64 returned 501: nobody could check the permission, so telling an
    operator they lacked it would have been the wrong fact.

    Migration 0034 makes the permission checkable, so a refusal now means what
    403 means - this caller genuinely does not hold the role.
    """
    with pytest.raises(HTTPException) as error:
        await routes.require_reviewer(user(), authorization())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_the_refusal_names_the_roles_that_would_govern_it():
    """It uses the vocabulary that already exists, not a new one."""
    with pytest.raises(HTTPException) as error:
        await routes.require_reviewer(user(), authorization())

    required = error.value.detail["required_roles"]
    assert required == ["system_administrator", "executive"]


def test_those_roles_are_ones_migration_0007_actually_seeds():
    """Not invented here. A reviewer role the product does not otherwise know
    about would be a parallel permission system with nothing to reconcile it."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/0007_pdp_foundation.sql"
    ).read_text(encoding="utf-8")

    for role in ("system_administrator", "executive"):
        assert f"'{role}'" in migration


@pytest.mark.asyncio
async def test_the_refusal_says_how_to_grant_the_role():
    """A refusal with no path forward is a dead end someone has to re-derive."""
    with pytest.raises(HTTPException) as error:
        await routes.require_reviewer(user(), authorization())

    detail = error.value.detail
    assert "python -m app.pdp_admin grant-role" in detail["how_to_grant"]
    # And the message says what was actually wrong with THIS caller.
    assert "system_administrator" in detail["message"]


@pytest.mark.asyncio
async def test_no_role_claim_from_the_request_can_open_the_door():
    """A JWT role claim is not an application role.

    Supabase issues `authenticated` and `service_role` in the token; the
    application's roles live in `user_roles`. Accepting the former as the
    latter would let anyone with a session record a validation decision.

    Note the grants dict is EMPTY throughout: whatever the token says, the
    database is asked and the database says no.
    """
    for claimed in (
        "authenticated",
        "service_role",
        "executive",
        "system_administrator",
        "admin",
    ):
        with pytest.raises(HTTPException) as error:
            await routes.require_reviewer(user(role=claimed), authorization())
        assert error.value.status_code == 403


# --------------------------------------------------- and it does open now ---


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", ["system_administrator", "executive"])
async def test_a_user_holding_a_reviewer_role_is_admitted(granted: str):
    """The point of PR #66. A real grant, checked against the database, admits.

    And the identity still comes from the server context: the returned reviewer
    is `user-1` because that is who authenticated, not because anything in a
    request said so.
    """
    reviewer = await routes.require_reviewer(
        user(), authorization({"user-1": {granted}})
    )

    assert reviewer.user_id == "user-1"
    assert reviewer.role_key == granted
    assert reviewer.actor_type.value == "human"


@pytest.mark.asyncio
async def test_a_grant_to_someone_else_does_not_admit_this_caller():
    """The lookup uses the authenticated id, not "is anyone an admin"."""
    with pytest.raises(HTTPException):
        await routes.require_reviewer(
            user(), authorization({"someone-else": {"executive"}})
        )


# ------------------------------------------------ the body names nobody ---


def test_the_review_request_body_cannot_name_the_reviewer():
    """Identity comes from the authenticated context, never from the payload.

    A body field naming the reviewer would let a caller attribute a governed
    validation decision to somebody else - the one thing an audit trail exists
    to prevent.

    `acknowledged` is a checkbox a person ticks, not an identity: it says what
    the reviewer accepts, not who they are.
    """
    fields = set(routes.ReviewRequest.model_fields)
    assert fields == {"decision", "notes", "acknowledged"}
    for forbidden in (
        "reviewer",
        "reviewer_user_id",
        "user_id",
        "actor",
        "actor_type",
        "role",
        "role_key",
        "tenant_id",
    ):
        assert forbidden not in fields


def test_no_route_accepts_a_client_supplied_tenant():
    """Choosing your own tenant is choosing whose data to read.

    Every request model is checked rather than a named list, so a model added
    later is covered without anyone remembering to add it here.
    """
    import inspect

    from pydantic import BaseModel

    models = [
        value
        for value in vars(routes).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value is not BaseModel
    ]
    assert models, "no request models found - has this test gone stale?"

    for model in models:
        assert "tenant_id" not in model.model_fields, model.__name__

    source = inspect.getsource(routes)
    assert "tenant_id=resolve_tenant(" in source
    assert "tenant_id=request." not in source


def test_the_package_endpoint_accepts_a_case_id_and_nothing_else():
    """No dataset, no SAS, no expected answer, no package hash.

    The server loads the approved data for a predefined case itself. A browser
    that could submit observations could submit a modified version of the
    regulatory dataset under a case id claiming to be EMA Data set II, and the
    comparison against EMA's published interval would become meaningless.
    """
    fields = set(routes.GeneratePackageRequest.model_fields)
    assert fields == {"validation_case_id"}

    for forbidden in (
        "observations",
        "dataset",
        "sas",
        "sas_code",
        "program",
        "model",
        "expected_df",
        "denominator_df",
        "package_hash",
        "manifest",
    ):
        assert forbidden not in fields
