"""The tier-1B search, and the confusions it exists to make impossible.

The registry in `dossier.evidence_search` records what was opened and what it
turned out to be. These tests keep it honest in the two directions that
matter: a search entry may not claim more than it found, and nothing below
tier 1B may drift upward into it.
"""

from __future__ import annotations

from be_stats.dossier.evidence import EVIDENCE_MANIFEST, evidence_for
from be_stats.dossier.evidence_search import (
    ORDINARY_ABE_TIER_1B_SEARCH,
    SearchVerdict,
    adopted_sources,
    rejected_candidates,
)
from be_stats.dossier.findings import FINDINGS, FindingStatus
from be_stats.dossier.statuses import EvidenceTier

CAP = "AVERAGE_BE_2X2"


# ------------------------------------------------------ the registry itself ---


def test_every_searched_source_is_identified_well_enough_to_re_open():
    """A search nobody can repeat is an assertion, which is the whole point."""
    assert ORDINARY_ABE_TIER_1B_SEARCH, "An empty search would pass vacuously."

    for source in ORDINARY_ABE_TIER_1B_SEARCH:
        label = f"{source.authority}/{source.document}"
        assert source.authority.strip(), label
        assert source.document.strip(), label
        assert source.document_version.strip(), (
            f"{label} names no issue. A document without a version is not a "
            "document - the same rule the citation policy applies."
        )
        assert source.sections_read.strip(), (
            f"{label} does not say WHICH sections were read. 'We looked' is "
            "not a search record."
        )
        assert source.found.strip(), label
        assert source.sought.strip(), label


def test_a_rejected_candidate_states_which_condition_it_fails():
    """The near miss is the dangerous case: it gets found again.

    An unexplained rejection sends the next reader to redo the reasoning, and
    they may reach a more convenient answer.
    """
    rejected = rejected_candidates()
    assert rejected, "No rejected candidates; this guard would pass vacuously."

    for source in rejected:
        assert len(source.rejected_because) > 80, (
            f"{source.document}: a one-line rejection is an excuse. Say which "
            "condition it fails and why that condition is not negotiable."
        )


def test_a_verdict_of_no_numerical_output_carries_no_rejection_reason():
    """Those two fields answer different questions.

    A document that publishes no numbers is not a rejected candidate - it was
    never a candidate. Filling in `rejected_because` for one would read as a
    criticism of a guidance for being a guidance.
    """
    for source in ORDINARY_ABE_TIER_1B_SEARCH:
        if source.verdict is SearchVerdict.NO_NUMERICAL_OUTPUT:
            assert not source.rejected_because, source.document


def test_the_search_found_nothing_adoptable_and_says_so():
    """The result of this search, asserted rather than left to inference."""
    assert adopted_sources() == [], (
        "The search now reports an adopted source. If a tier-1B example has "
        "genuinely been found, DOSSIER-003 must be reconsidered through the "
        "governed route - and this test is where that argument starts."
    )


# ---------------------------------------------- tiers may not drift upward ---


def test_powertost_remains_tier_3_and_is_not_regulatory_authority():
    powertost = [
        r for r in EVIDENCE_MANIFEST if "POWERTOST" in r.evidence_id.upper()
    ]
    assert powertost, "The PowerTOST record is gone; this guard is vacuous."

    for record in powertost:
        assert record.tier is EvidenceTier.TIER_3, (
            f"{record.evidence_id} has moved off tier 3. An independent "
            "implementation agreeing is engineering evidence, not the "
            "regulator's own numbers, however well it agrees."
        )


def test_tier_1a_and_tier_1b_stay_distinct():
    """A stated algorithm and a published result are different claims.

    Both come from a regulator, which is exactly why they are easy to merge -
    and merging them would let a documented procedure count as a reproduced
    number.
    """
    from be_stats.dossier.evidence import SourceType

    for record in EVIDENCE_MANIFEST:
        if record.tier is EvidenceTier.TIER_1A:
            assert record.source_type is not SourceType.REGULATOR_PUBLISHED_NUMBERS, (
                f"{record.evidence_id} is tier 1A and claims a regulator's "
                "published NUMBERS as its source type."
            )
        if record.tier is EvidenceTier.TIER_1B:
            assert record.source_type is SourceType.REGULATOR_PUBLISHED_NUMBERS, (
                f"{record.evidence_id} is tier 1B without regulator-published "
                "numbers behind it. Tier 1B is the bar for VALIDATED and "
                "nothing below it substitutes."
            )


def test_no_evidence_record_says_validated_by_a_regulator():
    """Wording, policed where it would carry force.

    Reproducing a regulator's published number is not the regulator having
    validated anything. The phrase is checked across the fields a report
    prints, with the findings register left out - it is allowed to describe
    the error it exists to record.
    """
    for record in EVIDENCE_MANIFEST:
        text = " ".join(
            (record.scenario, record.expected, record.observed, record.note)
        ).lower()
        for phrase in ("validated by fda", "validated by ema", "validated by the regulator"):
            assert phrase not in text, f"{record.evidence_id}: {phrase!r}"


# ------------------------------------ tier 1B alone promotes nothing, ever ---


def test_establishing_tier_1b_does_not_move_the_validation_status(monkeypatch):
    """§10, asserted by DOING it rather than by describing the rule.

    A passing tier-1B record is injected for AVERAGE_BE_2X2 and the canonical
    status is read back. It must not move: status lives in `spec.VALIDATION`
    and is changed by a reviewed transition, never by evidence arriving.
    """
    from be_stats.dossier import capabilities
    from be_stats.dossier.evidence import (
        EvidenceRecord,
        EvidenceStatus,
        SourceType,
    )
    from be_stats.spec import ValidationStatus

    before = capabilities.CAPABILITY_MATRIX[CAP].validation_status

    injected = EvidenceRecord(
        evidence_id="TEST-ONLY-INJECTED-TIER-1B",
        capabilities=(CAP,),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="test fixture",
        scenario="Synthetic, to prove evidence does not promote.",
        dataset="-",
        software_environment="-",
        expected="-",
        observed="-",
        tolerance="-",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_dossier_evidence_search.py",
    )
    monkeypatch.setattr(
        "be_stats.dossier.evidence.EVIDENCE_MANIFEST",
        (*EVIDENCE_MANIFEST, injected),
    )

    after = capabilities.CAPABILITY_MATRIX[CAP].validation_status
    assert after is before is ValidationStatus.IMPLEMENTED_UNVALIDATED, (
        "Adding tier-1B evidence changed the validation status. Status is "
        "canonical in spec.VALIDATION and moves only through a reviewed "
        "transition; evidence makes a promotion POSSIBLE, it does not "
        "perform one."
    )


def test_dossier_003_stays_open_while_the_capability_has_no_tier_1b():
    """The finding cannot be closed by editing the register alone."""
    finding = FINDINGS["DOSSIER-003"]
    tier_1b = [r for r in evidence_for(CAP) if r.tier is EvidenceTier.TIER_1B]

    if not tier_1b:
        assert finding.status is FindingStatus.OPEN, (
            "DOSSIER-003 reads closed while AVERAGE_BE_2X2 still holds no "
            "tier-1B evidence. The finding tracks the absence of that "
            "evidence, so the register may not resolve ahead of the data."
        )


def test_dossier_003_resolution_condition_says_what_is_still_missing():
    """A condition that only says 'more evidence' closes on anything.

    All three requirements are general governance policy for a future tier-1B
    source. They are NOT a list of what the GL52 candidate failed - it
    satisfies FINAL - and the condition says so explicitly, because a reader
    who assumes otherwise reconstructs the error this PR was reviewed for.
    """
    condition = FINDINGS["DOSSIER-003"].resolution_condition.lower()
    for requirement in ("human", "final", "consistent"):
        assert requirement in condition, (
            f"The resolution condition no longer requires {requirement!r}. "
            "Each is a standing requirement on a future tier-1B source."
        )
    assert "satisfies final" in condition, (
        "The condition no longer records that CVM GFI #224 meets the FINAL "
        "requirement. Without that sentence the three requirements read as "
        "the candidate's three failures, which is the misstatement corrected "
        "here."
    )


def test_no_finding_calls_the_cvm_supplement_a_draft():
    """The corrected claim, policed in the register too.

    DOSSIER-003's evidence text carried the same error as the search record.
    Asserted on the sentence that would restate it rather than on the word,
    which the correction itself has to use.
    """
    evidence_text = FINDINGS["DOSSIER-003"].evidence
    assert "it supplements a DRAFT" not in evidence_text, (
        "DOSSIER-003 again describes CVM GFI #224 as supplementing a draft "
        "as a ground for rejection. It is a final guidance, September 2014."
    )
    assert "FINAL guidance" in evidence_text, (
        "DOSSIER-003 no longer records that the candidate is a final "
        "guidance, which is the fact the correction turned on."
    )
