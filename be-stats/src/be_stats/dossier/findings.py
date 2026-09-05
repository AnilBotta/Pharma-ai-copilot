"""The findings register: what is known to be unresolved or qualified.

WHY A REGISTER AND NOT JUST THE FILES

`validation/findings/` already holds one JSON and one Markdown file per
numerical finding, each far richer than anything summarised here. What it does
not hold is a single structured list a report can iterate, and it cannot hold
one for two reasons.

First, those files are not shipped inside the installed package -
`validation/` lives beside `src/`, so a library module cannot read them and a
deployed application has no access to them at all. A register that only exists
as files on a developer's disk is not available where the product needs it.

Second, some findings have no numerical file because they are not numerical.
"The manual SAS workflow attests execution rather than proving it" is a real,
recorded limitation on what the evidence can establish, and there is no oracle
comparison that would ever produce it.

So the register is declared here, in code, and
`test_register_agrees_with_the_committed_finding_files` cross-checks every
entry that has a file against that file's id, status and method. Neither can
drift without a failure.

SEVERITY IS ABOUT CONSEQUENCE FOR A CLAIM

Not about how surprising the finding was or how much work it caused. A reader
scanning this register is asking one question - "does this change what I may
say about a result" - and the severity answers exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FindingSeverity(StrEnum):
    """What the finding does to a claim."""

    #: A capability cannot exist or cannot be promoted until this is resolved.
    BLOCKING = "blocking"
    #: A claim stands, with a stated qualification attached. A tier-3 row that
    #: reads PASSED_WITH_FINDING rather than PASSED is the archetype.
    QUALIFYING = "qualifying"
    #: Bounds what is covered without weakening what is claimed inside those
    #: bounds.
    SCOPE_LIMITATION = "scope_limitation"
    #: Recorded so it is not rediscovered. No effect on any claim.
    INFORMATIONAL = "informational"


class FindingStatus(StrEnum):
    """Does anyone still need to work on this?

    Mirrors the vocabulary in `validation/findings/README.md`, deliberately:
    the register must not invent a second set of words for the states the
    committed files already use.
    """

    OPEN = "open"
    #: Found by inspecting an oracle's source BEFORE a comparison was written,
    #: so the wrong comparison was never run. Nothing broke.
    PREEMPTED = "preempted"
    #: Understood and decided. NOT the same as "the numbers now agree" - an
    #: accepted permanent divergence is RESOLVED and still qualifies a row.
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class Finding:
    """One entry in the register."""

    finding_id: str
    severity: FindingSeverity
    status: FindingStatus
    #: Capability ids from `dossier.capabilities`. Empty only for a finding
    #: about the validation apparatus itself rather than about a capability.
    affected_capabilities: tuple[str, ...]
    description: str
    #: What is actually known, and how. Not a restatement of the description.
    evidence: str
    #: What would close it. Required for OPEN findings, and present for
    #: RESOLVED ones that describe a permanent divergence, where the honest
    #: answer is that nothing closes it.
    resolution_condition: str
    #: The committed file, relative to the be-stats package root. Empty for
    #: findings with no numerical comparison behind them.
    evidence_file: str = ""
    #: The blocker id this finding motivates, if any.
    blocker_id: str = ""

    @property
    def is_open(self) -> bool:
        return self.status is FindingStatus.OPEN


FINDINGS_REGISTER: tuple[Finding, ...] = (
    Finding(
        finding_id="VAL-FDA-APPENDIX-C-PARTIAL-001",
        severity=FindingSeverity.BLOCKING,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("FDA_REPLICATE_STANDARD_ABE_PARTIAL",),
        description=(
            "The correct Satterthwaite denominator degrees of freedom for "
            "FDA's Appendix C model on a partial replicate design is not "
            "determined. A candidate of about 19.89 is the best supported "
            "value; ReplicateBE.jl's 22.540 is incompatible with EMA's "
            "published interval under the corroborated standard error."
        ),
        evidence=(
            "An independent observed-information calculation sharing no code "
            "with the REML implementation, checked for compatibility against "
            "EMA/618604/2008 Rev. 13's published partial replicate output. "
            "Boundary handling confirmed independently."
        ),
        resolution_condition=(
            "A licensed SAS PROC MIXED run of the Appendix C statements on a "
            "partial replicate dataset, reviewed and accepted through the "
            "governed workflow."
        ),
        evidence_file="validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.json",
        blocker_id="APPENDIX-C-PARTIAL-ORACLE",
    ),
    Finding(
        finding_id="VAL-FDA-APPENDIX-C-002",
        severity=FindingSeverity.BLOCKING,
        status=FindingStatus.OPEN,
        affected_capabilities=(
            "FDA_REPLICATE_STANDARD_ABE_PARTIAL",
            "FDA_REPLICATE_STANDARD_ABE_FULL",
        ),
        description=(
            "ReplicateBE.jl reproduces EMA's published SAS Method C output "
            "exactly on the fully replicate design and does not on the "
            "partial replicate one. An oracle established on one design does "
            "not transfer to the other."
        ),
        evidence=(
            "Pinned ReplicateBE.jl 1.0.15 on Julia 1.10.5 against both "
            "annexed EMA data sets, run in a locked container."
        ),
        resolution_condition=(
            "The same SAS evidence that closes the partial-replicate blocker. "
            "Until then this stays OPEN, which is why the partial capability "
            "is NOT_IMPLEMENTED rather than merely unvalidated."
        ),
        evidence_file="validation/findings/VAL-FDA-APPENDIX-C-002.json",
        blocker_id="APPENDIX-C-PARTIAL-ORACLE",
    ),
    Finding(
        finding_id="VAL-FDA-APPENDIX-C-003",
        severity=FindingSeverity.SCOPE_LIMITATION,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("FDA_REPLICATE_STANDARD_ABE_FULL",),
        description=(
            "ReplicateBE.jl cannot represent a NEGATIVE subject-by-"
            "formulation correlation, which FDA's FA0(2) structure permits "
            "through the sign of l21. Where the fit has one, the oracle is "
            "structurally incapable of fitting the same model and cannot "
            "adjudicate a disagreement."
        ),
        evidence=(
            "Seven of nine synthetic full-replicate cases agree to 1e-6 on "
            "all five covariance parameters, the standard error and the "
            "denominator df. The two that do not are exactly the negative-"
            "correlation fits, and they were adjudicated by an independent "
            "algebraic identity instead."
        ),
        resolution_condition=(
            "Nothing closes it - it is a permanent property of the oracle. "
            "The tier-3 claim is stated with the domain qualifier attached, "
            "which is the correct handling rather than a workaround."
        ),
        evidence_file="validation/findings/VAL-FDA-APPENDIX-C-003.json",
    ),
    Finding(
        finding_id="VAL-FDA-APPENDIX-C-004",
        severity=FindingSeverity.QUALIFYING,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("FDA_REPLICATE_STANDARD_ABE_FULL",),
        description=(
            "The denominator df difference against ReplicateBE.jl is a "
            "BOUNDARY effect and appears only at the boundary of the "
            "covariance parameter space. Away from it the two agree."
        ),
        evidence=(
            "The nine synthetic cases plus EMA Data set I, with the mechanism "
            "identified and the alternatives ruled out first."
        ),
        resolution_condition=(
            "Nothing closes it. The tolerance is stated in df rather than in "
            "percent, so the qualification travels with the claim."
        ),
        evidence_file="validation/findings/VAL-FDA-APPENDIX-C-004.json",
    ),
    Finding(
        finding_id="VAL-FDA-APPENDIX-C-001",
        severity=FindingSeverity.INFORMATIONAL,
        status=FindingStatus.RESOLVED,
        affected_capabilities=(
            "FDA_REPLICATE_STANDARD_ABE_FULL",
            "FDA_REPLICATE_STANDARD_ABE_PARTIAL",
        ),
        description=(
            "The feasibility question itself: is there a trustworthy "
            "numerical oracle for FDA's Appendix C model? Answered - one "
            "exists for the fully replicate design, within a stated "
            "covariance domain, and none exists for the partial replicate "
            "one."
        ),
        evidence=(
            "A survey of R mixed-model packages, none of which supports both "
            "group-specific residual variances and Satterthwaite df, followed "
            "by the ReplicateBE.jl investigation."
        ),
        resolution_condition=(
            "Answered as a question. The obstacle it identified is tracked as "
            "the partial-replicate blocker."
        ),
        evidence_file="validation/findings/VAL-FDA-APPENDIX-C-001.json",
    ),
    Finding(
        finding_id="VAL-FDA-HVD-002",
        severity=FindingSeverity.QUALIFYING,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("FDA_HVD_RSABE", "FDA_HVD_METHOD_SELECTION"),
        description=(
            "PowerTOST switches at sWR = 0.293560, derived from a 30% CV. FDA "
            "states 0.294. be-stats follows the regulator, so the tier-3 row "
            "is PASSED_WITH_FINDING rather than PASSED."
        ),
        evidence=(
            "PowerTOST source inspection plus a boundary sweep measuring how "
            "often the two thresholds select different analyses."
        ),
        resolution_condition=(
            "Nothing closes it. Both sides behave as designed and will "
            "continue to differ. Revisit only if FDA restates the rule."
        ),
        evidence_file="validation/findings/VAL-FDA-HVD-002.json",
    ),
    Finding(
        finding_id="VAL-EMA-ABEL-002",
        severity=FindingSeverity.QUALIFYING,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("EMA_ABEL_LIMIT_CALCULATION",),
        description=(
            "EMA states the ABEL cap as the pair 69.84-143.19%; the formula "
            "at CVwR = 50% gives a fractionally wider one, which PowerTOST "
            "keeps. be-stats applies the stated pair."
        ),
        evidence=(
            "The guideline's own table at CVwR 30, 35, 40, 45 and >=50 "
            "percent, all five rows reproduced to the printed decimals."
        ),
        resolution_condition=(
            "Nothing closes it. A documented divergence between an oracle and "
            "a regulator is not an open question about the rule."
        ),
        evidence_file="validation/findings/VAL-EMA-ABEL-002.json",
    ),
    Finding(
        finding_id="VAL-EMA-ABEL-001",
        severity=FindingSeverity.INFORMATIONAL,
        status=FindingStatus.PREEMPTED,
        affected_capabilities=("EMA_HVD_ENDPOINT_DECISION",),
        description=(
            "PowerTOST's p(BE-ABEL) is the MIXED decision rather than the "
            "scaled criterion alone, and power.scABEL documents four purely "
            "empirical adaptations - making it a tuned approximation rather "
            "than an oracle."
        ),
        evidence=(
            "Source inspection before any comparison fixture was written, so "
            "the wrong comparison was never run."
        ),
        resolution_condition=(
            "Nothing to close. Other oracles were used instead."
        ),
        evidence_file="validation/findings/VAL-EMA-ABEL-001.json",
    ),
    Finding(
        finding_id="VAL-FDA-HVD-001",
        severity=FindingSeverity.INFORMATIONAL,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("FDA_HVD_RSABE",),
        description=(
            "PowerTOST's p(BE-sABEc) is the mixed decision, not the scaled "
            "criterion alone. The harness had been comparing two quantities "
            "that are not the same quantity."
        ),
        evidence=(
            "A harness defect with no production impact, confirmed against "
            "the real oracle and reproduced by matched synthetic datasets."
        ),
        resolution_condition=(
            "Closed. It left behind the rule that an oracle's source is read "
            "before a comparison against it is written."
        ),
        evidence_file="validation/findings/VAL-FDA-HVD-001.json",
    ),
    # ------------------------------------------------------------------
    # Findings with no numerical comparison behind them. They are no less
    # real for that, and there is nowhere else they would be recorded.
    Finding(
        finding_id="DOSSIER-001",
        severity=FindingSeverity.INFORMATIONAL,
        status=FindingStatus.OPEN,
        affected_capabilities=("FDA_REPLICATE_STANDARD_ABE_PARTIAL",),
        description=(
            "The diagnostic emitted when a partial replicate study is refused "
            "is named APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED, while the "
            "canonical status of the capability is NOT_IMPLEMENTED. Two words "
            "for one situation, and the diagnostic's is the weaker claim."
        ),
        evidence=(
            "be_stats.diagnostics.DiagnosticCode versus "
            "spec.CAPABILITY_VALIDATION. The refusal vocabulary added in this "
            "release uses the accurate spelling and records the "
            "correspondence in dossier.refusals.DIAGNOSTIC_FOR."
        ),
        resolution_condition=(
            "Renaming the diagnostic would break the rule that a diagnostic "
            "code is never repurposed, since reports and audit trails outlive "
            "releases. It is left OPEN and documented rather than renamed. "
            "Closing it means a deliberate vocabulary migration with a "
            "deprecation path, not an in-place rename."
        ),
    ),
    Finding(
        finding_id="DOSSIER-002",
        severity=FindingSeverity.SCOPE_LIMITATION,
        status=FindingStatus.OPEN,
        affected_capabilities=(),
        description=(
            "In the manual SAS workflow the package hashes and the parsed "
            "result are verifiable, and that the output came from running "
            "that program in a licensed SAS session is ATTESTED by a named "
            "operator rather than proven by the platform."
        ),
        evidence=(
            "The workflow itself: package manifest SHA-256 verification "
            "establishes what was supposed to run, and an append-only "
            "operator attestation records who says it ran."
        ),
        resolution_condition=(
            "A managed or directly connected SAS execution path, where the "
            "platform submits and receives without a human-carried step."
        ),
        blocker_id="MANUAL-SAS-EXECUTION-INTEGRITY",
    ),
    Finding(
        finding_id="DOSSIER-004",
        severity=FindingSeverity.SCOPE_LIMITATION,
        status=FindingStatus.RESOLVED,
        affected_capabilities=("AVERAGE_BE_2X2",),
        # The description is the finding AS RAISED and is left in the past
        # tense rather than rewritten. A register that edits its own history
        # once a gap closes cannot be audited: the reader needs to see what
        # was wrong, not only that something now is not.
        description=(
            "The conventional 80.00-125.00% acceptance interval was not "
            "pinned to a primary document. Its citation named a rule rather "
            "than a document, gave three authorities at once, and carried the "
            "version string 'current' - which `provenance` opens by warning "
            "is not a version but a promise that somebody will remember to "
            "check."
        ),
        evidence=(
            "CONVENTIONAL_LOWER_PERCENT and CONVENTIONAL_UPPER_PERCENT were "
            "the two normative constants that failed `has_pinned_citation`. "
            "They were reported inside a '29/29 carry document, section and "
            "version' claim that the data never supported, and the metric "
            "that produced it counted no sections at all. "
            "CLOSED by reading three primary documents, each of which states "
            "the interval in the same words at its own section: ICH M13A "
            "2.2.4 (final version, adopted 23 July 2024); FDA's adoption at "
            "II.B.4 (final, October 2024); and EMA's at 2.2.4 "
            "(EMA/CHMP/ICH/953493/2022, effective 25 January 2025). The "
            "sentence read in all three: 'The 90% confidence interval for the "
            "geometric mean ratio of these PK parameters used to establish BE "
            "should lie within a range of 80.00 - 125.00%.'"
        ),
        resolution_condition=(
            "Satisfied. The condition was to read the section stating the "
            "interval in a primary source and cite it with a pinned version, "
            "never to write a section number from memory. Three were read "
            "rather than one because the sentence lives in three documents: "
            "M13A 2.2.4 sits inside 2.2, 'Data Analysis for Non-Replicate "
            "Study Design', and M13A's scope defers highly variable and "
            "narrow therapeutic index drugs to the future M13C - so the "
            "citation reaches ordinary average BE and reaches nothing else."
        ),
    ),
    Finding(
        finding_id="DOSSIER-005",
        severity=FindingSeverity.SCOPE_LIMITATION,
        status=FindingStatus.OPEN,
        affected_capabilities=(),
        description=(
            "M13A Q&A 2.1 states the twelve-evaluable-subject floor for "
            "PIVOTAL bioequivalence studies. `minimums.py` carries the "
            "figures and the word 'evaluable' but not the word 'pivotal', so "
            "a caller running a pilot relative bioavailability study is "
            "returned a floor the document does not place on it."
        ),
        evidence=(
            "Read at Q&A 2.1 in all three adoptions, which are word for word "
            "identical: 'The requirement for a minimum of 12 evaluable "
            "subjects in pivotal BE studies for a crossover design, or a "
            "minimum of 12 per treatment group for a parallel design, is an "
            "established practice by regulatory agencies.' The same answer "
            "then names a pilot relative bioavailability study as an INPUT to "
            "sizing the pivotal one, so the document plainly does not hold a "
            "pilot to the floor. `RegulatoryMinimum.scope` currently reads "
            "'immediate-release solid oral dosage forms', which is M13A's "
            "dosage-form scope and not its study-role scope."
        ),
        resolution_condition=(
            "Decide whether `lookup` should take the study's role, or whether "
            "the qualifier belongs in `scope` alone. It is recorded rather "
            "than fixed because it changes what a study-design rule returns, "
            "which is not a provenance edit. The direction of the error is "
            "conservative - a floor applied where none is required - but "
            "conservative is not correct, and this module's own docstring "
            "names applying a document's rule outside its scope as the "
            "failure it exists to prevent."
        ),
    ),
    Finding(
        finding_id="DOSSIER-003",
        severity=FindingSeverity.SCOPE_LIMITATION,
        status=FindingStatus.OPEN,
        affected_capabilities=(
            "FDA_HVD_RSABE",
            "FDA_NTI_RSABE",
            "AVERAGE_BE_2X2",
        ),
        description=(
            "No FDA capability holds tier-1B evidence, because FDA has "
            "published no worked numerical example of any of these "
            "procedures. Every FDA method that produces a number therefore "
            "stands at IMPLEMENTED_UNVALIDATED regardless of how much tier-1A "
            "and tier-3 evidence supports it."
        ),
        evidence=(
            "The validation ladder in validation/README.md, and the absence "
            "of any FDA-published dataset with published results."
        ),
        resolution_condition=(
            "An FDA-published worked example, or a licensed SAS run of FDA's "
            "own example code on published inputs."
        ),
        blocker_id="FDA-TIER-1B-WORKED-EXAMPLE",
    ),
)


#: Keyed for lookup.
FINDINGS: dict[str, Finding] = {f.finding_id: f for f in FINDINGS_REGISTER}


def open_findings() -> list[Finding]:
    return [f for f in FINDINGS_REGISTER if f.is_open]


def findings_for(capability_id: str) -> list[Finding]:
    """Every finding that qualifies or blocks one capability."""
    return [
        f for f in FINDINGS_REGISTER if capability_id in f.affected_capabilities
    ]


def blocking_findings() -> list[Finding]:
    return [
        f for f in FINDINGS_REGISTER if f.severity is FindingSeverity.BLOCKING
    ]
