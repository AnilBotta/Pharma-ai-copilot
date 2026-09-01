"""Recording an oracle closure is a governed decision, not a signed-in action.

WHY THE ENDPOINT IS CLOSED RATHER THAN ROLE-GATED

Migration 0007 seeds a real role vocabulary, including `system_administrator`
(rank 95) and `executive` (rank 90). What does not exist is any way for THIS
BACKEND to check them:

    private.has_role(role_key, project_id)   reads auth.uid(), which is NULL
                                             when the backend connects as the
                                             service role
    private.user_capabilities(user, project) is project-scoped by signature and
                                             cannot answer "is this user an
                                             executive" globally

There is no `user_has_global_role(user_id, role_key)` twin, and
`settings_module/routes.py` records that nobody currently holds either
org-level role.

That left three options: let every signed-in user record an oracle closure,
invent a parallel permission system, or refuse. The first is not acceptable for
a governed validation decision; the second would be a second answer to "who may
decide", with nothing to say which one wins.

So the HTTP door is shut and says why. The domain service is complete and
tested - only the boundary is closed.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import AuthenticatedUser
from app.sas_validation import routes


def user(role: str = "authenticated") -> AuthenticatedUser:
    return AuthenticatedUser(id="user-1", email="someone@example.com", role=role)


def test_an_ordinary_authenticated_user_cannot_record_an_oracle_closure():
    """The default answer is no, and it is enforced at the boundary."""
    with pytest.raises(HTTPException) as error:
        routes.require_reviewer(user())

    assert error.value.status_code == 501
    assert error.value.detail["code"] == "REVIEWER_AUTHORIZATION_NOT_CONFIGURED"


def test_the_refusal_is_501_and_not_403():
    """403 would tell an operator they lack a permission.

    The truth is that the permission cannot yet be checked by anyone, which is
    a different fact and the one worth logging.
    """
    with pytest.raises(HTTPException) as error:
        routes.require_reviewer(user())
    assert error.value.status_code == 501
    assert error.value.status_code != 403


def test_the_refusal_names_the_roles_that_would_govern_it():
    """It uses the vocabulary that already exists, not a new one."""
    with pytest.raises(HTTPException) as error:
        routes.require_reviewer(user())

    required = error.value.detail["required_roles"]
    assert required == ["system_administrator", "executive"]

    # And these are roles migration 0007 actually seeds - not invented here.
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[3]
        / "supabase/migrations/0007_pdp_foundation.sql"
    ).read_text(encoding="utf-8")
    for role in required:
        assert f"'{role}'" in migration


def test_the_refusal_says_what_would_enable_it():
    """A refusal with no path forward is a dead end someone has to re-derive."""
    with pytest.raises(HTTPException) as error:
        routes.require_reviewer(user())

    detail = error.value.detail
    assert "user_has_global_role" in detail["what_would_enable_it"]
    assert "auth.uid()" in detail["message"]


def test_no_role_claim_from_the_request_can_open_the_door():
    """A JWT role claim is not an application role.

    Supabase issues `authenticated` and `service_role` in the token; the
    application's roles live in `user_roles`. Accepting the former as the
    latter would let anyone with a session record a validation decision.
    """
    for claimed in ("authenticated", "service_role", "executive",
                    "system_administrator", "admin"):
        with pytest.raises(HTTPException) as error:
            routes.require_reviewer(user(role=claimed))
        assert error.value.status_code == 501


def test_the_flag_is_the_single_thing_that_opens_it(monkeypatch):
    """One switch, flipped only when a real check exists behind it.

    Patching it here proves the gate is the flag rather than something
    incidental - and that the identity still comes from the server context.
    """
    monkeypatch.setattr(routes, "REVIEWER_AUTHORIZATION_CONFIGURED", True)
    reviewer = routes.require_reviewer(user())
    assert reviewer.id == "user-1"


def test_the_review_request_body_cannot_name_the_reviewer():
    """Identity comes from the authenticated context, never from the payload.

    A body field naming the reviewer would let a caller attribute a governed
    validation decision to somebody else - the one thing an audit trail exists
    to prevent.
    """
    fields = set(routes.ReviewRequest.model_fields)
    assert fields == {"decision", "notes"}
    for forbidden in ("reviewer", "reviewer_user_id", "user_id", "actor", "tenant_id"):
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
        "observations", "dataset", "sas", "sas_code", "program",
        "model", "expected_df", "denominator_df", "package_hash", "manifest",
    ):
        assert forbidden not in fields
