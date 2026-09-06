"""No unauthenticated route may serve a candidate answer.

WHAT THIS FILE EXISTS BECAUSE OF

PR #80 blinded the archive the SAS operator downloads. It did not blind
`GET /api/sas-validation/options`, which takes no `current_user` and returned
every `target.reference` - so the candidate dfs 19.8906 and 22.5403, the name
"ReplicateBE", and the note calling one of them BEST-SUPPORTED were served to
anybody on the internet, unauthenticated. Verified against the deployed
production URL before this fix.

An operator handed a blinded archive need only open the application's own
public API to read both answers and which one we prefer. The blind was
installed on the package and defeated one route away.

So blinding is not a property of the package. It is a property of every
surface the operator can reach, and this file tests the public ones.
"""

from __future__ import annotations

import json

import pytest

from app.sas_validation.package import (
    FORBIDDEN_EXPECTED_VALUES,
    FORBIDDEN_OPERATOR_PHRASES,
)
from app.sas_validation.routes import list_options
from app.sas_validation.targets import TARGETS


@pytest.fixture(scope="module")
def options_payload() -> str:
    """The route function's own output, serialised as the API would send it."""
    return json.dumps(list_options(), default=str)


@pytest.mark.parametrize("forbidden", FORBIDDEN_EXPECTED_VALUES)
def test_the_public_options_route_serves_no_candidate_value(
    options_payload, forbidden
):
    assert forbidden not in options_payload, (
        f"GET /options serves {forbidden!r} to unauthenticated callers."
    )


@pytest.mark.parametrize("phrase", FORBIDDEN_OPERATOR_PHRASES)
def test_the_public_options_route_serves_no_expectation_vocabulary(
    options_payload, phrase
):
    """The same vocabulary the package is held to.

    Reusing the package's list rather than writing a second one: two lists
    would drift, and the one that drifted would be whichever nobody was
    reading when a new candidate arrived.
    """
    assert phrase not in options_payload.lower(), (
        f"GET /options serves {phrase!r} to unauthenticated callers."
    )


def test_the_public_route_still_serves_what_a_regulator_published():
    """Blinding by deletion would be the wrong fix.

    EMA's published estimate and interval are not candidates for the SAS run
    to settle - they are already public in EMA's own Q&A - and the selection
    screen legitimately shows them.
    """
    payload = list_options()
    case = next(
        c
        for c in payload["cases"]
        if c["case_id"] == "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
    )

    quantities = {r["quantity"] for r in case["references"]}
    assert "estimate_percent" in quantities
    assert "ci_lower_percent" in quantities
    assert "ci_upper_percent" in quantities

    for reference in case["references"]:
        assert reference["regulator_confirmed"] is True, reference["quantity"]


def test_the_public_route_says_that_something_is_withheld():
    """Silence would let a reader conclude the candidates do not exist."""
    payload = list_options()
    case = next(
        c
        for c in payload["cases"]
        if c["case_id"] == "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
    )
    withheld = case["unconfirmed_references_withheld"]

    target = TARGETS["FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"]
    assert withheld == len(target.unconfirmed())
    assert withheld > 0, (
        "This target no longer carries any unconfirmed reference, so this "
        "test proves nothing. Check that the candidates were not deleted "
        "instead of filtered."
    )


def test_the_candidates_still_exist_internally():
    """The fix must scope who sees them, not destroy the record.

    If the leak had been closed by deleting the reference values, the
    reviewer would have lost the context the run is judged against - and this
    test would be the only thing to say so.
    """
    target = TARGETS["FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"]
    values = {r.value for r in target.unconfirmed() if r.value is not None}
    assert 19.8906 in values
    assert 22.5403 in values


def test_every_unauthenticated_route_in_this_module_is_accounted_for():
    """A future public route inherits the same obligation.

    Enumerated from the router rather than listed here: a new route added
    without `current_user` shows up as a failure naming itself, which is what
    `/options` would have done had this existed.
    """
    import inspect

    from app.sas_validation.routes import router

    public = []
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        parameters = inspect.signature(endpoint).parameters
        takes_user = any(
            name in ("user", "current_user") for name in parameters
        )
        if not takes_user:
            public.append(route.path)

    assert set(public) == {"/sas-validation/options"}, (
        f"Unauthenticated SAS routes are now {sorted(public)}. Any route "
        "reachable without a session must be covered by the blinding tests "
        "in this file - the candidates leaked through exactly such a route."
    )
