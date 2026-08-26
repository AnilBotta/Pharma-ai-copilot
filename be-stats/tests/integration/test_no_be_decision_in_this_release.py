"""This release measures. It does not decide. Asserted, not promised.

WHY A TEST AND NOT A CONVENTION

The replicate data layer makes the regulatory decision easy. sWR is right
there, the verified threshold is one import away, and adding
`bioequivalent: bool` to the result would take a minute and look like
progress. It would also mean a bioequivalence verdict shipped from a module
whose estimator has never been checked against a regulator-published dataset.

The separation is the deliverable, so it is enforced the way anything else
load-bearing is: by a test that fails when someone reaches for the shortcut.

TWO THINGS ARE CHECKED

That no public result type carries a verdict-shaped field, and that no module
in this release imports the switching rule at all. The second is the stronger
one - a module that cannot see the threshold cannot apply it.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from be_stats import diagnostics, reference_variance, replicate

#: Names that would mean a verdict had entered this release. From the release
#: brief verbatim, plus the tokens they decompose into so a near-miss like
#: `is_pass` or `overall_be_result` is caught as well.
FORBIDDEN_NAMES = frozenset(
    {
        "pass",
        "fail",
        "bioequivalent",
        "be_result",
        "rsabe_pass",
        "overall_result",
        "accepted",
        "rejected",
    }
)

FORBIDDEN_TOKENS = frozenset(
    {"pass", "fail", "bioequivalent", "accepted", "rejected", "rsabe"}
)

MODULES = (replicate, reference_variance, diagnostics)

#: `estimable` is a bool and is deliberately allowed. It answers "does this
#: quantity exist for these data", which is a statement about estimation, not
#: about the product. Recorded here so the exemption is a decision rather than
#: an oversight.
PERMITTED_BOOLEANS = frozenset({"estimable", "has_reference_pair", "has_test"})


def public_classes(module):
    return [
        obj
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and inspect.isclass(obj)
        and obj.__module__ == module.__name__
    ]


def member_names(cls) -> set[str]:
    """Field names, annotations, properties and methods of one class."""
    names: set[str] = set()
    if dataclasses.is_dataclass(cls):
        names |= {f.name for f in dataclasses.fields(cls)}
    names |= set(getattr(cls, "__annotations__", {}))
    names |= {n for n in vars(cls) if not n.startswith("__")}
    return names


def test_the_modules_under_test_actually_exist():
    """Guards the guard: a typo'd import list would make everything below vacuous."""
    assert MODULES
    for module in MODULES:
        assert public_classes(module), f"{module.__name__} exposes no public class"


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_no_public_type_carries_a_verdict_shaped_field(module):
    offenders: list[str] = []
    for cls in public_classes(module):
        for name in member_names(cls):
            if name in PERMITTED_BOOLEANS:
                continue
            lowered = name.lower()
            if lowered in FORBIDDEN_NAMES:
                offenders.append(f"{cls.__name__}.{name}")
                continue
            if set(lowered.split("_")) & FORBIDDEN_TOKENS:
                offenders.append(f"{cls.__name__}.{name}")
    assert not offenders, (
        "This release must not expose a bioequivalence verdict. Offending "
        "members: " + ", ".join(sorted(offenders))
    )


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_no_module_in_this_release_can_see_the_switching_rule(module):
    """The stronger check: it cannot apply what it does not import.

    Walks the AST rather than searching the text, because the module docstrings
    legitimately DISCUSS 0.294 and where the decision lives - and prose
    explaining a boundary is documentation doing its job. That distinction was
    learned the hard way in Phase 1, when a text-searching guard failed on its
    own explanatory comment.
    """
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "be_stats.spec":
            imported |= {alias.name for alias in node.names}
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}

    forbidden_imports = {
        "fda_hvd_method_for",
        "fda_hvd_theta",
        "FDA_HVD_CONSTANTS",
        "FDA_NTI_CONSTANTS",
        "be_stats.spec",
    }
    assert not (imported & forbidden_imports), (
        f"{module.__name__} imports {sorted(imported & forbidden_imports)}. "
        "The estimation layer must not be able to reach the regulatory "
        "switching rule; applying it is a separate release."
    )

    numeric = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, float)
        and abs(node.value - 0.294) < 1e-12
    ]
    assert not numeric, (
        f"{module.__name__} contains 0.294 as a numeric literal at line(s) "
        f"{numeric}. The threshold is a regulatory value in spec.py; a copy "
        "here would be an uncited duplicate AND a decision this release must "
        "not make."
    )


def test_the_result_reports_swr_without_reporting_a_method():
    """End to end: a real estimate, and nothing that selects a procedure."""
    from be_stats.reference_variance import estimate_reference_variance
    from be_stats.replicate import ReplicateDataset, ReplicateObservation, parse_sequence

    observations = []
    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(4):
            for period, value in enumerate(
                [100.0 + 3 * k, 108.0 - 2 * k, 96.0 + k], start=1
            ):
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}",
                        sequence,
                        period,
                        sequence.expected_treatment(period),
                        "AUC",
                        value,
                    )
                )

    result = estimate_reference_variance(ReplicateDataset.build(observations))
    assert result.estimable
    assert result.swr > 0.0

    exposed = {f.name for f in dataclasses.fields(result)}
    assert "method" not in exposed
    assert not exposed & FORBIDDEN_NAMES

    # And the summary tells the reader where the decision is NOT.
    assert "NOT COMPUTED IN THIS MODULE" in result.summary()


def test_the_decision_lives_outside_the_estimation_layer():
    """The separation survived RSABE being implemented.

    When this file was written, no module in the package decided anything, so
    the guard could not tell "the estimation layer is separate" from "nothing
    decides yet". FDA HVD RSABE is implemented now - in `hvd.py`, which is
    allowed to import the switching rule and does.

    The estimation layer still is not, and that is what the tests above check.
    This one pins the other half: the decision exists, and it exists somewhere
    else.
    """
    from be_stats import VALIDATION, Method, ValidationStatus
    from be_stats import hvd

    assert VALIDATION[Method.FDA_HVD_RSABE] is (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    assert hvd.__name__ not in {m.__name__ for m in MODULES}
    assert hasattr(hvd, "assess_endpoint")

    # Still not implemented, and not reachable by configuring this one.
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.NOT_IMPLEMENTED
    assert VALIDATION[Method.EMA_HVD_ABEL] is ValidationStatus.NOT_IMPLEMENTED
    for status in VALIDATION.values():
        assert status is not ValidationStatus.VALIDATED


def test_the_new_capabilities_are_tracked_apart_from_the_methods():
    """Estimating a quantity and deciding with it are different claims."""
    from be_stats import CAPABILITY_VALIDATION, Capability, Method, ValidationStatus

    assert (
        CAPABILITY_VALIDATION[Capability.FDA_HVD_REPLICATE_DATA_VALIDATION]
        is ValidationStatus.IMPLEMENTED
    )
    assert (
        CAPABILITY_VALIDATION[Capability.FDA_HVD_REFERENCE_VARIANCE]
        is ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    # A capability is not a method, and must never be routable as one.
    assert not set(Capability) & set(Method)
