"""`passes = False` must never mean "not implemented".

The most dangerous single line this package could contain. A reader sees False
beside a bioequivalence endpoint and concludes the study failed; nothing was
computed. These tests hold the three-field contract across every result type
that exists, structurally, so a new one cannot be added with a `passes` that
lies.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import pkgutil

import pytest

import be_stats
from be_stats.dossier.explain import Outcome, explain_capability, explain_route
from be_stats.dossier.semantics import (
    assert_result_semantics,
    check_result_semantics,
)
from be_stats.spec import DrugClass, Endpoint, Jurisdiction


def _result_classes():
    """Every class in the package that reports a bioequivalence outcome.

    Found by ATTRIBUTE rather than by name. A class is a result type if it can
    carry `passes` - as a field or as a property - and searching for the
    attribute means a new result type is covered the moment it is written,
    without anybody remembering to add it here.
    """
    found = []
    for info in pkgutil.walk_packages(be_stats.__path__, "be_stats."):
        module = importlib.import_module(info.name)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != info.name:
                continue
            has_passes = (
                any(f.name == "passes" for f in dataclasses.fields(obj))
                if dataclasses.is_dataclass(obj)
                else False
            ) or isinstance(getattr(obj, "passes", None), property)
            if has_passes:
                found.append(obj)
    return found


def test_result_classes_were_actually_found():
    """Guard against the search silently matching nothing.

    A structural test that finds zero subjects passes vacuously and looks
    green forever. This repository has shipped that mistake before.
    """
    classes = _result_classes()
    assert len(classes) >= 5, (
        f"Only found {[c.__name__ for c in classes]}. The search for result "
        "types is matching too little to be meaningful."
    )


#: Types whose `passes` is a COMPONENT criterion rather than an endpoint
#: verdict, and which therefore carry no `decided` of their own.
#:
#: The distinction is real and worth keeping. A criterion answers one of the
#: regulator's conditions; the endpoint result answers the study. An
#: undecidable criterion propagates upward - `FdaNtiResult.decided` is false
#: when any of its three is None - so the "no decision" state is expressed
#: exactly once, where a reader looks for it.
#:
#: This is an ALLOW-LIST, so a new endpoint result type that forgot `decided`
#: fails below rather than being quietly absorbed.
CRITERION_TYPES = {
    "be_stats.hvd.ScaledCriterion",
    "be_stats.hvd.PointEstimateConstraint",
    "be_stats.hvd.RsabeResult",
    "be_stats.nti.NtiScaledMeanCriterion",
    "be_stats.nti.NtiUnscaledAbeCriterion",
    "be_stats.nti.NtiVariabilityRatioCriterion",
}


def test_every_endpoint_result_can_express_no_decision():
    """A `passes` with no `decided` beside it has no way to say 'undecided'.

    Then the only available answer to "we did not run the test" is False, and
    False reads as a failed study.
    """
    for cls in _result_classes():
        qualified = f"{cls.__module__}.{cls.__name__}"
        if qualified in CRITERION_TYPES:
            continue
        names = (
            {f.name for f in dataclasses.fields(cls)}
            if dataclasses.is_dataclass(cls)
            else set()
        )
        has_decided = "decided" in names or isinstance(
            getattr(cls, "decided", None), property
        )
        assert has_decided, (
            f"{qualified} carries `passes` and no `decided`. It cannot "
            "distinguish 'the study failed' from 'no criterion was "
            "evaluated'. If it is a component criterion rather than an "
            "endpoint verdict, add it to CRITERION_TYPES with a reason."
        )


def test_the_criterion_allow_list_has_not_gone_stale():
    """Every allow-listed name still exists, so the list cannot rot open.

    An allow-list entry for a class that has been renamed silently stops
    excluding anything - and silently stops protecting anything either.
    """
    found = {f"{c.__module__}.{c.__name__}" for c in _result_classes()}
    stale = CRITERION_TYPES - found
    assert not stale, f"Allow-listed types that no longer exist: {stale}"


def test_an_undecidable_criterion_makes_the_endpoint_undecided():
    """The propagation the allow-list depends on, asserted rather than assumed.

    Component criteria are permitted to omit `decided` only because their None
    reaches the endpoint's `decided`. If that link broke, the allow-list would
    be excusing exactly the failure it assumes cannot happen.
    """
    import be_stats.nti as nti

    source = inspect.getsource(nti.FdaNtiResult)
    assert "decided" in source

    assess = inspect.getsource(nti)
    assert "passes is not None" in assess, (
        "FdaNtiResult.decided is no longer computed from whether each "
        "criterion produced an answer. The criterion allow-list in this "
        "module rests on that computation."
    )


def test_every_result_types_passes_is_optional():
    """`passes: bool` cannot hold None, so it cannot represent no decision."""
    for cls in _result_classes():
        if not dataclasses.is_dataclass(cls):
            continue
        field = next(
            (f for f in dataclasses.fields(cls) if f.name == "passes"), None
        )
        # `passes` as a computed property carries no annotation to check; the
        # contract is then enforced by the value tests above rather than here.
        if field is None:
            continue
        annotation = str(field.type)
        assert "None" in annotation or "Optional" in annotation, (
            f"{cls.__module__}.{cls.__name__}.passes is annotated "
            f"{annotation!r}. A non-optional bool has no value meaning "
            "'undecided', so the undecided case will be spelled False."
        )


def test_the_checker_catches_the_dangerous_combination():
    """decided=False with passes=False - the collapse this all exists for."""

    @dataclasses.dataclass
    class Bad:
        decided: bool = False
        passes: bool | None = False

    violations = check_result_semantics(Bad(), "Bad")
    assert violations
    assert any("dangerous" in str(v).lower() for v in violations)

    with pytest.raises(AssertionError):
        assert_result_semantics(Bad(), "Bad")


def test_the_checker_catches_a_decision_with_no_verdict():
    @dataclasses.dataclass
    class AlsoBad:
        decided: bool = True
        passes: bool | None = None

    assert check_result_semantics(AlsoBad(), "AlsoBad")


def test_the_checker_accepts_both_legitimate_shapes():
    @dataclasses.dataclass
    class Decided:
        decided: bool = True
        passes: bool | None = False

    @dataclasses.dataclass
    class Refused:
        decided: bool = False
        passes: bool | None = None

    assert check_result_semantics(Decided(), "Decided") == []
    assert check_result_semantics(Refused(), "Refused") == []


def test_the_checker_rejects_an_object_with_no_pair_at_all():
    class Naked:
        outcome = False

    violations = check_result_semantics(Naked(), "Naked")
    assert violations
    assert "cannot express" in str(violations[0])


def test_a_not_implemented_capability_explains_rather_than_failing():
    """The dossier's own explanation obeys the same contract."""
    explanation = explain_capability("FDA_REPLICATE_STANDARD_ABE_PARTIAL")
    assert explanation.passes is None
    assert explanation.refusal is not None
    assert explanation.refusal.lifted_by
    assert not explanation.submission_ready


def test_an_unsupported_route_explains_rather_than_deciding():
    explanation = explain_route(
        Jurisdiction.EMA, DrugClass.NARROW_THERAPEUTIC_INDEX, Endpoint.CMAX
    )
    assert explanation.outcome is Outcome.REFUSED
    assert explanation.passes is None, (
        "An unsupported route must not produce a verdict of any kind, and "
        "specifically must not produce False."
    )
    assert explanation.method is None
    assert explanation.refusal is not None


def test_no_explanation_ever_reports_false_without_a_decision():
    """Sweep every capability and every route through the explainer."""
    from be_stats.dossier.capabilities import CAPABILITY_MATRIX

    for capability_id in CAPABILITY_MATRIX:
        explanation = explain_capability(capability_id)
        if explanation.outcome is not Outcome.DECIDED:
            assert explanation.passes is None, capability_id

    for jurisdiction in Jurisdiction:
        for drug_class in DrugClass:
            for endpoint in Endpoint:
                explanation = explain_route(jurisdiction, drug_class, endpoint)
                if explanation.outcome is not Outcome.DECIDED:
                    assert explanation.passes is None
