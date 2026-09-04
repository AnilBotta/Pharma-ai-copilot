"""Why no regulatory decision was produced, as a code rather than a sentence.

A REFUSAL IS AN ANSWER, AND IT HAS TO SURVIVE THE TRIP

The failure this vocabulary is against: a caller asks for a bioequivalence
verdict on a partial-replicate study below FDA's switch, gets back an object
whose `passes` field is `False`, and files that. Nothing was computed. Nothing
disagreed with 80.00-125.00%. `False` meant "we did not decide" and was read as
"the study failed", because a boolean has no room to say anything else.

`be_stats` already refuses correctly - `decided=False, passes=None` throughout,
with a `DiagnosticCode` naming the condition. What was missing is a stable,
enumerated REFUSAL vocabulary at the level a product surface and an audit
report consume: one code per reason a regulatory decision was withheld, with
the capability it concerns and the condition that would lift it.

RELATIONSHIP TO `DiagnosticCode`

They are different vocabularies for different readers and are deliberately not
merged.

    DiagnosticCode   what happened to a SUBJECT or a MODEL FIT, inside an
                     analysis. Includes conditions that exclude one subject and
                     change nothing else.
    RefusalCode      why the STUDY got no regulatory verdict. Always
                     study-level, always terminal for that endpoint.

Several refusals have a diagnostic counterpart, and `DIAGNOSTIC_FOR` records
the correspondence so the two cannot drift apart unnoticed.

ONE CORRESPONDENCE IS NOT A RENAME, AND THE DIFFERENCE IS REAL

`DiagnosticCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED` and
`RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED` name the same
situation with two different words, and the second one is the one that matches
the canonical status: `Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL` is
`NOT_IMPLEMENTED`.

The diagnostic keeps its name. `diagnostics.DiagnosticCode` states that a code
is never repurposed, because reports and audit trails outlive releases, and
that rule is worth more than the tidier spelling. The discrepancy is recorded
as finding `DOSSIER-001` rather than papered over - which is what the findings
register is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.diagnostics import DiagnosticCode


class RefusalCode(StrEnum):
    """Why an endpoint produced no regulatory decision.

    Every member answers "what would have to change" in `RefusalReason` below.
    A refusal that cannot say what would lift it is a dead end rather than an
    answer.
    """

    # ------------------------------------------------ not implemented ---
    #: FDA Appendix C for the PARTIAL replicate design. The capability is
    #: NOT_IMPLEMENTED and the reason is evidentiary, not arithmetical: the
    #: same code would converge and produce a plausible interval, and there is
    #: no trustworthy oracle to check its denominator degrees of freedom
    #: against. See validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.md.
    APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED = (
        "APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED"
    )
    #: The endpoint routed to ordinary average BE on a replicate design, and
    #: the raw subject-period observations were not supplied. Appendix C is an
    #: available-case model and cannot be run from a reduced dataset.
    APPENDIX_C_REQUIRES_RAW_OBSERVATIONS = (
        "APPENDIX_C_REQUIRES_RAW_OBSERVATIONS"
    )

    # ------------------------------------------------ design mismatch ---
    #: A highly variable drug was submitted without a replicate design. FDA's
    #: reference-scaled procedure has no sWR to scale by.
    FDA_HVD_DESIGN_REQUIRED = "FDA_HVD_DESIGN_REQUIRED"
    #: An NTI drug on anything but a fully replicate crossover. FDA III.B
    #: requires one, and criterion (c) needs within-TEST replicates that a
    #: partial replicate design does not provide.
    FDA_NTI_FULL_REPLICATE_REQUIRED = "FDA_NTI_FULL_REPLICATE_REQUIRED"
    #: EMA 4.1.10 permits widening only on a 3- or 4-period replicate design.
    EMA_ABEL_REPLICATE_DESIGN_REQUIRED = "EMA_ABEL_REPLICATE_DESIGN_REQUIRED"
    #: The sequences present do not form any supported design.
    UNSUPPORTED_REPLICATE_DESIGN = "UNSUPPORTED_REPLICATE_DESIGN"

    # ---------------------------------------------- scope of the rule ---
    #: EMA widening applies to Cmax and to nothing else. 4.1.10's final
    #: paragraph keeps AUC at 80.00-125.00% regardless of variability, so an
    #: AUC request for ABEL is refused rather than answered with the widened
    #: limits.
    EMA_ABEL_CMAX_ONLY = "EMA_ABEL_CMAX_ONLY"
    #: EMA narrows Cmax for an NTI drug only where Cmax is itself important
    #: for safety, efficacy or therapeutic drug monitoring - decided per
    #: product. Both defaults are wrong for some products.
    EMA_NTI_CMAX_PRODUCT_SPECIFIC = "EMA_NTI_CMAX_PRODUCT_SPECIFIC"
    #: A jurisdiction and drug-class combination this engine does not route.
    UNSUPPORTED_REGULATORY_ROUTE = "UNSUPPORTED_REGULATORY_ROUTE"

    # ------------------------------------------------- estimability ---
    #: The data are structurally fine and an estimate does not exist -
    #: insufficient degrees of freedom, no test replicate, a variance ratio
    #: with a zero denominator.
    QUANTITY_NOT_ESTIMABLE = "QUANTITY_NOT_ESTIMABLE"
    #: The model did not converge, or converged to a singular covariance.
    MODEL_DID_NOT_FIT = "MODEL_DID_NOT_FIT"

    # ---------------------------------------------------- governance ---
    #: The caller demanded a submission-grade result and the capability is
    #: below VALIDATED. Never raised by the ordinary path: implemented
    #: capabilities return their result with the status attached. This is the
    #: refusal a caller opts INTO by asking for validated-only behaviour.
    VALIDATION_STATUS_BELOW_REQUIRED = "VALIDATION_STATUS_BELOW_REQUIRED"


@dataclass(frozen=True, slots=True)
class RefusalReason:
    """A refusal that explains itself and says what would lift it."""

    code: RefusalCode
    #: One sentence, for a person. The code is the machine-readable carrier;
    #: this may be reworded without breaking a caller.
    summary: str
    #: The condition under which this refusal stops applying. "" only where
    #: nothing the caller can do would lift it - and there is no such member
    #: at present, which is deliberate.
    lifted_by: str
    #: Where the rule being enforced is written down.
    source: str = ""

    def explain(self) -> str:
        line = f"{self.code}: {self.summary}"
        return f"{line} Lifted by: {self.lifted_by}" if self.lifted_by else line


#: Every refusal code, with its explanation. Total over `RefusalCode` -
#: `test_every_refusal_code_has_a_reason` fails if a member is added without
#: one, because a code with no "what would lift it" is a dead end rather than
#: an answer.
REFUSALS: dict[RefusalCode, RefusalReason] = {
    RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED: RefusalReason(
        code=RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED,
        summary=(
            "FDA Appendix C is implemented for fully replicate designs only. "
            "For a partial replicate design (2x3x3) the model would converge "
            "and produce a plausible interval, and there is no trustworthy "
            "oracle for its Satterthwaite denominator degrees of freedom, so "
            "no verdict is issued."
        ),
        lifted_by=(
            "An accepted licensed-SAS PROC MIXED run of the Appendix C model "
            "on a partial replicate dataset, establishing the denominator df. "
            "Tracked as blocker APPENDIX-C-PARTIAL-ORACLE."
        ),
        source="validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.md",
    ),
    RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS: RefusalReason(
        code=RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,
        summary=(
            "Appendix C fits subject-period observations with an "
            "available-case likelihood. A dataset reduced to per-subject "
            "contrasts cannot be fitted, and substituting the Appendix G "
            "contrast would answer FDA's question with a different model."
        ),
        lifted_by="Supply the raw log-transformed subject-period observations.",
        source="FDA Statistical Approaches, Appendix C",
    ),
    RefusalCode.FDA_HVD_DESIGN_REQUIRED: RefusalReason(
        code=RefusalCode.FDA_HVD_DESIGN_REQUIRED,
        summary=(
            "FDA's reference-scaled procedure for a highly variable drug "
            "requires a replicated crossover, because sWR is estimated from "
            "repeated reference administrations."
        ),
        lifted_by="Submit a partially or fully replicated crossover study.",
        source="FDA Statistical Approaches, III.C and Appendix G",
    ),
    RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED: RefusalReason(
        code=RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED,
        summary=(
            "FDA requires a FULLY replicate crossover for a narrow "
            "therapeutic index drug. Criterion (c) compares sigma_WT with "
            "sigma_WR, and a partial replicate design never replicates the "
            "test product."
        ),
        lifted_by="Submit a fully replicate crossover study.",
        source="FDA Statistical Approaches, III.B and Appendix F",
    ),
    RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED: RefusalReason(
        code=RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED,
        summary=(
            "EMA permits widened Cmax limits only where CVwR was demonstrated "
            "in a replicate design of three or four periods."
        ),
        lifted_by="Submit a 3-period or 4-period replicate crossover study.",
        source="EMA CPMP/EWP/QWP/1401/98 Rev. 1, 4.1.10",
    ),
    RefusalCode.UNSUPPORTED_REPLICATE_DESIGN: RefusalReason(
        code=RefusalCode.UNSUPPORTED_REPLICATE_DESIGN,
        summary=(
            "The sequences present do not form a replicate design this engine "
            "recognises. Guessing the intended design would silently analyse a "
            "different study from the one submitted."
        ),
        lifted_by=(
            "Submit one of the supported designs, or correct the sequence "
            "labels if they were mis-coded."
        ),
    ),
    RefusalCode.EMA_ABEL_CMAX_ONLY: RefusalReason(
        code=RefusalCode.EMA_ABEL_CMAX_ONLY,
        summary=(
            "EMA's widened acceptance range applies to Cmax only. 4.1.10 keeps "
            "AUC at 80.00-125.00% regardless of variability, so a widened "
            "limit is not available for this endpoint."
        ),
        lifted_by=(
            "Nothing about the study. Analyse AUC under the ordinary "
            "80.00-125.00% interval, which this engine does support."
        ),
        source="EMA CPMP/EWP/QWP/1401/98 Rev. 1, 4.1.10, final paragraph",
    ),
    RefusalCode.EMA_NTI_CMAX_PRODUCT_SPECIFIC: RefusalReason(
        code=RefusalCode.EMA_NTI_CMAX_PRODUCT_SPECIFIC,
        summary=(
            "EMA narrows Cmax for an NTI drug only where Cmax itself matters "
            "for safety, efficacy or therapeutic drug monitoring, and that is "
            "a per-product decision: ciclosporin narrows both AUC and Cmax, "
            "colchicine narrows AUC and leaves Cmax at 80.00-125.00%."
        ),
        lifted_by=(
            "Supply the Cmax limits from the applicable product-specific "
            "guidance as a ProductOverride."
        ),
        source="EMA CPMP/EWP/QWP/1401/98 Rev. 1, narrow therapeutic index drugs",
    ),
    RefusalCode.UNSUPPORTED_REGULATORY_ROUTE: RefusalReason(
        code=RefusalCode.UNSUPPORTED_REGULATORY_ROUTE,
        summary=(
            "This jurisdiction and drug-class combination is not routed by "
            "this engine. Falling back to the ordinary 80.00-125.00% interval "
            "would answer a question the regulator answers differently."
        ),
        lifted_by="Implementation of the route, with its own validation ladder.",
    ),
    RefusalCode.QUANTITY_NOT_ESTIMABLE: RefusalReason(
        code=RefusalCode.QUANTITY_NOT_ESTIMABLE,
        summary=(
            "The quantity the criterion needs does not exist for these data - "
            "too few residual degrees of freedom, no replicated test "
            "measurement, or a ratio whose denominator is exactly zero."
        ),
        lifted_by=(
            "More evaluable subjects, or the missing replicate measurements. "
            "The accompanying diagnostics name which subjects and why."
        ),
    ),
    RefusalCode.MODEL_DID_NOT_FIT: RefusalReason(
        code=RefusalCode.MODEL_DID_NOT_FIT,
        summary=(
            "The mixed model did not converge, or converged to a singular "
            "covariance structure. A fit that did not happen is not a failed "
            "bioequivalence test."
        ),
        lifted_by=(
            "Inspect the dataset for duplicated or degenerate observations; "
            "the diagnostics name the condition."
        ),
    ),
    RefusalCode.VALIDATION_STATUS_BELOW_REQUIRED: RefusalReason(
        code=RefusalCode.VALIDATION_STATUS_BELOW_REQUIRED,
        summary=(
            "The caller required a capability at VALIDATED and this one is "
            "below that bar. The result was computed and is being withheld, "
            "which is not the same as the study failing."
        ),
        lifted_by=(
            "Qualifying evidence promoting the capability to VALIDATED "
            "through the release gate, or a caller that accepts the stated "
            "status and its limitations."
        ),
    ),
}


#: Refusals that have a `DiagnosticCode` counterpart, and which one.
#:
#: Not every refusal appears here: `VALIDATION_STATUS_BELOW_REQUIRED` is a
#: governance decision taken above the analysis, and no diagnostic is emitted
#: for it because nothing happened to the data.
DIAGNOSTIC_FOR: dict[RefusalCode, DiagnosticCode] = {
    RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED: (
        # Named NOT_VALIDATED in the diagnostic vocabulary. Same situation,
        # older spelling, kept because diagnostic codes are never repurposed.
        # See finding DOSSIER-001.
        DiagnosticCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED
    ),
    RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS: (
        DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED
    ),
    RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED: (
        DiagnosticCode.NTI_REQUIRES_FULLY_REPLICATE_DESIGN
    ),
    RefusalCode.UNSUPPORTED_REPLICATE_DESIGN: (
        DiagnosticCode.UNSUPPORTED_REPLICATE_DESIGN
    ),
    RefusalCode.MODEL_DID_NOT_FIT: DiagnosticCode.SINGULAR_MODEL,
}


def refusal(code: RefusalCode) -> RefusalReason:
    """The reason for a code. Raises rather than returning a placeholder."""
    return REFUSALS[code]
