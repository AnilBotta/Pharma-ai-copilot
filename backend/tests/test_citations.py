"""Citation validation.

The system's central promise is that a citation in the report resolves to a
record that was actually retrieved. These tests are that promise. If any of
them fails, the product is capable of producing exactly the defect it exists to
eliminate: a source that looks real and is not.
"""

from __future__ import annotations

import pytest

from app.llm.citations import (
    compute_section_confidence,
    extract_markers,
    find_overconfident_language,
    find_uncited_numeric_claims,
    validate_and_clean,
    validate_claim_citations,
)


class TestMarkerExtraction:
    def test_finds_single_marker(self) -> None:
        assert extract_markers("Peptides degrade [E1].") == ["E1"]

    def test_finds_grouped_markers(self) -> None:
        assert extract_markers("Shown in vitro [E1, E7; E12].") == ["E1", "E7", "E12"]

    def test_deduplicates_and_preserves_order(self) -> None:
        assert extract_markers("[E3] then [E1] then [E3] again.") == ["E3", "E1"]

    def test_ignores_non_marker_brackets(self) -> None:
        assert extract_markers("See [Figure 1] and [the appendix].") == []

    def test_handles_empty_input(self) -> None:
        assert extract_markers("") == []


class TestCitationStripping:
    def test_known_markers_survive_untouched(self) -> None:
        result = validate_and_clean("Stable at 4C [E1].", {"E1"})
        assert result.ok is True
        assert result.cleaned_text == "Stable at 4C [E1]."
        assert result.valid_markers == ["E1"]

    def test_hallucinated_marker_is_removed_not_left_looking_real(self) -> None:
        # The defining test. A model citing a source it never saw must not be
        # able to produce output where that citation appears legitimate.
        result = validate_and_clean("Release lasts 28 days [E99].", {"E1"})
        assert result.ok is False
        assert result.invalid_markers == ["E99"]
        assert "E99" not in result.cleaned_text
        assert "[unverified citation removed]" in result.cleaned_text

    def test_valid_citation_survives_alongside_an_invalid_one(self) -> None:
        result = validate_and_clean("Both agree [E1, E99].", {"E1"})
        assert result.valid_markers == ["E1"]
        assert result.invalid_markers == ["E99"]
        assert "[E1]" in result.cleaned_text
        assert "[unverified citation removed]" in result.cleaned_text
        assert "E99" not in result.cleaned_text

    def test_empty_allowlist_rejects_everything(self) -> None:
        # When nothing was retrieved, nothing is citable.
        result = validate_and_clean("Widely reported [E1].", set())
        assert result.invalid_markers == ["E1"]
        assert "E1" not in result.cleaned_text

    def test_multiple_invalid_markers_are_all_reported(self) -> None:
        result = validate_and_clean("Claim one [E5]. Claim two [E6].", {"E1"})
        assert result.invalid_markers == ["E5", "E6"]

    def test_text_without_citations_is_unchanged(self) -> None:
        text = "This section makes no evidential claims."
        assert validate_and_clean(text, {"E1"}).cleaned_text == text

    def test_claim_citation_lists_are_split(self) -> None:
        valid, invalid = validate_claim_citations(["E1", "E99", "E2"], {"E1", "E2"})
        assert valid == ["E1", "E2"]
        assert invalid == ["E99"]


class TestUncitedNumericClaims:
    @pytest.mark.parametrize(
        "sentence",
        [
            "Release continued for 28 days.",
            "Bioavailability was 0.4%.",
            "Loading reached 45 mg per gram.",
            "Particle size was 150 nm.",
            "Exposure increased 3 fold.",
        ],
    )
    def test_quantitative_claims_without_citation_are_flagged(self, sentence: str) -> None:
        assert find_uncited_numeric_claims(sentence) == [sentence]

    def test_cited_numeric_claim_is_not_flagged(self) -> None:
        assert find_uncited_numeric_claims("Release continued for 28 days [E4].") == []

    def test_non_numeric_prose_is_not_flagged(self) -> None:
        assert find_uncited_numeric_claims("The peptide was stable.") == []

    def test_only_the_offending_sentence_is_returned(self) -> None:
        text = "The approach is promising. Burst release was 15%. It merits study."
        assert find_uncited_numeric_claims(text) == ["Burst release was 15%."]


class TestOverconfidentLanguage:
    @pytest.mark.parametrize(
        "phrase",
        ["proven", "conclusively", "guarantees", "definitively", "will ensure", "always"],
    )
    def test_certainty_language_is_detected(self, phrase: str) -> None:
        assert find_overconfident_language(f"This {phrase} works.")

    def test_hedged_language_passes(self) -> None:
        text = "The data suggest this may improve stability, though evidence is limited."
        assert find_overconfident_language(text) == []

    def test_detection_is_case_insensitive(self) -> None:
        assert find_overconfident_language("This PROVEN method.") == ["PROVEN"]


class TestSectionConfidence:
    def test_no_claims_means_insufficient_evidence(self) -> None:
        level, _ = compute_section_confidence(
            total_claims=0, cited_claims=0, distinct_sources=0, has_contradictions=False
        )
        assert level == "insufficient_evidence"

    def test_uncited_section_is_insufficient_regardless_of_length(self) -> None:
        # A long, fluent, entirely uncited section is the worst case, not a good one.
        level, rationale = compute_section_confidence(
            total_claims=20, cited_claims=0, distinct_sources=0, has_contradictions=False
        )
        assert level == "insufficient_evidence"
        assert "none supported" in rationale

    def test_high_confidence_needs_both_coverage_and_source_breadth(self) -> None:
        level, _ = compute_section_confidence(
            total_claims=10, cited_claims=9, distinct_sources=6, has_contradictions=False
        )
        assert level == "high"

    def test_good_coverage_from_too_few_sources_is_not_high(self) -> None:
        # Nine of ten claims citing the same two papers is not strong evidence.
        level, _ = compute_section_confidence(
            total_claims=10, cited_claims=9, distinct_sources=2, has_contradictions=False
        )
        assert level == "low"

    def test_moderate_band(self) -> None:
        level, _ = compute_section_confidence(
            total_claims=10, cited_claims=7, distinct_sources=4, has_contradictions=False
        )
        assert level == "moderate"

    def test_contradictions_downgrade_high_confidence(self) -> None:
        level, rationale = compute_section_confidence(
            total_claims=10, cited_claims=9, distinct_sources=6, has_contradictions=True
        )
        assert level == "moderate"
        assert "disagree" in rationale

    def test_contradictions_are_noted_even_when_not_downgrading(self) -> None:
        _, rationale = compute_section_confidence(
            total_claims=10, cited_claims=7, distinct_sources=4, has_contradictions=True
        )
        assert "disagree" in rationale

    def test_rationale_reports_the_actual_numbers(self) -> None:
        _, rationale = compute_section_confidence(
            total_claims=10, cited_claims=8, distinct_sources=5, has_contradictions=False
        )
        assert "8 of 10" in rationale
        assert "80%" in rationale
        assert "5 distinct sources" in rationale
