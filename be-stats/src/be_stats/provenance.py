"""Where every regulatory number came from.

THE QUESTION THIS MODULE EXISTS TO ANSWER

"Why did you use 0.90?" must have a better answer than "because constants.py
says so". A bare float in source is indistinguishable from a remembered one,
and a remembered constant that is subtly wrong is indistinguishable from a
correct one until a submission fails.

So a regulatory number is not a float here. It is a value plus the document it
came from, the section within it, the version of that document, and whether
anybody has actually checked it.

PIN THE DOCUMENT, NOT THE AUTHORITY

"FDA" is not a citation. FDA's *Statistical Approaches to Establishing
Bioequivalence* was issued on 29 May 2026 and replaced the February 2001
guidance of the same title, which said materially different things. A result
computed under one and read under the other is a trap, so the version is part
of the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerificationStatus(StrEnum):
    """How much weight this number can carry."""

    #: Read from the cited document by a person, at the cited version.
    VERIFIED = "verified"
    #: Believed correct, not yet checked against the primary source. Must be
    #: visible wherever it is used - never silently equivalent to VERIFIED.
    UNVERIFIED = "unverified"
    #: Computed from another value rather than transcribed, e.g. the HVD
    #: switching threshold derived from a 30% CV. Its trustworthiness is that
    #: of its input plus the derivation.
    DERIVED = "derived"


class ValidationStatus(StrEnum):
    """How far a method has got toward being usable for a submission.

    A production caller should refuse anything below VALIDATED; a development
    caller opts in deliberately. The point is that "we implemented it" and "it
    has been shown to agree with the regulator" are different claims, and only
    the second one licenses a filing.
    """

    NOT_IMPLEMENTED = "not_implemented"
    EXPERIMENTAL = "experimental"
    IMPLEMENTED_UNVALIDATED = "implemented_unvalidated"
    VALIDATED = "validated"


@dataclass(frozen=True, slots=True)
class Citation:
    """A document, precisely enough to find the same words again."""

    authority: str
    document: str
    #: Section, appendix or question number. "" only when the document is short
    #: enough that the whole of it is the citation.
    section: str = ""
    #: Issue or revision date. The single most load-bearing field here: FDA's
    #: 2001 and 2026 guidances share a title and disagree.
    document_version: str = ""
    url: str = ""

    def __str__(self) -> str:
        parts = [self.authority, self.document]
        if self.section:
            parts.append(self.section)
        if self.document_version:
            parts.append(f"({self.document_version})")
        return " — ".join(parts[:2]) + (
            ", " + ", ".join(parts[2:]) if len(parts) > 2 else ""
        )


@dataclass(frozen=True, slots=True)
class RegulatoryValue:
    """A number that came from somewhere, and says where."""

    value: float
    citation: Citation
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    #: Free text for anything the citation cannot carry, e.g. what the value
    #: was derived from.
    note: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verification is VerificationStatus.VERIFIED

    def explain(self) -> str:
        """One line a report can print beside the number it used."""
        line = f"{self.value} — {self.citation} [{self.verification}]"
        return f"{line}. {self.note}" if self.note else line


# ------------------------------------------------------------- documents ---
# Declared once so a version cannot drift between the places it is cited.

FDA_STATISTICAL_APPROACHES = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    document_version="final, 29 May 2026",
    url="https://www.fda.gov/regulatory-information/search-fda-guidance-documents/statistical-approaches-establishing-bioequivalence",
)

FDA_NASAL_LOCAL_ACTION = Citation(
    authority="FDA",
    document=(
        "Bioavailability and Bioequivalence Studies for Nasal Aerosols and "
        "Nasal Sprays for Local Action"
    ),
    document_version="draft, reissued 2003",
)

EMA_BIOEQUIVALENCE = Citation(
    authority="EMA",
    document="Guideline on the Investigation of Bioequivalence",
    section="Narrow therapeutic index drugs",
    document_version="current",
)

ICH_M13A_QA = Citation(
    authority="ICH",
    document=(
        "M13A — Bioequivalence for Immediate-Release Solid Oral Dosage Forms: "
        "Questions and Answers"
    ),
    section="Q&A 2.1",
    document_version="current",
)

#: A stand-in for values this package computes rather than cites.
DERIVED_INTERNALLY = Citation(
    authority="be-stats",
    document="derived, not transcribed",
)
