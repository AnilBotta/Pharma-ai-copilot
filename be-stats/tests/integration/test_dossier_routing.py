"""The routing matrix must describe what the router actually does.

A documented rule that nobody runs is the most reliable way to be confidently
wrong. So every row is driven through `resolve_be_spec` and checked against
what came back - including the rows whose correct behaviour is to raise.
"""

from __future__ import annotations

import itertools

import pytest

from be_stats.dossier.refusals import REFUSALS
from be_stats.dossier.routing import (
    ROUTING_MATRIX,
    UNSUPPORTED_COMBINATION,
    route_for,
    routes_for,
)
from be_stats.spec import (
    DrugClass,
    Endpoint,
    Jurisdiction,
    Method,
    NotApplicable,
    SpecificationRequired,
    resolve_be_spec,
)


@pytest.mark.parametrize("route", ROUTING_MATRIX, ids=lambda r: r.route_id)
def test_every_route_matches_resolve_be_spec(route):
    """The row is checked against the real router, endpoint by endpoint."""
    for endpoint in route.endpoints:
        if route.raises:
            expected = {
                "SpecificationRequired": SpecificationRequired,
                "NotApplicable": NotApplicable,
            }[route.raises]
            with pytest.raises(expected):
                resolve_be_spec(
                    jurisdiction=route.jurisdiction,
                    drug_class=route.drug_class,
                    endpoint=endpoint,
                )
            continue

        spec = resolve_be_spec(
            jurisdiction=route.jurisdiction,
            drug_class=route.drug_class,
            endpoint=endpoint,
        )
        assert spec.method is route.method, (
            f"{route.route_id} on {endpoint}: the matrix says "
            f"{route.method} and the router selected {spec.method}."
        )
        assert spec.jurisdiction is route.jurisdiction
        assert spec.drug_class is route.drug_class


def test_the_matrix_covers_every_combination_the_router_accepts():
    """No combination routes somewhere the matrix does not describe."""
    for jurisdiction, drug_class, endpoint in itertools.product(
        Jurisdiction, DrugClass, Endpoint
    ):
        route = route_for(jurisdiction, drug_class, endpoint)
        assert route is not UNSUPPORTED_COMBINATION, (
            f"{jurisdiction}/{drug_class}/{endpoint} has no row, but the "
            "router handles it. An undocumented route is one nobody reviews."
        )


def test_the_seven_required_routes_are_present():
    """The routes the release brief enumerates, by name.

    FDA and EMA ordinary ABE, FDA HVD, FDA NTI, EMA ABEL, EMA NTI, and the
    unsupported case. Named individually so that deleting one is a visible
    failure rather than a smaller table.
    """
    ids = {route.route_id for route in ROUTING_MATRIX}
    assert {
        "FDA_STANDARD",
        "FDA_HVD",
        "FDA_NTI",
        "EMA_STANDARD",
        "EMA_HVD_ABEL",
        "EMA_NTI_AUC",
        "EMA_NTI_CMAX",
    } <= ids
    assert UNSUPPORTED_COMBINATION.route_id == "UNSUPPORTED"
    assert UNSUPPORTED_COMBINATION.method is None


def test_endpoint_specific_rows_win_over_general_ones():
    """EMA NTI needs three rows and the AUC row must not shadow the others."""
    auc = route_for(Jurisdiction.EMA, DrugClass.NARROW_THERAPEUTIC_INDEX, Endpoint.AUC)
    cmax = route_for(
        Jurisdiction.EMA, DrugClass.NARROW_THERAPEUTIC_INDEX, Endpoint.CMAX
    )
    assert auc.route_id == "EMA_NTI_AUC"
    assert cmax.route_id == "EMA_NTI_CMAX"
    assert auc.method is Method.EMA_NTI_NARROW_ABE
    assert cmax.method is None


def test_rows_for_one_jurisdiction_and_class_partition_the_endpoints():
    """Two rows must never both claim the same endpoint at the same priority."""
    for jurisdiction in Jurisdiction:
        for drug_class in DrugClass:
            rows = [
                r
                for r in ROUTING_MATRIX
                if r.jurisdiction is jurisdiction and r.drug_class is drug_class
            ]
            for endpoint in Endpoint:
                claiming = [r for r in rows if endpoint in r.endpoints]
                if len(claiming) > 1:
                    sizes = [len(r.endpoints) for r in claiming]
                    assert len(set(sizes)) == len(sizes), (
                        f"{jurisdiction}/{drug_class}/{endpoint} is claimed by "
                        f"{[r.route_id for r in claiming]} at the same "
                        "specificity, so which one wins is arbitrary."
                    )


def test_no_route_silently_falls_back_to_the_conventional_interval():
    """The failure this matrix exists to prevent, asserted directly.

    A non-standard drug class must never come back carrying STANDARD_ABE with
    80.00-125.00%. It either selects the regulator's own method or it refuses.
    """
    for route in ROUTING_MATRIX:
        if route.drug_class is DrugClass.STANDARD:
            continue
        assert route.method is not Method.STANDARD_ABE, (
            f"{route.route_id} routes a {route.drug_class} drug to ordinary "
            "average BE. That answers a different regulatory question with an "
            "identical-looking verdict."
        )


def test_an_unsupported_route_refuses_rather_than_defaulting():
    """`UNSUPPORTED` raises, and says so, and names nothing to fall back to."""
    assert UNSUPPORTED_COMBINATION.raises == "NotApplicable"
    assert UNSUPPORTED_COMBINATION.method is None
    assert "80.00" in UNSUPPORTED_COMBINATION.refusal_behaviour, (
        "The refusal text must say what it does NOT do; a reader who only "
        "learns that it raises will assume something reasonable happened."
    )


def test_every_route_refusal_code_is_a_declared_refusal():
    for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION):
        for code in route.refusal_conditions:
            assert code in REFUSALS, f"{route.route_id} cites unknown {code}"


def test_every_route_states_a_decision_rule_and_a_refusal_behaviour():
    for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION):
        assert route.input_classification.strip(), route.route_id
        assert route.decision_rule.strip(), route.route_id
        assert route.refusal_behaviour.strip(), route.route_id


def test_routes_for_returns_only_that_jurisdiction():
    for jurisdiction in Jurisdiction:
        for route in routes_for(jurisdiction):
            assert route.jurisdiction is jurisdiction
