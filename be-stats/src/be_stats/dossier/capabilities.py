"""The canonical capability matrix. One row per thing this engine can do.

WHY THIS FILE EXISTS AND WHAT IT IS NOT

It is NOT a second copy of the validation statuses. Those live in
`be_stats.spec` - `VALIDATION` for methods, `CAPABILITY_VALIDATION` for
capabilities - each entry carrying paragraphs of reasoning about why it is
where it is on the ladder. Restating a status here would create two places to
edit and one of them would go stale; the first PR to promote something would
promote it in one file and the product would show the other.

So every row READS its status through `validation_status`, which looks it up in
`spec`. There is exactly one place a status is written down, and this module is
not it. `test_capability_matrix_does_not_restate_statuses` enforces that by
mutating the spec table and asserting the matrix follows.

WHAT THIS FILE ADDS

Everything a reviewer, a report or a product surface needs that `spec` does not
carry, because `spec` is consumed by the calculation path and should not grow
presentation concerns:

    jurisdiction        which regulator's rule this is
    design_requirement  which study designs it accepts
    endpoints           which measures it may be applied to
    evidence_tier       what KIND of evidence backs its status
    known_limitations   what it does not cover, in the caller's words
    decision_supported  does this alone yield a regulatory verdict
    refusal_conditions  the ways it declines to produce one

COVERAGE IS TOTAL AND TESTED

Every member of `spec.Method` and every member of `spec.Capability` appears
exactly once. A new method added to the engine without a row here fails
`test_every_production_capability_appears_in_the_matrix`, which is the point:
the matrix cannot be quietly incomplete, and a capability that reaches
production without a documented status and limitation set is the failure mode
this whole dossier exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

from be_stats.dossier.refusals import RefusalCode
from be_stats.dossier.statuses import (
    EvidenceTier,
    ImplementationStatus,
    implementation_status_of,
)
from be_stats.minimums import DesignFamily
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE,
    EMA_BIOEQUIVALENCE_HVD,
    EMA_PKWP_QA,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F,
    FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5,
    FDA_STATISTICAL_APPROACHES_APPENDIX_G,
    FDA_STATISTICAL_APPROACHES_II_A,
    FDA_STATISTICAL_APPROACHES_III_B,
    FDA_STATISTICAL_APPROACHES_III_C,
    Citation,
    ValidationStatus,
)
from be_stats.replicate_abe import FDA_STATISTICAL_APPROACHES_APPENDIX_C
from be_stats.spec import (
    CAPABILITY_VALIDATION,
    CONVENTIONAL_ACCEPTANCE_CITATION,
    VALIDATION,
    Capability,
    Endpoint,
    Jurisdiction,
    Method,
)

#: Every endpoint. Spelled out rather than left implicit by an empty tuple,
#: because "applies to all endpoints" and "nobody filled this in" must not look
#: the same in a regulatory document.
ALL_ENDPOINTS: tuple[Endpoint, ...] = (Endpoint.AUC, Endpoint.CMAX, Endpoint.OTHER)

#: The two designs FDA's replicate appendices recognise.
REPLICATE_DESIGNS: tuple[DesignFamily, ...] = (
    DesignFamily.REPLICATE,
    DesignFamily.PARTIAL_REPLICATE,
)


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One row. Everything about a capability except its validation status.

    The status is absent BY DESIGN - see `validation_status`, which reads it
    from `spec`. A `validation_status` field here would be a second copy, and a
    second copy of a regulatory claim is how a product ends up telling a
    customer one thing and an auditor another.
    """

    capability_id: str
    #: What it does, for someone who does not already know.
    title: str
    #: The regulator whose rule this is. `None` where the rule is common to
    #: both - the conventional 80.00-125.00% interval is not FDA's or EMA's.
    jurisdiction: Jurisdiction | None
    #: The method this belongs to. `None` for a capability that serves several
    #: - Appendix C is reached by the HVD unscaled branch and by NTI criterion
    #: (b), and attributing it to one would misdescribe the other.
    method: Method | None
    #: The key this row's status is looked up under. A `Method` or a
    #: `Capability`; never both, never neither.
    source_key: Method | Capability
    design_requirement: tuple[DesignFamily, ...]
    endpoints: tuple[Endpoint, ...]
    regulatory_source: Citation
    evidence_tier: EvidenceTier
    #: Does this ALONE produce a bioequivalence verdict? False for everything
    #: that estimates a quantity or validates a structure - which is most of
    #: the matrix, and the reason a reader must not treat a green row as an
    #: answer to "can I decide a study with this".
    decision_supported: bool
    known_limitations: tuple[str, ...] = ()
    refusal_conditions: tuple[RefusalCode, ...] = ()
    #: Free text for anything the fields above cannot carry.
    note: str = ""

    @property
    def validation_status(self) -> ValidationStatus:
        """Read from `spec`, never stored. The single source of truth."""
        if isinstance(self.source_key, Method):
            return VALIDATION[self.source_key]
        return CAPABILITY_VALIDATION[self.source_key]

    @property
    def implementation_status(self) -> ImplementationStatus:
        """Derived from the validation status, never independently asserted."""
        return implementation_status_of(self.validation_status)

    @property
    def source_version(self) -> str:
        """The document version, pulled out for reports that tabulate it."""
        return self.regulatory_source.document_version


def _record(**kwargs) -> CapabilityRecord:
    return CapabilityRecord(**kwargs)


# ---------------------------------------------------------------- methods ---
#
# A METHOD is a candidate answer to "which test applies to this study". Each of
# the five appears once; `Method` has exactly five members and
# `test_every_production_capability_appears_in_the_matrix` checks that.

_METHOD_ROWS: tuple[CapabilityRecord, ...] = (
    _record(
        capability_id="AVERAGE_BE_2X2",
        title="Average bioequivalence, conventional 80.00-125.00% interval",
        jurisdiction=None,
        method=Method.STANDARD_ABE,
        source_key=Method.STANDARD_ABE,
        design_requirement=(DesignFamily.CROSSOVER, DesignFamily.PARALLEL),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=CONVENTIONAL_ACCEPTANCE_CITATION,
        evidence_tier=EvidenceTier.TIER_3,
        decision_supported=True,
        known_limitations=(
            "The two one-sided tests procedure on a 2x2 crossover or a "
            "parallel design. A REPLICATE design routed to ordinary average "
            "BE is a different model - FDA Appendix C - and is a separate "
            "capability with its own status.",
            "No regulator-published worked dataset has been reproduced "
            "through this path, so it stands at IMPLEMENTED_UNVALIDATED "
            "despite being the most conventional analysis in the package.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="FDA_HVD_RSABE",
        title="FDA reference-scaled average BE for highly variable drugs",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Method.FDA_HVD_RSABE,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=True,
        known_limitations=(
            "Tier 1A only: FDA's stated algorithm is conformed to, and FDA "
            "has published no worked numerical example of it. The tier-3 "
            "PowerTOST agreement is engineering evidence, not regulatory "
            "authority.",
            "Below the sWR switch the endpoint routes to ordinary average BE, "
            "which on a partial replicate design is not implemented and "
            "returns NOT DECIDED rather than a verdict.",
        ),
        refusal_conditions=(
            RefusalCode.FDA_HVD_DESIGN_REQUIRED,
            RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    _record(
        capability_id="FDA_NTI_RSABE",
        title="FDA narrow therapeutic index procedure, all three criteria",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_NTI_RSABE,
        source_key=Method.FDA_NTI_RSABE,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=True,
        known_limitations=(
            "Tier 1A only. FDA publishes the three criteria and no worked "
            "dataset carrying all three through to a verdict.",
            "All three criteria must hold. A caller reading only the scaled "
            "criterion is reading a third of the procedure.",
            "Requires a FULLY replicate design; a partial replicate study is "
            "refused before any arithmetic runs.",
        ),
        refusal_conditions=(
            RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    _record(
        capability_id="EMA_HVD_ABEL",
        title="EMA average bioequivalence with expanding limits",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Method.EMA_HVD_ABEL,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=True,
        known_limitations=(
            "Three of its four component capabilities are VALIDATED on "
            "tier-1B evidence and the METHOD is not. No EMA publication "
            "carries one end-to-end example from CVwR > 30% through widened "
            "limits and the Method A interval to a stated verdict, so the "
            "wiring between validated parts is itself unvalidated.",
            "Cmax only. AUC stays at 80.00-125.00% regardless of variability.",
        ),
        refusal_conditions=(
            RefusalCode.EMA_ABEL_CMAX_ONLY,
            RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    _record(
        capability_id="EMA_NTI_NARROW_ABE",
        title="EMA narrowed 90.00-111.11% interval for NTI drugs",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_NTI_NARROW_ABE,
        source_key=Method.EMA_NTI_NARROW_ABE,
        design_requirement=(DesignFamily.CROSSOVER, DesignFamily.REPLICATE),
        endpoints=(Endpoint.AUC, Endpoint.CMAX),
        regulatory_source=EMA_BIOEQUIVALENCE,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=True,
        known_limitations=(
            "Applies to AUC by default. For Cmax the narrowed interval "
            "applies only where Cmax itself matters for safety, efficacy or "
            "therapeutic drug monitoring - a per-product decision the engine "
            "refuses to guess.",
            "EMA narrows the interval; FDA does not. The two NTI procedures "
            "are different procedures and neither is a parameterisation of "
            "the other.",
        ),
        refusal_conditions=(RefusalCode.EMA_NTI_CMAX_PRODUCT_SPECIFIC,),
    ),
)


# ----------------------------------------------------------- capabilities ---
#
# A CAPABILITY is something the engine does that is NOT a candidate answer to
# "which test applies" - it validates a structure, or estimates a quantity a
# method will later consume. `decision_supported` is False for all but the two
# that assemble a verdict, and a reader must not infer from a healthy row here
# that a study can be decided.

_CAPABILITY_ROWS: tuple[CapabilityRecord, ...] = (
    # ------------------------------------------- FDA highly variable ---
    _record(
        capability_id="FDA_HVD_REPLICATE_DATA_VALIDATION",
        title="Recognise and validate an FDA replicate design",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Capability.FDA_HVD_REPLICATE_DATA_VALIDATION,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_II_A,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "Structural. It enforces the design definitions and produces no "
            "number a regulator could disagree with, which is why its status "
            "is IMPLEMENTED rather than IMPLEMENTED_UNVALIDATED.",
        ),
        refusal_conditions=(RefusalCode.UNSUPPORTED_REPLICATE_DESIGN,),
    ),
    _record(
        capability_id="FDA_HVD_REFERENCE_VARIANCE",
        title="Estimate the within-subject reference variance and CVwR",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Capability.FDA_HVD_REFERENCE_VARIANCE,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "Produces sWR, which selects the analysis. No FDA-published "
            "worked dataset has been reproduced through it.",
            "Subjects without two reference measurements are excluded and "
            "reported; the count that reaches the estimator is not the count "
            "that entered the study.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="FDA_HVD_TREATMENT_CONTRAST",
        title="Estimate mu_T - mu_R from the sequence means of Iij",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Capability.FDA_HVD_TREATMENT_CONTRAST,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_G,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "The Appendix G contrast, which absorbs period within a subject "
            "and is NOT the Appendix C model. The two must never be "
            "substituted for one another.",
            "Needs a complete subject; Appendix C does not. The two models "
            "run on different subject sets and each reports its own.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="FDA_HVD_METHOD_SELECTION",
        title="Apply FDA's sWR = 0.294 switch to one endpoint",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Capability.FDA_HVD_METHOD_SELECTION,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_III_C,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "The boundary case sWR = 0.294 selects reference scaling, which "
            "is what III.C and Appendix G both state. Section III.A uses the "
            "same number with the opposite inequality for in vitro permeation "
            "testing, and this switch is wrong for that context.",
        ),
    ),
    _record(
        capability_id="FDA_HVD_UNSCALED_BRANCH",
        title="Ordinary average BE for a replicate design below the switch",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_HVD_RSABE,
        source_key=Capability.FDA_HVD_UNSCALED_BRANCH,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_C,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=True,
        known_limitations=(
            "The status is the weaker of the two situations it covers. A "
            "FULLY replicate study with raw observations is decided; a "
            "PARTIAL replicate study is refused, and so is a fully replicate "
            "one supplied only as reduced contrasts.",
            "A caller reading IMPLEMENTED here must not infer that every HVD "
            "study below the switch receives a verdict.",
        ),
        refusal_conditions=(
            RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED,
            RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,
        ),
    ),
    # ------------------------------------------------------ Appendix C ---
    _record(
        capability_id="FDA_REPLICATE_STANDARD_ABE_FULL",
        title="FDA Appendix C mixed model, fully replicate design",
        jurisdiction=Jurisdiction.FDA,
        method=None,
        source_key=Capability.FDA_REPLICATE_STANDARD_ABE_FULL,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_C,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=True,
        known_limitations=(
            "The tier-1B numbers are EMA-published, for a model EMA "
            "transcribes and attributes to FDA by name. Excellent evidence "
            "that the arithmetic is right; NOT FDA validating FDA's own "
            "model, and never to be described as the latter. That is why the "
            "status is IMPLEMENTED_UNVALIDATED despite the evidence.",
            "The tier-3 ReplicateBE.jl agreement holds only within the "
            "covariance domain that oracle can represent. A negative "
            "subject-by-formulation correlation, which FA0(2) permits, is "
            "outside it - see VAL-FDA-APPENDIX-C-003.",
            "Requires the raw subject-period observations; the model is "
            "available-case and cannot be fitted from reduced contrasts.",
        ),
        refusal_conditions=(RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,),
        note=(
            "Would move to VALIDATED on an FDA-published worked example of "
            "Appendix C, or a licensed SAS PROC MIXED run on a dataset with "
            "published inputs. Not on another oracle and not on more "
            "synthetic cases."
        ),
    ),
    _record(
        capability_id="FDA_REPLICATE_STANDARD_ABE_PARTIAL",
        title="FDA Appendix C mixed model, partial replicate design",
        jurisdiction=Jurisdiction.FDA,
        method=None,
        source_key=Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL,
        design_requirement=(DesignFamily.PARTIAL_REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_C,
        evidence_tier=EvidenceTier.NONE,
        decision_supported=False,
        known_limitations=(
            "NOT IMPLEMENTED. The obstacle is evidentiary rather than "
            "arithmetical: the same code would converge and return a "
            "plausible interval, and the correct Satterthwaite denominator "
            "degrees of freedom for this design remain NOT DETERMINED.",
            "Candidate values exist and none is treated as the answer. They "
            "are recorded in the blocker record with what each one does and "
            "does not establish, and no constant in this package holds one.",
        ),
        refusal_conditions=(
            RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED,
        ),
        note=(
            "Blocked on blocker APPENDIX-C-PARTIAL-ORACLE: a licensed SAS "
            "Appendix C run on a partial replicate dataset. See "
            "validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.md."
        ),
    ),
    # ------------------------------------ narrow therapeutic index ---
    _record(
        capability_id="FDA_NTI_DESIGN_VALIDATION",
        title="Enforce a fully replicate design before any NTI arithmetic",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_NTI_RSABE,
        source_key=Capability.FDA_NTI_DESIGN_VALIDATION,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_III_B,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "Structural. The gate either enforces III.B or it does not.",
        ),
        refusal_conditions=(RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED,),
    ),
    _record(
        capability_id="FDA_NTI_REFERENCE_SCALED_CRITERION",
        title="Appendix F criterion (a): the reference-scaled mean criterion",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_NTI_RSABE,
        source_key=Capability.FDA_NTI_REFERENCE_SCALED_CRITERION,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "One of three criteria. Passing it is not passing the procedure.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="FDA_NTI_VARIABILITY_RATIO",
        title="Appendix F criterion (c): the 90% F interval for sWT / sWR",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_NTI_RSABE,
        source_key=Capability.FDA_NTI_VARIABILITY_RATIO,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_F_STEPS_4_5,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "An equal-tails F interval at alpha = 0.1, not a normal "
            "approximation.",
            "Undefined when sWR is exactly zero. That is a refusal, not a "
            "pass and not infinity.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="FDA_NTI_UNSCALED_ABE",
        title="Appendix F criterion (b): the unscaled 80.00-125.00% limits",
        jurisdiction=Jurisdiction.FDA,
        method=Method.FDA_NTI_RSABE,
        source_key=Capability.FDA_NTI_UNSCALED_ABE,
        design_requirement=(DesignFamily.REPLICATE,),
        endpoints=ALL_ENDPOINTS,
        regulatory_source=FDA_STATISTICAL_APPROACHES_APPENDIX_F,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=False,
        known_limitations=(
            "Computed through Appendix C, and therefore inherits Appendix C's "
            "evidence and its requirement for raw observations.",
            "NTI's design gate already requires a fully replicate design, so "
            "unlike the HVD branch there is no partial replicate case here.",
        ),
        refusal_conditions=(RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,),
    ),
    # ------------------------------------------- EMA highly variable ---
    _record(
        capability_id="EMA_HVD_DESIGN_GATE",
        title="Which replicate designs EMA 4.1.10 permits, with a reason",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_HVD_DESIGN_GATE,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=("Structural; no number for a regulator to dispute.",),
        refusal_conditions=(RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED,),
    ),
    _record(
        capability_id="EMA_HVD_VARIABILITY_ELIGIBILITY",
        title="CVwR > 30%, strictly, on the CV scale, Cmax only",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_HVD_VARIABILITY_ELIGIBILITY,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "Compared on the CV scale and never converted to an sWR boundary. "
            "EMA's threshold on that scale is 0.293560..., which is a "
            "different number from FDA's stated 0.294, and studies exist "
            "between them.",
        ),
        refusal_conditions=(RefusalCode.EMA_ABEL_CMAX_ONLY,),
    ),
    _record(
        capability_id="EMA_HVD_REFERENCE_VARIABILITY",
        title="CVwR from the reference measurements alone",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_HVD_REFERENCE_VARIABILITY,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_PKWP_QA,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=False,
        known_limitations=(
            "Validated against the two annexed EMA data sets. Both are "
            "four-period; no published three-period example exists.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="EMA_REPLICATE_METHOD_A",
        title="EMA Method A: the all-fixed-effects ANOVA the Q&A recommends",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_REPLICATE_METHOD_A,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=ALL_ENDPOINTS,
        regulatory_source=EMA_PKWP_QA,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=False,
        known_limitations=(
            "Validated on both annexed data sets including the unbalanced "
            "one, whose eight incomplete subjects must be retained for the "
            "published result to come out.",
            "Method A is EMA's recommendation and is not FDA's Appendix C. "
            "The two are different models and neither substitutes.",
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    _record(
        capability_id="EMA_ABEL_LIMIT_CALCULATION",
        title="The widened limits exp(+/- 0.760 sWR), capped as stated",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_ABEL_LIMIT_CALCULATION,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1B,
        decision_supported=False,
        known_limitations=(
            "The cap is applied as the regulator STATES it, 69.84-143.19%, "
            "not as the formula recomputes it. PowerTOST keeps the unrounded "
            "pair; be-stats follows EMA. See VAL-EMA-ABEL-002.",
        ),
        refusal_conditions=(RefusalCode.EMA_ABEL_CMAX_ONLY,),
    ),
    _record(
        capability_id="EMA_ABEL_PE_CONSTRAINT",
        title="The GMR must additionally fall within 80.00-125.00%",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_ABEL_PE_CONSTRAINT,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=False,
        known_limitations=(
            "A containment test on a number produced elsewhere. No "
            "EMA-published example exercises the constraint on its own, so it "
            "stays unvalidated even though the limits either side of it are "
            "validated.",
        ),
    ),
    _record(
        capability_id="EMA_HVD_ENDPOINT_DECISION",
        title="The two EMA criteria combined into one endpoint verdict",
        jurisdiction=Jurisdiction.EMA,
        method=Method.EMA_HVD_ABEL,
        source_key=Capability.EMA_HVD_ENDPOINT_DECISION,
        design_requirement=REPLICATE_DESIGNS,
        endpoints=(Endpoint.CMAX,),
        regulatory_source=EMA_BIOEQUIVALENCE_HVD,
        evidence_tier=EvidenceTier.TIER_1A,
        decision_supported=True,
        known_limitations=(
            "Every PART has tier-1B evidence and the WHOLE does not. "
            "Validating the components does not validate the wiring between "
            "them, and this is exactly where correct pieces could be "
            "assembled into a wrong verdict.",
        ),
        refusal_conditions=(
            RefusalCode.EMA_ABEL_CMAX_ONLY,
            RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED,
        ),
    ),
)


#: THE canonical capability matrix, keyed by `capability_id`.
CAPABILITY_MATRIX: dict[str, CapabilityRecord] = {
    record.capability_id: record for record in (*_METHOD_ROWS, *_CAPABILITY_ROWS)
}


def capability(capability_id: str) -> CapabilityRecord:
    """One row, or a KeyError naming what is available."""
    try:
        return CAPABILITY_MATRIX[capability_id]
    except KeyError:
        raise KeyError(
            f"No capability {capability_id!r}. Known: "
            f"{', '.join(sorted(CAPABILITY_MATRIX))}"
        ) from None


def capabilities_for(jurisdiction: Jurisdiction | None) -> list[CapabilityRecord]:
    """Every row for one regulator, in matrix order.

    `None` selects the jurisdiction-neutral rows, not "all rows" - a caller
    that means all of them can read `CAPABILITY_MATRIX` directly, and
    overloading `None` to mean both would make a filtered report silently
    unfiltered.
    """
    return [r for r in CAPABILITY_MATRIX.values() if r.jurisdiction is jurisdiction]


def decision_capabilities() -> list[CapabilityRecord]:
    """The rows that alone produce a regulatory verdict."""
    return [r for r in CAPABILITY_MATRIX.values() if r.decision_supported]


def by_validation_status() -> dict[ValidationStatus, list[str]]:
    """Capability ids grouped by status, for a release note or a dashboard."""
    grouped: dict[ValidationStatus, list[str]] = {s: [] for s in ValidationStatus}
    for record in CAPABILITY_MATRIX.values():
        grouped[record.validation_status].append(record.capability_id)
    return grouped
