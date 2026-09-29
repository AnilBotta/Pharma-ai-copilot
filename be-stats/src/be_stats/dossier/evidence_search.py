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
            "CVM GFI #224 (Supplement to VICH GL52) — Supplemental Examples "
            "For Illustrating Statistical Concepts Described in the VICH In "
            "Vivo Bioequivalence Guidance GL52"
        ),
        # A CORRECTION, AND WHERE THE ERROR CAME FROM
        #
        # This record first read "FDA/CVM, undated; supplements VICH GL52 in
        # draft", and a rejection ground was built on it. Both were wrong.
        #
        # The PDF's own first line reads "... VICH In Vivo Bioequivalence
        # DRAFT Guidance GL52", and that was taken to describe the supplement.
        # It does not: it names the state GL52 was in when these examples were
        # written. The supplement itself is a final FDA guidance, and FDA's
        # guidance page says so in a field of its own - "Final", September
        # 2014, docket FDA-2014-D-1352. FDA's Guidance-by-Number listing gives
        # 24 September 2014; the month is used here because that is what the
        # guidance page itself shows, and an over-specific citation looks
        # checked when it is not.
        #
        # The lesson is the one the citation policy already encodes: a
        # document's status is read from the issuing page's status field, not
        # inferred from a phrase inside its title.
        document_version="CVM GFI #224, final, September 2014",
        sections_read=(
            "'Bioequivalence data statistical analysis' in full: Table 1 (the "
            "dataset), Table 2 (tests of fixed effects), Table 3 (difference "
            "and confidence interval), and the text deriving the BE bounds. "
            "Status and date read from FDA's guidance page for GFI #224, not "
            "from the PDF, which carries neither."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "THE ONLY FDA-PUBLISHED ORDINARY 2x2 WORKED EXAMPLE FOUND, and a "
            "FINAL guidance: FDA's guidance page carries the status field "
            "'Final' with September 2014 and docket FDA-2014-D-1352, and "
            "FDA's Guidance-by-Number listing gives 24 September 2014. A "
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
            "Two independent reasons, either of which is sufficient. "
            "(1) SCOPE: it is FDA Center for Veterinary Medicine guidance "
            "supplementing VICH GL52, and its subjects are animals; "
            "AVERAGE_BE_2X2 is cited to ICH M13A 2.2.4, whose scope is human "
            "immediate-release solid oral dosage forms. Applying a document "
            "outside its scope is the failure this package exists to prevent. "
            "(2) INTERNAL CONSISTENCY: Table 3 prints the difference as "
            "0.1958, which does not lie between its own published 90% limits "
            "of -0.0346 and 0.0738. The limits and the standard error are "
            "mutually consistent with a difference of 0.01958, so the printed "
            "figure carries a misplaced decimal point. Adopting the table "
            "would mean deciding which of its published numbers is "
            "authoritative, which is inferring an expected value rather than "
            "reproducing one. "
            "NOT a reason, and recorded here because this record asserted it "
            "and was wrong: the supplement is NOT a draft and NOT undated. It "
            "is final, September 2014, and could be pinned. Removing a false "
            "ground makes the rejection rest on the two that survive scrutiny."
        ),
        url="https://www.fda.gov/media/89845/download",
    ),
)


#: The tier-1B search for FDA's NARROW THERAPEUTIC INDEX procedure, Appendix F.
#:
#: The question: has FDA published a worked numerical example of the NTI
#: procedure - a dataset carried through sWR, sWT, the reference-scaled bound,
#: the unscaled interval and the variance-ratio interval to a stated outcome -
#: such that `FDA_NTI_RSABE` could hold tier-1B evidence?
#:
#: The answer is no, and every document below was read from its own extracted
#: text rather than from a summary of it. The recurring shape is instructive:
#: FDA states this procedure in four places and the text of each is traceable
#: to the one before - the 2012 warfarin PSG carried the method and its SAS, the
#: 2021 draft ANDA guidance moved it into an appendix, and the May 2026 final
#: guidances point to Statistical Approaches. Four statements of one algorithm
#: are tier-1A material four times over, and none of them is a number to
#: reproduce.
FDA_NTI_TIER_1B_SEARCH: tuple[SearchedSource, ...] = (
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document="Statistical Approaches to Establishing Bioequivalence",
        document_version="final, May 2026",
        sections_read=(
            "III.B (statistical method for NTI drugs) and Appendix F steps 1-5 "
            "with its SAS example, read in full from the extracted text of "
            "pages 22-23 and 44-48."
        ),
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "The governing statement of the procedure: a fully replicate "
            "crossover; sigma_W0 = 0.10 and Delta = 1/0.9 'approximately "
            "=1.11111'; criterion (a) the 95% upper bound <= 0; (b) 'Regular "
            "unscaled BE limits of 80.00%-125.00% should be passed'; (c) the "
            "upper limit of the 90% equal-tails interval for sigma_WT/sigma_WR "
            "<= 2.500, with the F quantiles defined by right-tail probability "
            "and alpha = 0.1. The SAS assumes datasets TEST and REF 'have "
            "already been created' and prints no data and no output."
        ),
        url="https://www.fda.gov/media/163638/download",
    ),
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document=(
            "Bioequivalence Studies With Pharmacokinetic Endpoints for Drugs "
            "Submitted Under an ANDA — Guidance for Industry"
        ),
        document_version="final, May 2026",
        sections_read=(
            "Full extracted text (35 pages) searched for the NTI terms, the "
            "Appendix F constants and any numeric table; every hit read in "
            "context, including III.A.4 (study designs) and the data analysis "
            "paragraph on narrow therapeutic index drugs."
        ),
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Recommends a fully replicate design for NTI drugs 'where "
            "within-subject variability for both the reference standard and "
            "test product can be computed', and refers the statistical analysis "
            "to Statistical Approaches (May 2026). No dataset, no worked "
            "result, and no clustered numeric table anywhere in the text."
        ),
        url="https://www.fda.gov/media/192774/download",
    ),
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document="Draft Guidance on Warfarin Sodium (product-specific guidance)",
        document_version="draft, Recommended December 2012",
        sections_read="All seven pages of extracted text, including the full statistical method and SAS.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "THE ORIGIN OF THE PROCEDURE'S WORDING: the full method and SAS "
            "later carried into Statistical Approaches, for a fully replicated "
            "4-way crossover. Notably it writes the constant as '1.11111 "
            "(=1/0.9, the upper BE limit)', where the final May 2026 guidance "
            "states 1/0.9 'approximately =1.11111' - the draft PSG leads with "
            "the rounded literal, the governing final guidance with the ratio, "
            "which is the one this package decides with. No data and no output."
        ),
        url=(
            "https://www.accessdata.fda.gov/drugsatfda_docs/psg/"
            "Warfarin_Sodium_tab_09218_RC12-12.pdf"
        ),
    ),
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document="Draft Guidance on Tacrolimus (product-specific guidance, PSG_210115)",
        document_version="draft, Recommended March 2020; Revised August 2022 and May 2026",
        sections_read="All three pages of extracted text.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Classifies tacrolimus as NTI with the evidence for that "
            "classification, requires a fully replicate crossover 'to scale "
            "bioequivalence limits' and 'compare test product and RLD "
            "within-subject variability', and defers the method to the ANDA PK "
            "guidance. No data and no output."
        ),
        url="https://www.accessdata.fda.gov/drugsatfda_docs/psg/PSG_210115.pdf",
    ),
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document=(
            "Bioequivalence Studies with Pharmacokinetic Endpoints for Drugs "
            "Submitted Under an ANDA — SBIA webinar slides (L. Zhang, N. Tampal, "
            "Office of Generic Drugs)"
        ),
        document_version="presentation, 24 February 2022",
        sections_read="All 44 slides of extracted text.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Describes the August 2021 revised draft ANDA guidance adding "
            "Appendix C on reference-scaled BE for NTI drugs, 'previously "
            "included in PSG for ... warfarin sodium oral tablets' - which is "
            "the lineage recorded above. A presentation of guidance history "
            "with no worked example."
        ),
        url="https://www.fda.gov/media/164681/download",
    ),
    SearchedSource(
        sought="FDA narrow therapeutic index procedure (Appendix F), published numerical output",
        authority="FDA",
        document=(
            "FDA Drug Topics: Understanding Generic Narrow Therapeutic Index "
            "Drugs — presentation slides (W. Jiang, Office of Generic Drugs)"
        ),
        # No issue date is printed in the document, and none is inferred. The
        # GL52 correction in ORDINARY_ABE_TIER_1B_SEARCH is the reason: a date
        # read from somewhere other than the issuing record looks checked when
        # it is not.
        document_version="presentation; no issue date printed in the document",
        sections_read=(
            "All 43 slides of extracted text; slide 24 ('Reference Scaled BE "
            "Limits for NTI Drugs') read against the Appendix F constants."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "THE ONLY NTI NUMBERS FDA MATERIAL PRINTS. Slide 24 tabulates the "
            "reference-scaled BE limits implied by Delta = 1/0.9 and sigma_W0 "
            "= 0.10 at CVwR 5, 10, 15 and 20%, and '>21.42' where they reach "
            "80.00-125.00%. Seven of the eight printed limits and the 21.42 "
            "crossover reproduce to the two decimals printed - see "
            "tests/validation/test_fda_nti_drug_topics_candidate.py, which "
            "records the comparison rather than claiming it as evidence."
        ),
        rejected_because=(
            "Three independent reasons, any one sufficient. "
            "(1) STANDING: a speaker presentation carrying the disclaimer that "
            "its views 'are those of the speaker and not necessarily those of "
            "the Food and Drug Administration'. It is not guidance. "
            "(2) WHAT THE NUMBERS ARE: a function of two regulatory constants "
            "and nothing else - no dataset, no sWR estimate, no Howe bound, no "
            "criterion (b), no criterion (c). Reproducing them re-checks theta, "
            "which is already tier-1A material from the guidance itself; it "
            "cannot reproduce a single step of the procedure applied to data. "
            "Nor can it even adjudicate the normative Delta: 1/0.9 and 1.11111 "
            "give the same table at the printed precision. "
            "(3) INTERNAL CONSISTENCY: the CVwR 15% lower limit is printed "
            "85.35, while the limits are reciprocal by construction and the "
            "printed upper limit 117.02 implies 85.46 - which is also what the "
            "constants give. Adopting the table would mean deciding which of "
            "its printed numbers to believe."
        ),
        url="https://www.fda.gov/media/162779/download",
    ),
)


#: The END-TO-END tier-1B search for EMA's highly variable procedure, ABEL.
#:
#: The question: has EMA published ONE scenario carried all the way through -
#: reference variability, eligibility, widened limits, the Method A 90% CI, the
#: GMR constraint - to a stated bioequivalence verdict, such that
#: `EMA_HVD_ABEL` could hold method-level tier-1B evidence?
#:
#: The answer is no. EMA publishes three of the components with numbers, and
#: this package already holds them as tier-1B evidence for those components. It
#: publishes them in different places, for different data, and never joins
#: them. Joining them here - taking Data set I's CVwR, computing the limits it
#: would imply, and checking EMA's Method A interval against them - would be
#: this package writing an end-to-end example and then citing EMA for it.
EMA_HVD_ABEL_END_TO_END_SEARCH: tuple[SearchedSource, ...] = (
    SearchedSource(
        sought="EMA ABEL end to end: one scenario through variability, limits, Method A CI, GMR and a stated verdict",
        authority="EMA",
        document="Guideline on the Investigation of Bioequivalence (CPMP/EWP/QWP/1401/98 Rev. 1)",
        document_version="Rev. 1, effective 1 August 2010",
        sections_read=(
            "4.1.8 (acceptance limits and statistical analysis), 4.1.9 and "
            "4.1.10 in full, read from the extracted text of pages 15-17."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "The rule: widening only for HVDP 'for which a wider difference in "
            "Cmax is considered clinically irrelevant based on a sound clinical "
            "justification', a replicate design demonstrating CVwR '>30%', the "
            "request 'prospectively specified in the protocol', [U, L] = "
            "exp[+/- k.sWR] with k = 0.760, a maximum of 69.84 - 143.19%, the "
            "GMR within 80.00-125.00%, and no widening for AUC. One table of "
            "limits at CVwR 30, 35, 40, 45 and >=50%."
        ),
        rejected_because=(
            "Component numbers only. The table is a function of CVwR and k: no "
            "dataset, no interval, no GMR, no verdict. It is already tier-1B "
            "evidence for EMA_ABEL_LIMIT_CALCULATION (EMA-ABEL-LIMITS-TABLE), "
            "which is what it can support."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "guideline-investigation-bioequivalence-rev1_en.pdf"
        ),
    ),
    SearchedSource(
        sought="EMA ABEL end to end: one scenario through variability, limits, Method A CI, GMR and a stated verdict",
        authority="EMA",
        document=(
            "Questions & Answers: Positions on specific questions addressed to "
            "the Pharmacokinetics Working Party (EMA/618604/2008)"
        ),
        document_version="Rev. 13, 19 November 2015",
        sections_read=(
            "The replicate-design analysis section (Methods A, B and C; results "
            "for Data sets I and II; 3.4 estimating the within subject "
            "variability; discussion and conclusion) and its annex, read from "
            "pages 16-19; question 4 (widening Cmax for clopidogrel); question "
            "19 (3-period replicate designs); the orally inhaled products "
            "answer on scaled limits."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "Data set I (4-period, unbalanced) and Data set II (3-period): "
            "Method A point estimates and 90% intervals, 115.66 (107.11, "
            "124.89) and 102.26 (97.32, 107.46), and reference CVwR 47.0% and "
            "11.2% by the reference-only model - with the raw data. These are "
            "tier-1B evidence for EMA_REPLICATE_METHOD_A and "
            "EMA_HVD_REFERENCE_VARIABILITY. Question 4 is the only passage "
            "applying the widening rule to a product, and it concludes 'the "
            "widening of 90% confidence intervals for Cmax is not recommended' "
            "for clopidogrel, with no numbers."
        ),
        rejected_because=(
            "The data sets illustrate MODELS, not the ABEL decision. EMA states "
            "no widened limits for either, no clinical justification or "
            "protocol prespecification, and no bioequivalence conclusion - "
            "Data set I's CVwR of 47.0% is never taken through 4.1.10. Stitching "
            "its CVwR, the limits it would imply and its published interval "
            "into a PASS would be a verdict this package wrote, attributed to "
            "EMA."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "questions-and-answers-positions-specific-questions-addressed-"
            "pharmacokinetics-working-party_en.pdf"
        ),
    ),
    SearchedSource(
        sought="EMA ABEL end to end: one scenario through variability, limits, Method A CI, GMR and a stated verdict",
        authority="EMA",
        document=(
            "Considerations regarding the implementation of ICH M13A on "
            "bioequivalence for immediate-release solid oral dosage forms "
            "(EMA/531548/2024)"
        ),
        document_version="adopted by CHMP 17 February 2025",
        sections_read="All three pages.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Precedence only: the 2010 guideline 'pertaining to specific topics "
            "not addressed in ICH M13A will continue to apply', naming 'BE "
            "studies with highly variable drugs (replicate design)'. No numbers."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "considerations-regarding-implementation-ich-m13a-bioequivalence-"
            "immediate-release-solid-oral-dosage-forms_en.pdf"
        ),
    ),
    SearchedSource(
        sought="EMA ABEL end to end: one scenario through variability, limits, Method A CI, GMR and a stated verdict",
        authority="EMA",
        document=(
            "ICH M13A Guideline on bioequivalence for immediate-release solid "
            "oral dosage forms - Questions and answers (EMA/CHMP/ICH/325575/2024)"
        ),
        document_version="final adoption by CHMP 25 July 2024",
        sections_read=(
            "Full extracted text (17 pages) searched for replicate, highly "
            "variable and widening terms; none is present."
        ),
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "Addresses non-replicate design and analysis only, consistent with "
            "M13A's scope. Nothing on highly variable drugs or widened limits."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/other/ich-m13a-guideline-"
            "bioequivalence-immediate-release-solid-oral-dosage-forms-"
            "questions-answers_en.pdf"
        ),
    ),
)


#: The tier-1B search for EMA's NARROW THERAPEUTIC INDEX procedure.
#:
#: The question: has EMA published a worked numerical example of a study
#: decided under 4.1.9 - a product classified as an NTID, an endpoint, a 90%
#: confidence interval and a stated bioequivalence verdict against
#: 90.00-111.11% - such that `EMA_NTI_NARROW_ABE` could hold method-level
#: tier-1B evidence?
#:
#: The answer is no, and the shape of the "no" matters. EMA publishes the RULE
#: in the guideline and publishes PER-PRODUCT APPLICATIONS of the rule in the
#: PKWP Q&A - which interval applies to ciclosporin, and to tacrolimus - and
#: publishes no study, no geometric mean ratio and no interval anywhere. An
#: interval that a regulator says SHOULD be used is tier-1A rule evidence. It
#: becomes tier-1B only when there is a number the engine can be run against
#: and a verdict the regulator itself stated, and there is none.
#:
#: NOT SEARCHED, and recorded as such rather than as absent: the individual
#: EMA product-specific bioequivalence guidance documents, and EPAR assessment
#: reports for NTI generics. Those are the places a published GMR and interval
#: would most plausibly appear. They were not retrieved in this pull request,
#: so nothing here claims they hold nothing - only that they were not read.
EMA_NTI_TIER_1B_SEARCH: tuple[SearchedSource, ...] = (
    SearchedSource(
        sought=(
            "EMA NTI end to end: one product classified, one endpoint, a 90% "
            "CI and a stated verdict against 90.00-111.11%"
        ),
        authority="EMA",
        document=(
            "Guideline on the Investigation of Bioequivalence "
            "(CPMP/EWP/QWP/1401/98 Rev. 1)"
        ),
        document_version="Rev. 1, effective 1 August 2010",
        sections_read=(
            "4.1.8 (parameters to be analysed and acceptance limits) and 4.1.9 "
            "(narrow therapeutic index drugs) in full, read from the extracted "
            "text of pages 15-16; Appendix III's two cross-references to 4.1.9."
        ),
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "The whole rule, in three sentences: 'the acceptance interval for "
            "AUC should be tightened to 90.00-111.11%'; 'Where Cmax is of "
            "particular importance for safety, efficacy or drug level "
            "monitoring the 90.00-111.11% acceptance interval should also be "
            "applied for this parameter'; and 'it is not possible to define a "
            "set of criteria to categorise drugs as narrow therapeutic index "
            "drugs (NTIDs) and it must be decided case by case ... based on "
            "clinical considerations'. No dataset, no interval, no verdict."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "guideline-investigation-bioequivalence-rev1_en.pdf"
        ),
    ),
    SearchedSource(
        sought=(
            "EMA NTI end to end: one product classified, one endpoint, a 90% "
            "CI and a stated verdict against 90.00-111.11%"
        ),
        authority="EMA",
        document=(
            "Questions & Answers: Positions on specific questions addressed to "
            "the Pharmacokinetics Working Party (EMA/618604/2008)"
        ),
        document_version="Rev. 13",
        sections_read=(
            "Question 3 (acceptance criteria for losartan), question 4 "
            "(bioequivalence assessment of generics for tacrolimus, pages "
            "9-10) and question 5 (requirements for demonstration of "
            "bioequivalence for ciclosporine generics, page 11), read in full."
        ),
        verdict=SearchVerdict.NUMBERS_OUT_OF_SCOPE,
        found=(
            "The two per-product applications of 4.1.9, decided in opposite "
            "directions for Cmax. Ciclosporin: 'As EWP has defined ciclosporin "
            "to be a NTID, for which both AUC and Cmax are important for "
            "safety and efficacy, a narrowed (90.00-111.11%) acceptance range "
            "should be applied for both AUC and Cmax.' Tacrolimus, with its "
            "reasoning - 'peak whole blood levels do not seem to be critical "
            "for either safety or efficacy' - concluding '[90-111%] for AUC "
            "and [80-125%] for Cmax'."
        ),
        rejected_because=(
            "Limits, not results. Both answers state which interval a future "
            "study must meet; neither reports a study, a geometric mean ratio, "
            "a confidence interval or a bioequivalence decision. There is "
            "nothing here to run the engine against, which is the whole of "
            "what tier 1B requires. They are adopted as tier-1A applicability "
            "evidence instead (EMA-NTI-CMAX-IMPORTANCE-001)."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "questions-answers-positions-specific-questions-addressed-"
            "pharmacokinetics-working-party_en.pdf"
        ),
    ),
    SearchedSource(
        sought=(
            "whether ICH M13A supplies the NTI acceptance criteria, worked or "
            "otherwise, after 25 January 2025"
        ),
        authority="ICH",
        document=(
            "M13A Guideline on bioequivalence for immediate-release solid oral "
            "dosage forms (EMA/CHMP/ICH/953493/2022)"
        ),
        document_version="Step 5",
        sections_read=(
            "Section 1 (introduction and the M13 series scope), 2.2.3 "
            "(statistical analysis) and 2.2.4 (bioequivalence criteria)."
        ),
        verdict=SearchVerdict.NUMBERS_FOR_ANOTHER_METHOD,
        found=(
            "2.2.4 states 80.00-125.00% and nothing about narrow therapeutic "
            "index drugs. Section 1 defers them explicitly: 'The third "
            "guideline in the series, M13C, will include data analysis and BE "
            "assessment for 1) highly variable drugs, 2) drugs with narrow "
            "therapeutic index'. 2.2.3.2 gives the analysis model this engine "
            "uses for the non-replicate crossover."
        ),
        rejected_because=(
            "M13A supplies the MODEL and the conventional criteria, not the "
            "NTI ones. Reading its 80.00-125.00% as the EMA NTI interval would "
            "invert the rule 4.1.9 states."
        ),
    ),
    SearchedSource(
        sought=(
            "which document governs EMA NTI acceptance criteria after ICH "
            "M13A came into effect"
        ),
        authority="EMA",
        document=(
            "Considerations regarding the implementation of ICH M13A on "
            "bioequivalence for immediate-release solid oral dosage forms"
        ),
        document_version="EMA/531548/2024, adopted by CHMP 17 February 2025",
        sections_read="Background and Implementation, in full - the document is three pages.",
        verdict=SearchVerdict.NO_NUMERICAL_OUTPUT,
        found=(
            "That M13A came into effect on 25 January 2025 'formally "
            "superseding applicable parts of' the EMA guideline; that the EMA "
            "guideline 'pertaining to specific topics not addressed in ICH "
            "M13A will continue to apply'; and that 'the requirements of both "
            "ICH M13A and the existing EMA Guideline read in conjunction may "
            "be applicable to e.g., ... drugs with narrow therapeutic index'. "
            "It also puts the existing Q&As under the same read-in-conjunction "
            "rule pending EMA's review."
        ),
        rejected_because=(
            "Precedence, not numbers. It settles WHICH documents govern - both "
            "of them, each for what it covers - and publishes no result."
        ),
        url=(
            "https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "considerations-regarding-implementation-ich-m13a-bioequivalence-"
            "immediate-release-solid-oral-dosage-forms_en.pdf"
        ),
    ),
)


def sources_with_verdict(
    verdict: SearchVerdict,
    search: tuple[SearchedSource, ...] = ORDINARY_ABE_TIER_1B_SEARCH,
) -> list[SearchedSource]:
    """Sources in one search with one verdict.

    `search` defaults to the ordinary-ABE registry, which is what every caller
    meant before the NTI registry existed; a second search is asked for by name
    rather than merged into the first, because the two answer different
    questions and a combined "nothing adoptable" would hide which one found what.
    """
    return [s for s in search if s.verdict is verdict]


def adopted_sources(
    search: tuple[SearchedSource, ...] = ORDINARY_ABE_TIER_1B_SEARCH,
) -> list[SearchedSource]:
    """Anything this search actually turned into evidence. Empty is an answer."""
    return sources_with_verdict(SearchVerdict.ADOPTED, search)


def rejected_candidates(
    search: tuple[SearchedSource, ...] = ORDINARY_ABE_TIER_1B_SEARCH,
) -> list[SearchedSource]:
    """Documents that published the right kind of number and were not used."""
    return [
        s
        for s in search
        if s.verdict
        in (
            SearchVerdict.NUMBERS_OUT_OF_SCOPE,
            SearchVerdict.NUMBERS_FOR_ANOTHER_METHOD,
        )
    ]
