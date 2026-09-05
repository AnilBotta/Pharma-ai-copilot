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

#: FDA's adoption of the M13A Q&A, now pinned.
#:
#: This carried `document_version="FDA guidance for industry"`, which names a
#: DOCUMENT TYPE and not an issue of one - the same class of non-version as the
#: `"current"` that DOSSIER-004 was about, dressed up well enough to look
#: checked. FDA has published draft and final M13A Q&A material, and "guidance
#: for industry" does not say which is meant.
#:
#: Read at the section: the cover page gives October 2024, and the document
#: carries the FINAL-guidance boilerplate ("This guidance represents the
#: current thinking..."), not the draft form. FDA keeps ICH's question number
#: and puts it in a table of its own, so the identifier is "Table 2, Q&A 2.1".
FDA_M13A_QA = Citation(
    authority="FDA",
    document="M13A Bioequivalence for Immediate-Release Solid Oral Dosage Forms: Questions and Answers",
    section="Table 2, Q&A 2.1 (section II, general principles)",
    document_version="final, October 2024",
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

#: The EMA bioequivalence guideline, now pinned.
#:
#: This citation previously carried `document_version="current"`, which is the
#: exact failure this module opens by warning about: "current" is not a version,
#: it is a promise that someone will remember to check. The document was read
#: for the highly-variable release and is pinned to what its own cover page
#: says.
EMA_BIOEQUIVALENCE = Citation(
    authority="EMA",
    document="Guideline on the Investigation of Bioequivalence",
    section="Narrow therapeutic index drugs",
    document_version="CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010",
)

#: Section 4.1.10, the highly-variable provision. Read at the cited version.
#:
#: WHY A 2010 GUIDELINE IS STILL THE RULE IN 2026
#:
#: ICH M13A came into effect on 25 January 2025 and formally superseded parts
#: of this guideline. It did NOT supersede this part. M13A covers only
#: "BE study considerations and data analysis for a non-replicate study design";
#: highly variable drugs on a replicate design are named as a Tier 3 topic for
#: the future M13C. EMA's own implementation note is explicit that the two
#: documents are to be read in conjunction here — see
#: `EMA_M13A_IMPLEMENTATION`.
EMA_BIOEQUIVALENCE_HVD = Citation(
    authority="EMA",
    document="Guideline on the Investigation of Bioequivalence",
    section="4.1.10 Highly variable drugs or drug products",
    document_version="CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010",
)

#: The document that settles precedence between M13A and the 2010 guideline.
#:
#: Verbatim, under "Implementation": "After 25 January 2025, the EMA Guideline
#: on the investigation of bioequivalence (CPMP/EWP/QWP/1401/98 Rev. 1)
#: pertaining to specific topics not addressed in ICH M13A will continue to
#: apply until such time as they are replaced by new ICH guidance." And: "the
#: requirements of both ICH M13A and the existing EMA Guideline read in
#: conjunction may be applicable to e.g., BE studies with highly variable drugs
#: (replicate design)".
EMA_M13A_IMPLEMENTATION = Citation(
    authority="EMA",
    document=(
        "Considerations regarding the implementation of ICH M13A on "
        "bioequivalence for immediate-release solid oral dosage forms"
    ),
    section="Implementation",
    document_version="EMA/531548/2024, adopted by CHMP 17 February 2025",
)

#: The Q&A that specifies HOW a replicate design is analysed, which the
#: guideline itself does not.
#:
#: Names three candidate models and recommends one: "Method A (guideline
#: recommended)" is an all-fixed-effects ANOVA — `proc glm; model logDATA =
#: sequence subject(sequence) period formulation`. It also gives the reference
#: -only model for sWR, and two worked data sets with published results, which
#: is what makes tier 1B possible for this method.
EMA_PKWP_QA = Citation(
    authority="EMA",
    document=(
        "Questions & Answers: Positions on specific questions addressed to "
        "the Pharmacokinetics Working Party"
    ),
    section="Statistical analysis of bioequivalence studies with a replicate design",
    document_version="EMA/618604/2008 Rev. 13",
)

# ---------------------------------------- the twelve-evaluable-subject rule ---
#
# Q&A 2.1 of the M13A Questions and Answers, in three adoptions, exactly as the
# guideline itself is in three (see `ICH_M13A_BE_CRITERIA` above). The answer is
# word-for-word identical in all three, and each regulator publishes its own
# document with its own reference number and date:
#
#     "The requirement for a minimum of 12 evaluable subjects in pivotal BE
#     studies for a crossover design, or a minimum of 12 per treatment group
#     for a parallel design, is an established practice by regulatory
#     agencies."
#
# TWO WORDS IN THAT SENTENCE DO WORK
#
# "evaluable" - not enrolled, not dosed. `minimums.RegulatoryMinimum.counts`
# carries it for exactly this reason.
#
# "pivotal" - the floor is stated for PIVOTAL BE studies. A pilot relative
# bioavailability study is named two sentences later as an input to sizing the
# pivotal one, so the document plainly does not hold a pilot to twelve. That
# qualifier is NOT currently carried by `minimums.py`; it is recorded as
# DOSSIER-005 rather than fixed here.

ICH_M13A_QA = Citation(
    authority="ICH",
    document=(
        "M13A — Bioequivalence for Immediate-Release Solid Oral Dosage Forms: "
        "Questions and Answers"
    ),
    section="Q&A 2.1 (section 2, general principles)",
    document_version="M13A Q&As, adopted 23 July 2024",
    url="https://database.ich.org/sites/default/files/ICH_M13A_Step4_QAs_2024_0723.pdf",
)

#: EMA's adoption of the same Q&A.
#:
#: Added because the two EMA rows in `minimums.py` were citing ICH's document
#: for a claim keyed to EMA. That is the fallback PR #76 removed for the
#: conventional interval, still in place one module away: an EMA reviewer
#: opens EMA/CHMP/ICH/325575/2024, and a jurisdiction-keyed row should hand
#: them the document their own regulator adopted.
EMA_M13A_QA = Citation(
    authority="EMA",
    document=(
        "ICH M13A Guideline on bioequivalence for immediate-release solid "
        "oral dosage forms: Questions and answers"
    ),
    section="Q&A 2.1 (section 2, general principles)",
    document_version=(
        "EMA/CHMP/ICH/325575/2024, final adoption by CHMP 25 July 2024, "
        "effective 25 January 2025"
    ),
    url="https://www.ema.europa.eu/en/documents/other/ich-m13a-guideline-bioequivalence-immediate-release-solid-oral-dosage-forms-questions-answers_en.pdf",
)

# ------------------------------------------- the conventional BE interval ---
#
# WHY THREE CITATIONS FOR ONE NUMBER
#
# The 80.00-125.00% interval used to be cited as a single placeholder reading
# `authority="ICH / FDA / EMA"`, `document="Conventional bioequivalence
# acceptance interval"`, `document_version="current"` - a rule rather than a
# document, three bodies rather than one place to look, and a version that
# identified no issue. That was tracked as DOSSIER-004 and is what these three
# citations replace.
#
# Three, not one, because the sentence appears in three DOCUMENTS. ICH M13A is
# the harmonised text; FDA and EMA each adopted it as their own instrument,
# with their own reference number, their own effective date and - in FDA's
# case - their own section numbering. A reader holding an FDA submission opens
# the FDA guidance, and telling them to open an ICH file would be handing them
# a document their reviewer does not administer.
#
# The wording is identical in all three, which is why one shared object was
# tempting. Identical wording is not the same as one document.
#
# WHAT THE SECTION ACTUALLY COVERS, WHICH IS NARROWER THAN "BIOEQUIVALENCE"
#
# 2.2.4 sits inside 2.2, "Data Analysis for NON-REPLICATE Study Design", and
# M13A's own scope (1.3) defers highly variable drugs and narrow therapeutic
# index drugs to the future M13C:
#
#     "The third guideline in the series, M13C, will include data analysis and
#     BE assessment for 1) highly variable drugs, 2) drugs with narrow
#     therapeutic index, and 3) complex BE study design ..."
#
# So this citation supports ordinary average BE on a non-replicate design -
# 2x2 crossover and parallel, both covered by 2.2.3 - and supports NOTHING
# about FDA RSABE, FDA NTI, EMA NTI or EMA ABEL. Those keep the citations they
# already had, which name the documents that do state them.
#
# The sentence, verbatim and identical in all three documents:
#
#     "The 90% confidence interval for the geometric mean ratio of these PK
#     parameters used to establish BE should lie within a range of
#     80.00 - 125.00%."

#: The harmonised text. Cited where no jurisdiction has been chosen yet -
#: `dossier.capabilities.AVERAGE_BE_2X2` carries `jurisdiction=None` because
#: the procedure is the same one in both regions.
ICH_M13A_BE_CRITERIA = Citation(
    authority="ICH",
    document="M13A — Bioequivalence for Immediate-Release Solid Oral Dosage Forms",
    section="2.2.4 Bioequivalence Criteria (within 2.2, non-replicate designs)",
    document_version="Final version, adopted 23 July 2024",
    url="https://database.ich.org/sites/default/files/ICH_M13A_Step4_Final_Guideline_2024_0723.pdf",
)

#: FDA's adoption. FDA renumbers the ICH headings and prints the ICH number in
#: parentheses, so the section identifier is II.B.4 and not 2.2.4 - which is
#: exactly the kind of difference a shared citation would have flattened.
FDA_M13A_BE_CRITERIA = Citation(
    authority="FDA",
    document=(
        "M13A Bioequivalence for Immediate-Release Solid Oral Dosage Forms — "
        "Guidance for Industry"
    ),
    section="II.B.4 Bioequivalence Criteria (2.2.4)",
    document_version="final, October 2024",
    url="https://www.fda.gov/media/165049/download",
)

#: EMA's adoption, which keeps ICH's numbering and adds its own reference
#: number and coming-into-effect date. Read from the Step 5 cover page.
EMA_M13A_BE_CRITERIA = Citation(
    authority="EMA",
    document=(
        "ICH M13A Guideline on bioequivalence for immediate-release solid "
        "oral dosage forms"
    ),
    section="2.2.4 Bioequivalence criteria (within 2.2, non-replicate designs)",
    document_version=(
        "EMA/CHMP/ICH/953493/2022, Step 5, final adoption by CHMP "
        "25 July 2024, effective 25 January 2025"
    ),
    url="https://www.ema.europa.eu/en/documents/scientific-guideline/ich-m13a-guideline-bioequivalence-immediaterelease-solid-oral-dosage-forms-step-5_en.pdf",
)

#: A stand-in for values this package computes rather than cites.
DERIVED_INTERNALLY = Citation(
    authority="be-stats",
    document="derived, not transcribed",
)
