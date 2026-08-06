"""Citation extraction and validation.

This module is the enforcement point for the system's central guarantee: a
citation in the report resolves to a record that was actually retrieved.

The guarantee is structural, not behavioural. Prompts *ask* the model to cite
only from the supplied allowlist, but prompts are advice. What makes the
guarantee hold is that every marker in generated text is extracted here and
checked against the evidence table, and anything that does not resolve is
removed and recorded. A model that hallucinates [E99] does not produce a
plausible fake citation in the output; it produces a flagged, stripped claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Matches [E12] and grouped forms such as [E1, E7] or [E1; E7].
_MARKER_BLOCK = re.compile(r"\[(E\d+(?:\s*[,;]\s*E\d+)*)\]")
_SINGLE_MARKER = re.compile(r"E\d+")


def extract_markers(text: str) -> list[str]:
    """Every evidence marker referenced in a block of text, in order of first
    appearance and without duplicates."""
    found: list[str] = []
    for block in _MARKER_BLOCK.finditer(text or ""):
        for marker in _SINGLE_MARKER.findall(block.group(1)):
            if marker not in found:
                found.append(marker)
    return found


@dataclass
class CitationValidation:
    """Outcome of checking one piece of generated text."""

    valid_markers: list[str] = field(default_factory=list)
    invalid_markers: list[str] = field(default_factory=list)
    cleaned_text: str = ""

    @property
    def ok(self) -> bool:
        return not self.invalid_markers


def validate_and_clean(text: str, known_markers: set[str]) -> CitationValidation:
    """Strip unresolvable citations from ``text``.

    A marker that is not in ``known_markers`` refers to a source that was never
    retrieved. It is removed and replaced with an explicit flag rather than left
    in place, because a citation that looks real but resolves to nothing is more
    damaging than a visible gap: a reader has no way to tell it is wrong.

    Markers within a group are handled individually, so [E1, E99] becomes
    [E1] plus a flag rather than losing the valid citation too.
    """
    valid: list[str] = []
    invalid: list[str] = []

    def replace(match: re.Match[str]) -> str:
        markers = _SINGLE_MARKER.findall(match.group(1))
        kept = []
        dropped = []
        for marker in markers:
            if marker in known_markers:
                if marker not in valid:
                    valid.append(marker)
                kept.append(marker)
            else:
                if marker not in invalid:
                    invalid.append(marker)
                dropped.append(marker)

        if kept and dropped:
            return f"[{', '.join(kept)}] [unverified citation removed]"
        if kept:
            return f"[{', '.join(kept)}]"
        return "[unverified citation removed]"

    cleaned = _MARKER_BLOCK.sub(replace, text or "")
    return CitationValidation(
        valid_markers=valid, invalid_markers=invalid, cleaned_text=cleaned
    )


def validate_claim_citations(
    citations: list[str], known_markers: set[str]
) -> tuple[list[str], list[str]]:
    """Split a claim's citation list into resolvable and unresolvable markers."""
    valid = [m for m in citations if m in known_markers]
    invalid = [m for m in citations if m not in known_markers]
    return valid, invalid


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #

#: Numeric claims that are not attributable to a source. Detecting these matters
#: because a specific-looking figure carries more weight than the prose around
#: it, so an uncited one is disproportionately misleading.
#: The trailing word boundary applies only to the alphabetic units. Placing it
#: after the whole alternation would break "%", because a word boundary cannot
#: exist between "%" and a following "." -- both are non-word characters, so
#: "15%." silently escaped detection.
_NUMERIC_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|(?:percent|mg|µg|ug|ng|mL|ml|L|kg|g|nm|µm|um|mm|"
    r"hours?|days?|weeks?|months?|years?|fold|x)\b)",
    re.IGNORECASE,
)

#: Language that asserts more certainty than research support can carry.
_OVERCONFIDENT = re.compile(
    r"\b(?:proven|proves|definitively|conclusively|guarantee[sd]?|certainly|"
    r"undoubtedly|always|never fails?|clearly demonstrates?|establishes? that|"
    r"confirms? that|will ensure)\b",
    re.IGNORECASE,
)


def find_uncited_numeric_claims(text: str) -> list[str]:
    """Sentences containing a quantitative claim but no citation."""
    findings = []
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if _NUMERIC_CLAIM.search(sentence) and not _MARKER_BLOCK.search(sentence):
            findings.append(sentence.strip())
    return findings


def find_overconfident_language(text: str) -> list[str]:
    """Phrases asserting certainty that retrieved evidence cannot support."""
    return sorted({m.group(0) for m in _OVERCONFIDENT.finditer(text or "")})


def compute_section_confidence(
    *,
    total_claims: int,
    cited_claims: int,
    distinct_sources: int,
    has_contradictions: bool,
) -> tuple[str, str]:
    """Derive a section's confidence from evidence coverage, not self-assessment.

    The model is never asked how confident it feels. Confidence here is a
    function of how much of the section is actually backed by distinct retrieved
    sources, because a fluent, well-written section with two citations is less
    trustworthy than a terse one with twelve, and only the second signal is
    observable.

    Returns (confidence, rationale).
    """
    if total_claims == 0:
        return "insufficient_evidence", "No claims were made in this section."

    coverage = cited_claims / total_claims

    if distinct_sources == 0:
        return (
            "insufficient_evidence",
            f"{total_claims} statements, none supported by a retrieved source.",
        )

    base = (
        "high" if coverage >= 0.8 and distinct_sources >= 5
        else "moderate" if coverage >= 0.6 and distinct_sources >= 3
        else "low"
    )

    rationale = (
        f"{cited_claims} of {total_claims} statements cited "
        f"({coverage:.0%} coverage) across {distinct_sources} distinct sources."
    )

    if has_contradictions and base == "high":
        # Sources disagreeing is exactly when a confident label is least earned.
        return "moderate", rationale + " Downgraded: sources disagree on this topic."
    if has_contradictions:
        return base, rationale + " Sources disagree on this topic."

    return base, rationale
