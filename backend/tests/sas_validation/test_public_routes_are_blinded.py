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


def test_no_reference_value_of_any_status_reaches_the_public_payload():
    """THE STRUCTURAL INVARIANT, and the primary test in this file.

    Not a list of numbers. Every `ReferenceValue.value` on every target is
    checked against the serialised public payload, whatever its evidence
    status - REGULATOR_PUBLISHED included.

    WHY REGULATOR_PUBLISHED IS NOT AN EXEMPTION

    The first fix filtered to `regulator_published()` and still served
    estimate 102.26 and the interval 97.05-107.76: expected numerical outputs
    for the dataset the blinded operator is about to analyse. Provenance
    status and audience disclosure are different questions, and one was used
    as a proxy for the other.

    A literal list would also have to be extended by hand the first time a
    new published example is attached to a target. This cannot go stale: the
    values are read from the targets themselves.
    """
    payload = json.dumps(list_options(), default=str)

    checked = 0
    for target in TARGETS.values():
        for reference in target.references:
            if reference.value is None:
                continue
            checked += 1
            for rendering in (
                str(reference.value),
                f"{reference.value:g}",
            ):
                assert rendering not in payload, (
                    f"{target.case_id}: the public payload contains "
                    f"{rendering} ({reference.quantity}, "
                    f"{reference.status.value}). Evidence provenance is not "
                    "audience disclosure - a number a regulator printed is "
                    "still an expected result to the operator who is about "
                    "to produce it."
                )

    assert checked >= 5, (
        f"only {checked} reference values were checked; this guard would be "
        "close to vacuous. Have the targets' references been deleted rather "
        "than withheld?"
    )


@pytest.mark.parametrize(
    "value", ["102.26", "97.05", "107.76", "19.8906", "22.5403"]
)
def test_the_specific_values_known_to_have_leaked_are_absent(
    options_payload, value
):
    """The literal check, kept as a companion to the structural one.

    Redundant while the structural test holds, and cheap. If someone ever
    weakens the invariant above, these five say plainly which numbers went
    back out.
    """
    assert value not in options_payload


def test_the_public_payload_carries_no_reference_field_at_all():
    """Withheld structurally, rather than emptied.

    An empty `references: []` would invite a later change to "just include
    the published ones" - which is exactly what happened once. The field is
    not part of the public contract.
    """
    for case in list_options()["cases"]:
        assert "references" not in case, case["case_id"]
        assert "reviewer_question" not in case, (
            f"{case['case_id']}: reviewer_question is reviewer context and "
            "its wording referred to reference values this payload no "
            "longer carries."
        )


def test_the_public_payload_carries_the_selection_metadata_it_needs():
    """Blinding must not break case selection."""
    case = next(
        c
        for c in list_options()["cases"]
        if c["case_id"] == "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
    )
    for field in (
        "case_id",
        "title",
        "regulatory_method",
        "design",
        "dataset_source",
        "purpose",
    ):
        assert case[field], field


def test_the_public_route_says_that_something_is_withheld():
    """Counts, not values. Silence would suggest there is nothing to withhold."""
    case = next(
        c
        for c in list_options()["cases"]
        if c["case_id"] == "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"
    )
    target = TARGETS["FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"]

    assert case["unconfirmed_references_withheld"] == len(target.unconfirmed())
    assert case["published_references_withheld"] == len(
        target.regulator_published()
    )
    assert case["unconfirmed_references_withheld"] > 0
    assert case["published_references_withheld"] > 0


def test_both_kinds_of_reference_still_exist_internally():
    """The fix must scope who sees them, not destroy the record.

    Both kinds. The candidates are the question the SAS run settles, and the
    regulator-published figures are the context a reviewer judges it against;
    losing either would turn a disclosure fix into evidence destruction.
    """
    target = TARGETS["FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"]

    candidates = {r.value for r in target.unconfirmed() if r.value is not None}
    assert 19.8906 in candidates
    assert 22.5403 in candidates

    published = {
        r.value for r in target.regulator_published() if r.value is not None
    }
    assert 102.26 in published
    assert 97.05 in published
    assert 107.76 in published


def test_regulator_published_is_not_used_as_an_audience_filter():
    """The architectural mistake, guarded structurally.

    `regulator_published()` answers "may this support a regulatory claim".
    It does not answer "may the blinded operator see this", and the first fix
    to this route used it for the second question.

    Asserted on the AST rather than on behaviour: the behavioural tests above
    would also pass if the route filtered by status and happened to have
    nothing published attached. This says the route does not consult the
    status at all.
    """
    import ast
    import inspect
    import textwrap

    from app.sas_validation import routes

    tree = ast.parse(textwrap.dedent(inspect.getsource(routes.list_options)))

    # `target.references` must not be touched at all: the payload is a
    # whitelist of named fields, not a filtered copy of the target.
    attributes = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert not any(n.attr == "references" for n in attributes), (
        "list_options touches `target.references`. The public payload is a "
        "whitelist of non-numeric fields, not a filtered copy."
    )

    # The two reference accessors may appear ONLY inside `len(...)`. A count
    # discloses no result; anything else with them renders one.
    #
    # NOT a check for `.value` anywhere - `mode.value` on the integration-mode
    # enum is unrelated and legitimate, and matching it would be the blunt
    # search this repository keeps relearning to avoid.
    counted = {
        id(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and node.args
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in ("regulator_published", "unconfirmed"):
            assert id(node) in counted, (
                f"`{node.func.attr}()` is called outside len() in "
                "list_options. Evidence provenance is not audience "
                "disclosure: filtering by status is how 102.26, 97.05 and "
                "107.76 reached an unauthenticated route."
            )


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
