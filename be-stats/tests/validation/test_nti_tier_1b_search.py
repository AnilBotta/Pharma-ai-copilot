"""The FDA NTI tier-1B search: what was opened, and why nothing was adopted.

A negative evidentiary claim is only as good as the record of looking. DOSSIER-
003 and the NTI capability rows say FDA has published no worked NTI example;
`dossier.evidence_search.FDA_NTI_TIER_1B_SEARCH` is the record behind that, and
these tests hold it to the same standard as the ordinary-ABE search.
"""

from __future__ import annotations

from be_stats import CAPABILITY_VALIDATION, VALIDATION, Capability, Method
from be_stats.dossier.evidence import EVIDENCE_MANIFEST, SourceType
from be_stats.dossier.evidence_search import (
    FDA_NTI_TIER_1B_SEARCH,
    ORDINARY_ABE_TIER_1B_SEARCH,
    SearchVerdict,
    adopted_sources,
    rejected_candidates,
    sources_with_verdict,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import Authority, ValidationStatus


def test_every_source_is_identified_well_enough_to_re_open():
    assert FDA_NTI_TIER_1B_SEARCH, "An empty search would pass vacuously."
    for source in FDA_NTI_TIER_1B_SEARCH:
        assert source.authority == "FDA", source.document
        assert "narrow therapeutic index" in source.sought
        for field in ("document", "document_version", "sections_read", "found"):
            assert getattr(source, field).strip(), (source.document, field)
        assert source.url.startswith("https://"), source.document


def test_the_governing_guidance_was_read_and_publishes_no_output():
    governing = [
        s for s in FDA_NTI_TIER_1B_SEARCH
        if s.document == "Statistical Approaches to Establishing Bioequivalence"
    ]
    assert len(governing) == 1
    assert governing[0].document_version == "final, May 2026"
    assert governing[0].verdict is SearchVerdict.NO_NUMERICAL_OUTPUT
    assert "Appendix F" in governing[0].sections_read


def test_nothing_was_adopted_and_that_is_the_answer():
    assert adopted_sources(FDA_NTI_TIER_1B_SEARCH) == []
    assert sources_with_verdict(SearchVerdict.ADOPTED, FDA_NTI_TIER_1B_SEARCH) == []


def test_a_rejected_candidate_says_which_condition_it_fails():
    rejected = rejected_candidates(FDA_NTI_TIER_1B_SEARCH)
    assert rejected, "the near miss must be recorded, not dropped"
    for source in rejected:
        assert source.rejected_because.strip(), source.document


def test_a_document_with_no_numbers_needs_no_rejection_reason():
    for source in sources_with_verdict(
        SearchVerdict.NO_NUMERICAL_OUTPUT, FDA_NTI_TIER_1B_SEARCH
    ):
        assert not source.rejected_because, source.document


def test_the_helpers_still_default_to_the_ordinary_abe_search():
    """Generalising the helpers must not change what existing callers get."""
    assert adopted_sources() == adopted_sources(ORDINARY_ABE_TIER_1B_SEARCH)
    assert rejected_candidates() == rejected_candidates(ORDINARY_ABE_TIER_1B_SEARCH)
    assert not set(s.sought for s in FDA_NTI_TIER_1B_SEARCH) & set(
        s.sought for s in ORDINARY_ABE_TIER_1B_SEARCH
    ), "the two searches answer different questions and must stay separate"


def test_the_only_tier_1b_label_near_nti_is_inherited_appendix_c_evidence():
    """FDA_NTI_UNSCALED_ABE carries a TIER_1B label, and it is not NTI evidence.

    It is EMA's published output for the unscaled Appendix C mixed model, which
    criterion (b) is computed through. The test pins exactly that: any tier-1B
    record touching an FDA NTI capability touches only criterion (b), also
    covers the Appendix C capability it really belongs to, and is not FDA's.
    """
    for record in EVIDENCE_MANIFEST:
        if record.tier is not EvidenceTier.TIER_1B:
            continue
        nti = [c for c in record.capabilities if c.startswith("FDA_NTI")]
        if not nti:
            continue
        assert nti == ["FDA_NTI_UNSCALED_ABE"], record.evidence_id
        assert "FDA_REPLICATE_STANDARD_ABE_FULL" in record.capabilities
        # Structural, not a string test on the prose authority. That prose
        # reads "... attributes to FDA by name. NOT FDA." and contains "FDA".
        assert record.evidence_authority is not Authority.FDA, record.evidence_id


def test_powertost_stays_tier_3_for_nti():
    """An independent implementation is tier 3, whatever it cross-checks.

    Selected by source type rather than by the words "PowerTOST" at the start
    of a free-text field, which a reworded label would silently stop matching.
    """
    implementations = [
        r
        for r in EVIDENCE_MANIFEST
        if r.source_type is SourceType.INDEPENDENT_IMPLEMENTATION
    ]
    assert any("FDA_NTI_RSABE" in r.capabilities for r in implementations)
    for record in implementations:
        assert record.tier is EvidenceTier.TIER_3, record.evidence_id
        assert record.evidence_authority is None, record.evidence_id


def test_the_search_promotes_nothing():
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    for capability in Capability:
        if capability.name.startswith("FDA_NTI"):
            assert CAPABILITY_VALIDATION[capability] is not ValidationStatus.VALIDATED
