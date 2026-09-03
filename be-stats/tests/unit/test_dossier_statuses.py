"""Implemented is not validated, and the type system now says so.

These tests exist because the conflation is easy, invisible and expensive. A
product that reads one field and prints "Available" has not made a mistake
anybody can see in a diff.
"""

from __future__ import annotations

import pytest

from be_stats.dossier.statuses import (
    SUBMISSION_READY,
    EvidenceTier,
    ImplementationStatus,
    implementation_status_of,
    is_submission_ready,
)
from be_stats.provenance import ValidationStatus


def test_every_validation_status_maps_to_an_implementation_status():
    """Total, so adding a status is a decision rather than a default."""
    for status in ValidationStatus:
        assert isinstance(implementation_status_of(status), ImplementationStatus)


def test_the_implementation_axis_has_exactly_two_values():
    """Three would rebuild the conflation inside the module against it.

    A third value would be `IMPLEMENTED_UNVALIDATED`, which is a PAIR of
    answers wearing one label. Admitting it here means `implementation is
    IMPLEMENTED` stops being answerable without reading the other column,
    which is the whole failure.
    """
    assert set(ImplementationStatus) == {
        ImplementationStatus.NOT_IMPLEMENTED,
        ImplementationStatus.IMPLEMENTED,
    }


def test_only_not_implemented_maps_to_not_implemented():
    for status in ValidationStatus:
        expected = (
            ImplementationStatus.NOT_IMPLEMENTED
            if status is ValidationStatus.NOT_IMPLEMENTED
            else ImplementationStatus.IMPLEMENTED
        )
        assert implementation_status_of(status) is expected


def test_implemented_does_not_imply_validated():
    """The central claim, asserted rather than assumed.

    Four distinct validation statuses map to IMPLEMENTED. So knowing something
    is implemented tells you nothing about whether it may be relied on, and any
    code that treats the two as one is wrong for three of the four.
    """
    implemented = [
        status
        for status in ValidationStatus
        if implementation_status_of(status) is ImplementationStatus.IMPLEMENTED
    ]
    assert len(implemented) == 4
    not_submission_ready = [s for s in implemented if not is_submission_ready(s)]
    assert len(not_submission_ready) == 3, (
        "Three implemented statuses do not license a filing. If this changes, "
        "the product's status presentation has to change with it."
    )


def test_only_validated_licenses_a_filing():
    assert SUBMISSION_READY == frozenset({ValidationStatus.VALIDATED})
    for status in ValidationStatus:
        assert is_submission_ready(status) is (status is ValidationStatus.VALIDATED)


def test_no_inverse_mapping_exists():
    """`implementation_status_of` has no counterpart, and cannot have one.

    Asserted as a property of the module rather than as a comment: an inverse
    would have to pick one of four validation statuses from `IMPLEMENTED`, and
    whichever it picked would be wrong three times in four.
    """
    import be_stats.dossier.statuses as module

    assert not hasattr(module, "validation_status_of")
    assert not hasattr(module, "validation_status_for")


@pytest.mark.parametrize(
    "tier",
    [
        EvidenceTier.TIER_1A,
        EvidenceTier.TIER_1B,
        EvidenceTier.TIER_2,
        EvidenceTier.TIER_3,
        EvidenceTier.TIER_4,
        EvidenceTier.NONE,
    ],
)
def test_the_evidence_tiers_are_the_declared_six(tier):
    assert tier in set(EvidenceTier)
    assert len(set(EvidenceTier)) == 6
