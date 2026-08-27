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
Bioequivalence* is dated May 2026 and states on its first page that it replaces
the February 2001 guidance of the same title, which said materially different
things. A result computed under one and read under the other is a trap, so the
version is part of the record.

A CORRECTION TO THAT VERSION STRING

These citations previously read "final, 29 May 2026". The document's cover
gives only **May 2026**, and nothing inside it names a day. The precise date
came from recollection, not from the document, and an over-specific citation is
worse than a coarse one: it looks checked. Now "final, May 2026", which is what
the guidance itself says.
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
    #: Implemented, and there is no external numeric claim to validate against.
    #: Structural work lives here: a design validator either enforces the
    #: regulator's design definitions or it does not, and no worked dataset can
    #: tell you more than the tests already do. Distinct from the status below,
    #: which names a computed NUMBER that nobody has checked against a
    #: regulator - that gap is real and this one is not.
    IMPLEMENTED = "implemented"
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
    #: HOW it was checked, which is not the same as whether. A figure read from
    #: the primary document and one relayed by a qualified reviewer are both
    #: VERIFIED, and an auditor is entitled to know which. Several constants
    #: here are the second kind: this package's tooling could not retrieve the
    #: FDA guidance PDF, so the figures were supplied at statistical review
    #: together with their section references.
    verified_by: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verification is VerificationStatus.VERIFIED

    def explain(self) -> str:
        """One line a report can print beside the number it used."""
        line = f"{self.value} — {self.citation} [{self.verification}"
        line += f", via {self.verified_by}]" if self.verified_by else "]"
        return f"{line}. {self.note}" if self.note else line


# ------------------------------------------------------------- documents ---
# Declared once so a version cannot drift between the places it is cited.

FDA_STATISTICAL_APPROACHES = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

#: The same document, cited to the sections that carry the highly-variable and
#: narrow-therapeutic-index procedures.
FDA_STATISTICAL_APPROACHES_III_C = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="III.C",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

FDA_STATISTICAL_APPROACHES_APPENDIX_G = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="Appendix G (highly variable drugs)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

FDA_STATISTICAL_APPROACHES_III_B = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="III.B (statistical method for narrow therapeutic index drugs)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

#: Appendix F steps 4 and 5 specifically: the within-subject variability
#: comparison and the three conditions. Cited separately from the appendix at
#: large because the variance-ratio interval is the part most likely to be
#: reached for from somewhere else.
FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5 = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="Appendix F, steps 4-5 (variability comparison and the three conditions)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

FDA_STATISTICAL_APPROACHES_APPENDIX_F = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="Appendix F (narrow therapeutic index drugs)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

FDA_M13A_QA = Citation(
    authority="FDA",
    document="M13A Bioequivalence for Immediate-Release Solid Oral Dosage Forms: Questions and Answers",
    section="Q&A 2.1",
    document_version="FDA guidance for industry",
    url="https://www.fda.gov/media/183189/download",
)

#: The same document, cited to the section carrying the general study-design
#: requirements - including the floor on evaluable subjects.
FDA_STATISTICAL_APPROACHES_II_A = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="II.A (study design)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

#: The same document, cited to the in vitro section. Present for one reason:
#: it contains a SECOND rule using 0.294, with a different inequality. See
#: `spec.FDA_IVPT_NOTE`.
FDA_STATISTICAL_APPROACHES_III_A = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="III.A (in vitro BE and population BE)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)

# ------------------------------------------------------ chains of custody ---
#
# HOW a number was checked, which is not the same as whether. Recorded once
# each so the claim is identical everywhere it is made, and so the two cannot
# be confused when an auditor asks.

#: Read from the cited document. The guidance PDF was supplied and its text
#: extracted and read section by section, so these figures are transcribed from
#: the primary source rather than relayed.
VIA_PRIMARY_DOCUMENT = "primary document, read at the cited section"

#: Relayed by a qualified reviewer together with a section reference, without
#: this tooling having seen the document. A weaker claim, and still VERIFIED.
#: Retained because it remains true of the ICH/FDA M13A Q&A figures, which come
#: from a different document that has NOT been obtained.
VIA_STATISTICAL_REVIEW = "statistical review, with section references"

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
