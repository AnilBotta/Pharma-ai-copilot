"""What was searched for tier-1B evidence, and what each source turned out to be.

WHY A REGISTRY OF SEARCHES AND NOT ONLY OF FINDINGS

`dossier.evidence` records evidence this package HAS. `dossier.findings`
records questions that remain open. Neither records the work of looking, and
that gap has a cost: DOSSIER-003 has said "FDA has published no worked
numerical example" since the dossier was created, and nothing anywhere said
which documents had been opened to support that claim. A negative finding that
cannot be audited is an assertion.

So a search is recorded like any other evidence: the document, the version, the
sections read, the verdict, and - where a candidate was rejected - the reason
it was rejected. A reader who disagrees with a verdict can open the same
document and argue with it.

THE VERDICT IS ABOUT ADMISSIBILITY, NOT ABOUT QUALITY

`NO_NUMERICAL_OUTPUT` is not a criticism of a guidance. FDA's Statistical
Approaches publishes the SAS statements for the analyses it requires and
publishes no dataset to run them on; that is a deliberate editorial choice and
it makes the document tier-1A material rather than tier-1B. The verdict says
which kind of evidence a document can supply, and nothing else.

REJECTED IS RECORDED IN FULL, BECAUSE A NEAR MISS IS THE DANGEROUS CASE

An obviously irrelevant document is rejected once and forgotten. A document
that is *almost* admissible gets found again by the next person, who has to
redo the reasoning - and may reach a more convenient answer. So a rejected
candidate carries what it would have established, and exactly which condition
it fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SearchVerdict(StrEnum):
    """What a document turned out to be able to supply."""

    #: States a procedure, an equation or program statements, and publishes no
    #: numerical result to reproduce. Tier-1A material.
    NO_NUMERICAL_OUTPUT = "no_numerical_output"
    #: Publishes numbers, for a design or a method other than the one sought.
    NUMBERS_FOR_ANOTHER_METHOD = "numbers_for_another_method"
    #: Publishes numbers for the method sought, and is not admissible as
    #: evidence for the capability sought. The reason is always stated.
    NUMBERS_OUT_OF_SCOPE = "numbers_out_of_scope"
    #: Publishes numbers for the method sought, admissible, and adopted.
    ADOPTED = "adopted"
    #: A template or a presentation format, carrying placeholders rather than
    #: results.
    TEMPLATE_ONLY = "template_only"


@dataclass(frozen=True, slots=True)
class SearchedSource:
    """One document, opened and read, with what it turned out to hold."""

    #: What the search was for. Free text, because a search is scoped by a
    #: question rather than by a capability id.
    sought: str
    authority: str
    document: str
    #: The issue actually read. Same discipline as `provenance.Citation`: a
    #: document without a version is not a document.
    document_version: str
    #: The sections opened. Not the whole document unless it is short.
    sections_read: str
    verdict: SearchVerdict
    #: What was found, in the document's own terms.
    found: str
    #: For a rejected candidate: which condition it fails, and why that
    #: condition is not negotiable. Empty for a verdict that needs no defence.
    rejected_because: str = ""
    url: str = ""


#: The tier-1B search for ORDINARY (non-replicate) average bioequivalence.
#:
#: The question: has any regulator published a worked numerical example of an
#: ordinary 2x2 crossover or parallel average-BE analysis, with the resulting
#: point estimate and confidence interval, such that `AVERAGE_BE_2X2` could
#: hold tier-1B evidence?
ORDINARY_ABE_TIER_1B_SEARCH: tuple[SearchedSource, ...] = (
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="FDA",
        document="Statistical Approaches to Establishing Bioequivalence",
        document_version="final, May 2026",
        sections_read=(
            "Contents; II.A; III; Appendices A-G, which are the whole of the "
            "document's worked material."
        ),
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Appendix C gives SAS PROC MIXED statements for replicate average "
            "BE; F and G give the NTI and highly-variable procedures step by "
            "step. Every appendix states a method. None publishes a dataset, "
            "and none publishes an output to reproduce."
        ),
        url="https://www.fda.gov/media/163638/download",
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="FDA",
        document=(
            "M13A Bioequivalence for Immediate-Release Solid Oral Dosage "
            "Forms — Guidance for Industry"
        ),
        document_version="final, October 2024",
        sections_read="II.B (data analysis for non-replicate designs), II.B.4.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "States the 80.00-125.00% criterion and the analysis to apply. No "
            "dataset and no worked result."
        ),
        url="https://www.fda.gov/media/165049/download",
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="FDA",
        document=(
            "M13A Bioequivalence for Immediate-Release Solid Oral Dosage "
            "Forms: Questions and Answers — Guidance for Industry"
        ),
        document_version="final, October 2024",
        sections_read="Table 2 (section II), all questions.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Q&A 2.1 gives the twelve-evaluable-subject floor. The Q&As "
            "clarify procedure and publish no analysis output."
        ),
        url="https://www.fda.gov/media/183189/download",
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="ICH",
        document="M13A — Bioequivalence for Immediate-Release Solid Oral Dosage Forms",
        document_version="Final version, adopted 23 July 2024",
        sections_read="2.1.3, 2.2 in full, 2.2.4, 5 (Glossary).",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "The harmonised text of the same procedure. No annexed data and "
            "no worked example anywhere in the guideline or its Q&As."
        ),
        url=(
            "https://database.ich.org/sites/default/files/"
            "ICH_M13A_Step4_Final_Guideline_2024_0723.pdf"
        ),
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="EMA",
        document="Guideline on the Investigation of Bioequivalence",
        document_version="CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010",
        sections_read="4.1.8, 4.1.10, Appendices I-III.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "States the analysis and the acceptance interval. Searching the "
            "extracted text for a subject-level data table returns nothing: "
            "the guideline annexes no data."
        ),
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="EMA",
        document=(
            "Questions & Answers: Positions on specific questions addressed "
            "to the Pharmacokinetics Working Party"
        ),
        document_version="EMA/618604/2008 Rev. 13",
        sections_read=(
            "Sections 1-3, the statistical analysis question, and the annexed "
            "Data set I and Data set II."
        ),
        verdict=SearchVerdict.NUMBERS_FOR_ANOTHER_METHOD,
        found=(
            "THE CLOSEST EMA COMES, and it is a replicate design. Data set I "
            "is four-period unbalanced and Data set II three-period balanced; "
            "both are published WITH results and both are already reproduced "
            "as tier-1B evidence for EMA_REPLICATE_METHOD_A. The document "
            "says in terms that the fixed-versus-random question 'is not "
            "important for the standard two period, two sequence (2x2) "
            "crossover trial' - and then publishes no 2x2 example, because "
            "its subject is replicate designs."
        ),
        rejected_because=(
            "A replicate design routed through an ordinary ANOVA is a "
            "different model from an ordinary 2x2 analysis; the package "
            "already separates them into different capabilities for exactly "
            "this reason. Reusing this evidence for AVERAGE_BE_2X2 would "
            "claim a design the data does not contain."
        ),
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="EMA",
        document=(
            "Appendix IV of the Guideline on the Investigation on "
            "Bioequivalence: presentation of biopharmaceutical and "
            "bioanalytical data in module 2.7.1"
        ),
        document_version="EMA/CHMP/600958/2010/Corr.",
        sections_read="All ten pages of tables.",
        verdict=SearchVerdict.TEMPLATE_ONLY,
        found=(
            "Blank presentation tables for an applicant to complete. The "
            "strengths read 'XX mg'. There are no results here to reproduce."
        ),
    ),
    SearchedSource(
        sought="ordinary non-replicate average BE, published numerical output",
        authority="FDA",
        document=(
            "Supplemental Examples For Illustrating Statistical Concepts "
            "Described in the VICH In Vivo Bioequivalence Draft Guidance GL52"
        ),
        document_version="FDA/CVM, undated; supplements VICH GL52 in draft",
        sections_read=(
            "'Bioequivalence data statistical analysis' in full: Table 1 (the "
            "dataset), Table 2 (tests of fixed effects), Table 3 (difference "
            "and confidence interval), and the text deriving the BE bounds."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "THE ONLY FDA-PUBLISHED ORDINARY 2x2 WORKED EXAMPLE FOUND. A "
            "twelve-subject, two-sequence, two-period crossover with the "
            "subject-level values printed, analysed on the natural-log scale, "
            "published with denominator df 10, SE 0.02991, 90% limits "
            "-0.0346 and 0.0738, and the bounds exp(-0.0346)=0.97 and "
            "exp(0.0738)=1.08. be-stats reproduces the limits and the df "
            "through its production `analyse_crossover` path - see "
            "tests/validation/test_fda_cvm_vich_gl52_candidate.py, which "
            "records the comparison rather than claiming it as evidence."
        ),
        rejected_because=(
            "Three independent reasons, any one of which is sufficient. "
            "(1) SCOPE: it supplements VICH GL52, a VETERINARY guidance, and "
            "its subjects are animals; AVERAGE_BE_2X2 is cited to ICH M13A "
            "2.2.4, whose scope is human immediate-release solid oral dosage "
            "forms. Applying a document outside its scope is the failure this "
            "package exists to prevent. "
            "(2) STATUS: it supplements a DRAFT guidance and carries no issue "
            "date of its own, so it cannot be pinned to the standard "
            "`citations.is_pinned` requires. "
            "(3) INTERNAL CONSISTENCY: Table 3 prints the difference as "
            "0.1958, which does not lie between its own published 90% limits "
            "of -0.0346 and 0.0738. The limits and the standard error are "
            "mutually consistent with a difference of 0.01958, so the printed "
            "figure carries a misplaced decimal point. Adopting the table "
            "would mean deciding which of its published numbers is "
            "authoritative, which is inferring an expected value rather than "
            "reproducing one."
        ),
        url="https://www.fda.gov/media/89845/download",
    ),
)


def sources_with_verdict(verdict: SearchVerdict) -> list[SearchedSource]:
    return [s for s in ORDINARY_ABE_TIER_1B_SEARCH if s.verdict is verdict]


def adopted_sources() -> list[SearchedSource]:
    """Anything this search actually turned into evidence. Empty is an answer."""
    return sources_with_verdict(SearchVerdict.ADOPTED)


def rejected_candidates() -> list[SearchedSource]:
    """Documents that published the right kind of number and were not used."""
    return [
        s
        for s in ORDINARY_ABE_TIER_1B_SEARCH
        if s.verdict
        in (
            SearchVerdict.NUMBERS_OUT_OF_SCOPE,
            SearchVerdict.NUMBERS_FOR_ANOTHER_METHOD,
        )
    ]
