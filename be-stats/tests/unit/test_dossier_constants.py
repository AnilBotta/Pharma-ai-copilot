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
    derivation_inputs,
    provenance_coverage,
    unpinned_normative_constants,
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


def test_normative_constants_are_pinned_to_a_section_or_declare_why_not():
    """The check the previous release was missing.

    Only `document_version` was asserted, so two normative records with an
    EMPTY section passed - and a report built on the coverage numbers then
    claimed all of them carried document, section and version. Nothing counted
    sections, so nothing could contradict it.

    A section is required because a guidance runs to dozens of pages, "FDA
    says so" is not a citation anybody can check, and a rule can sit beside
    its near-twin in a different section of the same document - which is
    exactly what `FDA_IVPT_SWR_THRESHOLD` records.
    """
    for record in constants_of_kind(ConstantKind.NORMATIVE):
        if record.section:
            assert not record.citation_exception, (
                f"{record.constant_id} has a section AND an exception. One of "
                "the two is wrong, and a stale exception is the more "
                "dangerous: it excludes a pinned record from the count."
            )
            continue

        assert record.citation_exception, (
            f"{record.constant_id} is normative, cites "
            f"{record.document!r} with no section, and gives no reason. An "
            "empty section makes 'we have not pinned this yet' and 'this "
            "document has no sections' look identical, and only one of them "
            "is outstanding work."
        )


def test_a_citation_exception_is_specific_enough_to_act_on():
    """Not an escape hatch. It has to say what would close it."""
    for record in unpinned_normative_constants():
        exception = record.citation_exception
        assert len(exception) > 60, (
            f"{record.constant_id}: a one-line exception is an excuse. Say "
            "what is missing and what would close it."
        )
        assert "DOSSIER-004" in exception, (
            f"{record.constant_id}: an unpinned normative constant must point "
            "at the finding tracking it, so the gap is registered rather than "
            "absorbed."
        )


def test_no_normative_constant_is_unpinned():
    """The set was {CONVENTIONAL_LOWER_PERCENT, CONVENTIONAL_UPPER_PERCENT}.

    Both were closed by citing ICH M13A 2.2.4, so the set is now empty and the
    assertion is the strongest available: a new unpinned normative constant
    cannot appear at all without failing here. The exact-set form this
    replaces existed so a THIRD one could not hide behind a count of two; an
    empty set does that job without needing a list to maintain.
    """
    unpinned = {r.constant_id for r in unpinned_normative_constants()}
    assert unpinned == set(), (
        f"{sorted(unpinned)} are normative and not pinned. Either cite the "
        "document or declare a CitationException tracked by a finding - "
        "silently unpinned is the one option that is not available."
    )


def test_dossier_005_is_resolved_and_backed_by_the_behaviour():
    """Closure that cannot be asserted in the register alone.

    A finding may not read RESOLVED because somebody edited its status. The
    behaviour it tracked is exercised here: the pivotal floor applies, the
    pilot floor does not, and an unstated role collects neither.
    """
    from be_stats.dossier.findings import FINDINGS, FindingStatus
    from be_stats.minimums import (
        DesignFamily,
        Framework,
        MinimumApplicability,
        StudyRole,
        lookup,
    )

    finding = FINDINGS["DOSSIER-005"]
    assert finding.status is FindingStatus.RESOLVED

    def outcome(role):
        return lookup(
            "FDA",
            DesignFamily.CROSSOVER,
            framework=Framework.ICH_M13A,
            study_role=role,
        )

    assert outcome(StudyRole.PIVOTAL).required_total() == 12
    assert outcome(StudyRole.PILOT).required_total() is None
    assert outcome(StudyRole.NOT_STATED).required_total() is None
    assert (
        outcome(StudyRole.NOT_STATED).applicability
        is MinimumApplicability.ROLE_NOT_STATED
    ), (
        "DOSSIER-005 reads RESOLVED while an unstated role still collects "
        "M13A's floor, or while it is indistinguishable from a pilot."
    )

    # And the rule that is NOT role-scoped still applies to every role.
    for role in StudyRole:
        general = lookup(
            "FDA",
            DesignFamily.CROSSOVER,
            framework=Framework.GENERAL,
            study_role=role,
        )
        assert general.required_total() == 12, role


def test_dossier_004_is_resolved_and_still_on_the_register():
    """Closed findings are not deleted, and closure is not self-asserted.

    Two halves. The register must still carry DOSSIER-004 - a register that
    forgets what was wrong cannot be audited - and its RESOLVED status must be
    backed by the citation actually being pinned, so the status cannot be
    flipped in the register alone.
    """
    from be_stats.dossier.capabilities import CAPABILITY_MATRIX
    from be_stats.dossier.findings import FINDINGS, FindingStatus

    finding = FINDINGS["DOSSIER-004"]
    assert finding.status is FindingStatus.RESOLVED
    assert not finding.is_open

    assert CAPABILITY_MATRIX["AVERAGE_BE_2X2"].has_pinned_source, (
        "DOSSIER-004 reads RESOLVED while the citation it tracked is still "
        "unpinned. The register may not close a gap the data still shows."
    )

    # The history it exists to preserve.
    assert "was not" in finding.description or "were" in finding.evidence
    assert "80.00-125.00" in finding.description


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


def test_derived_constants_name_the_inputs_they_derive_from():
    """"What normative inputs produced this?" must have an answer.

    A derivation string alone is prose. Ids resolve, so the question can be
    answered by following them rather than by reading a formula and hoping the
    names in it correspond to records.
    """
    for record in constants_of_kind(ConstantKind.DERIVED):
        assert record.derived_from, (
            f"{record.constant_id} states a derivation and names no inputs, "
            "so the dossier cannot say what normative values produced it."
        )
        for input_id in record.derived_from:
            assert input_id in CONSTANT_INDEX, (
                f"{record.constant_id} derives from {input_id!r}, which is "
                "not an indexed constant."
            )


def test_a_derived_constant_never_derives_from_another_derived_one():
    """The chain has to bottom out in something a regulator wrote.

    A derived value computed from another derived value can drift two steps
    away from any stated rule while every individual record still looks
    correct.
    """
    for record in constants_of_kind(ConstantKind.DERIVED):
        for source in derivation_inputs(record.constant_id):
            assert source.kind is not ConstantKind.DERIVED, (
                f"{record.constant_id} derives from {source.constant_id}, "
                "which is itself derived."
            )


def test_the_derivation_expression_names_ids_rather_than_copying_values():
    """Ids, not numbers - in the DERIVATION, which is the load-bearing field.

    Scoped to `derivation` deliberately. An earlier version of this test also
    scanned `role` and `note`, and failed on
    DERIVED_FDA_NTI_THETA_SAS_EXAMPLE, whose prose says "the printed 1.11111"
    while EXPLAINING that the printed value is not the rule. Prose about a
    value is not a copy of it, and a test that cannot tell the difference
    punishes the records that explain themselves best.

    This repository has made that mistake with "validation_status", "signed",
    a relative fetch and the word "alias". The fix each time was to assert on
    the field that carries the meaning, not on every character nearby.
    """
    for record in constants_of_kind(ConstantKind.DERIVED):
        for source in derivation_inputs(record.constant_id):
            rendered = f"{source.value:g}"
            # A bare "30" is legitimate in an expression like "at CV = 0.30";
            # the failure guarded is a full-precision copy standing in for the
            # reference.
            if len(rendered) < 4:
                continue
            assert rendered not in record.derivation, (
                f"{record.constant_id}'s derivation contains {rendered}, the "
                f"value of {source.constant_id}. Reference the id; a copied "
                "constant is one that can go stale."
            )


def test_every_derived_input_id_is_actually_used_by_the_derivation():
    """`derived_from` must describe the formula, not accompany it.

    A list of ids nobody checks against the expression is decoration. The one
    documented exception is DERIVED_FDA_HVD_THETA, whose 1.25 is a literal in
    `spec.fda_hvd_theta` rather than a read of the indexed constant - and its
    note says exactly that rather than letting the mismatch pass unremarked.
    """
    for record in constants_of_kind(ConstantKind.DERIVED):
        unused = [
            input_id
            for input_id in record.derived_from
            if input_id not in record.derivation
        ]
        if not unused:
            continue
        for input_id in unused:
            # Not a keyword search for "literal" or "documentary" - that is
            # the blunt-match habit this file warns about two tests up. The
            # requirement is that the record NAMES the input it listed but
            # does not compute with, which cannot be satisfied by generic
            # hedging prose.
            assert input_id in record.note, (
                f"{record.constant_id} lists {input_id} as an input, its "
                "derivation does not use it, and its note does not mention "
                "it. Either the formula should consume it or the note should "
                "say why it is listed."
            )


def test_the_abel_cap_derivation_names_the_cap_cv_not_the_acceptance_ratio():
    """A correction, pinned so it cannot revert.

    The derivation read `sqrt(ln(1.25))`, which is the right NUMBER from the
    wrong input: the 1.25 there is 1 + (50/100)^2 from the cap CV, not the
    1.25 acceptance ratio. They coincide because the cap sits at CVwR = 50%,
    and writing the coincidence made the cap look as though it descended from
    the acceptance limits. It does not.
    """
    record = constant("DERIVED_EMA_ABEL_CAP_LOWER_PERCENT")
    assert record.derived_from == ("EMA_ABEL_K", "EMA_ABEL_CAP_CV_PERCENT")
    assert "EMA_ABEL_CAP_CV_PERCENT" in record.derivation
    assert "CONVENTIONAL_UPPER_PERCENT" not in record.derived_from


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


def test_provenance_coverage_counts_what_its_names_say():
    """Each denominator is the set its requirement actually applies to.

    The previous shape returned `verified`, `derived` and `unverified` over
    every constant at once, and counted no sections at all. A report built on
    it claimed all 29 carried document, section and version - which nothing in
    the data supported and nothing in the metrics could contradict.
    """
    coverage = provenance_coverage()

    assert coverage["total"] == len(CONSTANT_INDEX)
    assert (
        coverage["normative"] + coverage["derived"] + coverage["illustrative"]
        == coverage["total"]
    ), "The three kinds must partition the index."

    # The floor every record clears: authority, a source label, a role.
    assert coverage["classified"] == coverage["total"]

    # Normative: pinned plus declared exceptions accounts for all of them, and
    # the exception count is not allowed to be a silent remainder.
    assert (
        coverage["normative_pinned"] + coverage["normative_exceptions"]
        == coverage["normative"]
    )
    assert coverage["normative_exceptions"] == len(unpinned_normative_constants())
    assert coverage["normative_verified"] == coverage["normative"]

    # Derived: all state a derivation, all name inputs, all carry DERIVED.
    assert coverage["derived_with_derivation"] == coverage["derived"]
    assert coverage["derived_with_inputs"] == coverage["derived"]
    assert coverage["derived_status"] == coverage["derived"]

    # Illustrative: present in a document, read by nothing.
    assert coverage["illustrative_unconsumed"] == coverage["illustrative"]


def test_coverage_does_not_report_a_pinned_count_it_cannot_support():
    """The specific false claim, still impossible to restate from the metrics.

    This test used to read `normative_pinned < normative` and pin the pair at
    19/21, with a note saying to delete it once DOSSIER-004 closed by citing a
    document. That has now happened, and the shortfall is gone - but the claim
    the test was built to prevent was never "some constants are unpinned". It
    was "all 29 carry document, section and version", made over the WRONG
    DENOMINATOR: three derived constants carry no regulatory section, because
    no regulator states them, and no honest count will ever include them.

    So the guard survives its own gap. 21/21 is now true of the normative set
    and remains false of the index, and the numbers still contradict the old
    sentence rather than merely failing to support it.
    """
    coverage = provenance_coverage()

    assert coverage["normative_pinned"] == coverage["normative"], (
        "A normative constant has become unpinned. That is a regression in "
        "provenance, not a metric to update."
    )
    assert coverage["normative_pinned"] < coverage["total"], (
        "The pinned count has reached the size of the whole index, which is "
        "the number the discredited claim was made over. Derived constants "
        "have no regulatory section and must never be counted as pinned."
    )
    assert coverage["derived"] > 0


def test_explain_answers_why_this_number_is_here():
    line = constant("FDA_HVD_SWR_SWITCH").explain()
    assert "0.294" in line
    assert "FDA" in line
    assert "normative" in line

    derived_line = constant("DERIVED_SWR_AT_CV_30").explain()
    assert "derived as" in derived_line
