"""Every regulatory number has provenance, and normative is not derived.

The second property has already been violated once in this package's history:
an earlier release derived FDA's switching threshold as sqrt(ln(1 + 0.30^2))
instead of using the stated 0.294. The numbers differ in the fourth decimal and
real studies fall between them. These tests are what stops that returning.
"""

from __future__ import annotations

import math

import pytest

from be_stats.dossier.constants import (
    CONSTANT_INDEX,
    ConstantKind,
    constant,
    constants_of_kind,
    provenance_coverage,
)
from be_stats.provenance import VerificationStatus
from be_stats.spec import (
    EMA_HVD_CONSTANTS,
    FDA_HVD_CONSTANTS,
    FDA_NTI_CONSTANTS,
    fda_hvd_theta,
    fda_nti_theta,
)


def test_every_regulatory_constant_has_provenance():
    """Walk the spec tables; every value must be indexed.

    Compares by (value, citation) rather than by name, because the index and
    the spec tables key their entries differently and a name-based check would
    pass by matching nothing.
    """
    indexed = {
        (record.value, record.citation) for record in CONSTANT_INDEX.values()
    }
    for table_name, table in (
        ("FDA_HVD_CONSTANTS", FDA_HVD_CONSTANTS),
        ("EMA_HVD_CONSTANTS", EMA_HVD_CONSTANTS),
        ("FDA_NTI_CONSTANTS", FDA_NTI_CONSTANTS),
    ):
        for key, value in table.items():
            assert (value.value, value.citation) in indexed, (
                f"{table_name}[{key!r}] = {value.value} is not in the "
                "provenance index, so a review asking 'why is this number "
                "here' would not find it."
            )


def test_every_indexed_constant_names_a_document():
    for record in CONSTANT_INDEX.values():
        assert record.citation.authority, record.constant_id
        assert record.document, record.constant_id
        assert record.role.strip(), (
            f"{record.constant_id} says what it is and not what it does."
        )


def test_normative_constants_are_pinned_to_a_document_version():
    """An unpinned normative citation is the failure `provenance` opens with."""
    for record in constants_of_kind(ConstantKind.NORMATIVE):
        assert record.document_version, (
            f"{record.constant_id} cites {record.document!r} with no version. "
            "FDA's 2001 and 2026 guidances share a title and disagree."
        )


def test_normative_constants_declare_no_derivation():
    """Claiming a derivation for a stated value is the error itself.

    If a normative constant carries a formula, somebody has decided the
    regulator's number is computable - and the next step is computing it.
    """
    for record in constants_of_kind(ConstantKind.NORMATIVE):
        assert not record.derivation, (
            f"{record.constant_id} is normative and claims to be derived from "
            f"{record.derivation!r}."
        )


def test_derived_constants_state_their_derivation():
    for record in constants_of_kind(ConstantKind.DERIVED):
        assert record.derivation, (
            f"{record.constant_id} is derived from nothing stated, which makes "
            "it indistinguishable from a remembered number."
        )
        assert record.verification is VerificationStatus.DERIVED


def test_the_fda_switch_and_its_derived_lookalike_stay_distinct():
    """The specific substitution PR #54 reversed, pinned as a test.

    FDA states 0.294. sqrt(ln(1 + 0.30^2)) is 0.29356..., which is EMA's
    threshold expressed on the sWR scale. They are two different rules from two
    different regulators, and they must never be one entry.
    """
    stated = constant("FDA_HVD_SWR_SWITCH")
    derived = constant("DERIVED_SWR_AT_CV_30")

    assert stated.kind is ConstantKind.NORMATIVE
    assert derived.kind is ConstantKind.DERIVED
    assert stated.value == 0.294
    assert derived.value == pytest.approx(math.sqrt(math.log(1 + 0.30**2)))
    assert stated.value != derived.value
    assert stated.value - derived.value == pytest.approx(0.00044, abs=1e-5)

    assert derived.consumed_by == (), (
        "The derived lookalike must be read by nothing. The moment a decision "
        "path consumes it, this package is deciding with its own arithmetic "
        "instead of FDA's criterion."
    )


def test_the_ema_cap_is_applied_as_stated_and_not_as_computed():
    stated_lower = constant("EMA_ABEL_CAP_LOWER_PERCENT")
    computed_lower = constant("DERIVED_EMA_ABEL_CAP_LOWER_PERCENT")

    assert stated_lower.value == 69.84
    assert computed_lower.value != stated_lower.value
    assert computed_lower.consumed_by == ()
    assert stated_lower.consumed_by, (
        "The STATED cap must be the one something reads."
    )


def test_the_nti_delta_prose_constant_governs_and_the_example_does_not():
    """Appendix F states 1/0.9 in prose and prints 1.11111 in its SAS example."""
    prose = constant("FDA_NTI_DELTA")
    example = constant("FDA_NTI_SAS_EXAMPLE_DELTA")

    assert prose.kind is ConstantKind.NORMATIVE
    assert example.kind is ConstantKind.ILLUSTRATIVE
    assert prose.value == pytest.approx(1.0 / 0.9)
    assert example.value == 1.11111
    assert prose.value != example.value
    assert prose.consumed_by, "The prose constant must be the one that decides."
    assert example.consumed_by == ()


def test_illustrative_constants_are_read_by_nothing():
    """A number that appears in the guidance is not thereby the rule.

    Section III.A uses 0.294 with the OPPOSITE inequality for in vitro
    permeation testing. Finding the number in the document is not evidence
    about which rule applies.
    """
    for record in constants_of_kind(ConstantKind.ILLUSTRATIVE):
        assert record.consumed_by == (), (
            f"{record.constant_id} is illustrative and something consumes it."
        )


def test_derived_theta_values_match_what_the_package_computes():
    """The index is not a snapshot that can drift from the functions."""
    assert constant("DERIVED_FDA_HVD_THETA").value == pytest.approx(fda_hvd_theta())
    assert constant("DERIVED_FDA_NTI_THETA").value == pytest.approx(fda_nti_theta())


def test_no_two_constants_share_an_identifier_and_disagree():
    values: dict[str, float] = {}
    for record in CONSTANT_INDEX.values():
        assert record.constant_id not in values
        values[record.constant_id] = record.value


def test_provenance_coverage_is_complete():
    """Every indexed constant is either verified or explicitly derived.

    "Unverified" is a legitimate state that the package supports and must
    remain visible; the assertion is that none is currently in it, so a new
    unverified constant is a decision somebody makes on purpose.
    """
    coverage = provenance_coverage()
    assert coverage["total"] == len(CONSTANT_INDEX)
    assert coverage["verified"] + coverage["derived"] == coverage["total"], (
        f"{coverage['unverified']} constant(s) are neither verified against "
        "the primary document nor marked derived."
    )
    assert coverage["unverified"] == 0


def test_explain_answers_why_this_number_is_here():
    line = constant("FDA_HVD_SWR_SWITCH").explain()
    assert "0.294" in line
    assert "FDA" in line
    assert "normative" in line

    derived_line = constant("DERIVED_SWR_AT_CV_30").explain()
    assert "derived as" in derived_line
