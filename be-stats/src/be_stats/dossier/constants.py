"""Every regulatory number, and why it is here.

THE QUESTION THIS ANSWERS

Point at any constant in a report and ask: which document, which section, which
version, who checked it, and is it something the regulator WROTE or something
this package COMPUTED? `be_stats.provenance` already attaches the first four to
each value. This module adds the fifth, and makes the whole set enumerable so a
review can ask the question of every constant at once rather than one at a
time.

NORMATIVE AND DERIVED ARE NOT INTERCHANGEABLE

    NORMATIVE   the regulator wrote this number. It is the rule.
    DERIVED     this package computed it from something. It is arithmetic.

The distinction is not pedantry, and this package has already been wrong about
it once. FDA states the highly-variable switching threshold as sWR = 0.294.
Notice that sqrt(ln(1 + 0.30^2)) = 0.29356..., conclude that 0.294 is that
value rounded, and prefer the exact derivation, and you have replaced the
regulator's criterion with your own arithmetic. An earlier release did exactly
that; PR #54 undid it.

The two numbers differ in the fourth decimal, and real studies fall between
them. So both are kept, both are indexed, and `test_normative_and_derived_stay_distinct`
asserts they are never equal and never collapsed into one entry.

The same pattern appears twice more. EMA states the ABEL cap as the pair
69.84-143.19%; the formula at CVwR = 50% gives a fractionally wider one, and
be-stats follows the regulator (VAL-EMA-ABEL-002). FDA states Delta = 1/0.9 in
Appendix F's prose and prints 1.11111 in the same appendix's SAS example; the
prose governs, and the example value is indexed as what it is.

WHAT IS INDEXED

Every `RegulatoryValue` reachable from `be_stats.spec`'s constant tables, plus
the acceptance limits `resolve_be_spec` constructs inline, plus every derived
quantity the package can compute. `test_every_regulatory_constant_has_provenance`
walks the spec tables and fails if one is missing here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from be_stats.dossier.citations import exception_for, is_pinned
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE,
    Citation,
    RegulatoryValue,
    VerificationStatus,
)
from be_stats.spec import (
    CONVENTIONAL_ACCEPTANCE_CITATION,
    EMA_HVD_CONSTANTS,
    FDA_HVD_CONSTANTS,
    FDA_IVPT_NOTE,
    FDA_NTI_CONSTANTS,
    FDA_NTI_SAS_EXAMPLE_DELTA,
    ema_abel_cap_computed,
    fda_hvd_theta,
    fda_nti_theta,
    fda_nti_theta_sas_example,
)


class ConstantKind(StrEnum):
    """Whether the regulator wrote the number or this package computed it."""

    #: Transcribed from a regulatory document. Never recomputed, never
    #: replaced by a mathematically near-equal expression.
    NORMATIVE = "normative"
    #: Computed by this package from normative inputs. Its trustworthiness is
    #: that of its inputs plus the derivation, and it may not stand in for a
    #: normative value it happens to approximate.
    DERIVED = "derived"
    #: Appears in a regulatory document, and not as the rule - a value printed
    #: in example code, or a rule belonging to a different context that shares
    #: a number with one that matters here. Indexed so that its presence in the
    #: source cannot be mistaken for authority over the decision path.
    ILLUSTRATIVE = "illustrative"


@dataclass(frozen=True, slots=True)
class ConstantRecord:
    """One number, with everything needed to answer 'why is this here'."""

    constant_id: str
    value: float
    kind: ConstantKind
    citation: Citation
    verification: VerificationStatus
    #: What the number does, in one sentence.
    role: str
    #: For a DERIVED value, the expression that produces it. Empty for
    #: normative values, where there is no derivation and claiming one would
    #: be the exact error this module exists to prevent.
    derivation: str = ""
    #: For a DERIVED value, the ids of the constants it is computed FROM.
    #:
    #: Ids rather than copied numbers, deliberately. A derived record that
    #: restated its inputs' values would be a second copy of a regulatory
    #: constant, which is the duplication this whole package is built to
    #: avoid - and it would go stale the first time an input was corrected.
    derived_from: tuple[str, ...] = ()
    #: Capability ids that consume it. Empty means nothing in the decision
    #: path reads it - true of every ILLUSTRATIVE entry, and asserted.
    consumed_by: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_normative(self) -> bool:
        return self.kind is ConstantKind.NORMATIVE

    @property
    def has_pinned_citation(self) -> bool:
        """Delegated to `dossier.citations`, which owns the definition.

        This property used to implement the four-field check itself, and the
        release gate implemented a WEAKER one three modules away - a non-empty
        `document_version`, which `"current"` satisfies. One concept, two
        encodings, and the weaker of them sat on the control deciding whether
        something may be called VALIDATED.
        """
        return is_pinned(self.citation)

    @property
    def citation_exception(self) -> str:
        """WHY this citation is not pinned, when it is not.

        Derived from the registry keyed by the CITATION rather than stored per
        record. The two conventional-interval limits and the `AVERAGE_BE_2X2`
        capability all reference one `Citation` object, so all three inherit
        one explanation and none of them has to name a finding id.

        It is NOT an excuse mechanism. A record carrying one is excluded from
        the pinned-citation count and appears in the findings register.
        """
        exception = exception_for(self.citation)
        return exception.explain() if exception else ""

    @property
    def document(self) -> str:
        return self.citation.document

    @property
    def section(self) -> str:
        return self.citation.section

    @property
    def document_version(self) -> str:
        return self.citation.document_version

    def explain(self) -> str:
        """One line answering 'why is this number here'."""
        where = f"{self.citation.authority} {self.citation.document}"
        if self.citation.section:
            where += f", {self.citation.section}"
        if self.citation.document_version:
            where += f" ({self.citation.document_version})"
        line = f"{self.constant_id} = {self.value} [{self.kind}] - {where}"
        if self.derivation:
            line += f"; derived as {self.derivation}"
        return f"{line}. {self.role}"


def _from_regulatory_value(
    constant_id: str,
    value: RegulatoryValue,
    *,
    role: str,
    consumed_by: tuple[str, ...] = (),
    kind: ConstantKind = ConstantKind.NORMATIVE,
    note: str = "",
) -> ConstantRecord:
    """Index an existing `RegulatoryValue` without restating its citation.

    The citation, the value and the verification status come FROM the spec
    object. Nothing here re-types them, so a correction in `spec` reaches the
    index without a second edit.
    """
    return ConstantRecord(
        constant_id=constant_id,
        value=value.value,
        kind=kind,
        citation=value.citation,
        verification=value.verification,
        role=role,
        consumed_by=consumed_by,
        note=note or value.note,
    )


# ---------------------------------------------------------- normative ---

_NORMATIVE: tuple[ConstantRecord, ...] = (
    # FDA highly variable drugs
    _from_regulatory_value(
        "FDA_HVD_CLASSIFICATION_CV",
        FDA_HVD_CONSTANTS["classification_cv"],
        role="Defines WHICH DRUGS are highly variable. Not the analysis switch.",
        consumed_by=(),
    ),
    _from_regulatory_value(
        "FDA_HVD_SWR_SWITCH",
        FDA_HVD_CONSTANTS["swr_switching_threshold"],
        role=(
            "Selects WHICH ANALYSIS applies, from the estimated sWR. At or "
            "above it, reference-scaled ABE; below it, ordinary average BE."
        ),
        consumed_by=("FDA_HVD_METHOD_SELECTION", "FDA_HVD_RSABE"),
    ),
    _from_regulatory_value(
        "FDA_HVD_SIGMA_W0",
        FDA_HVD_CONSTANTS["sigma_w0"],
        role="The reference-scaling constant in FDA's HVD criterion.",
        consumed_by=("FDA_HVD_RSABE",),
    ),
    _from_regulatory_value(
        "FDA_HVD_POINT_ESTIMATE_LOWER",
        FDA_HVD_CONSTANTS["point_estimate_lower"],
        role="Lower bound of the point-estimate constraint required in addition.",
        consumed_by=("FDA_HVD_RSABE",),
    ),
    _from_regulatory_value(
        "FDA_HVD_POINT_ESTIMATE_UPPER",
        FDA_HVD_CONSTANTS["point_estimate_upper"],
        role="Upper bound of the point-estimate constraint.",
        consumed_by=("FDA_HVD_RSABE",),
    ),
    # EMA highly variable drugs
    _from_regulatory_value(
        "EMA_ABEL_CV_THRESHOLD_PERCENT",
        EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"],
        role=(
            "Widening requires CVwR > 30 percent, STRICTLY, compared on the "
            "CV scale and never converted to an sWR boundary."
        ),
        consumed_by=("EMA_HVD_VARIABILITY_ELIGIBILITY",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_K",
        EMA_HVD_CONSTANTS["regulatory_constant_k"],
        role="The regulatory constant in [U, L] = exp(+/- k.sWR).",
        consumed_by=("EMA_ABEL_LIMIT_CALCULATION",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_CAP_CV_PERCENT",
        EMA_HVD_CONSTANTS["cap_cv_percent"],
        role="The variability at which widening stops.",
        consumed_by=("EMA_ABEL_LIMIT_CALCULATION",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_CAP_LOWER_PERCENT",
        EMA_HVD_CONSTANTS["cap_lower_percent"],
        role=(
            "The widest lower limit EMA permits, STATED by the regulator and "
            "not recomputed."
        ),
        consumed_by=("EMA_ABEL_LIMIT_CALCULATION",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_CAP_UPPER_PERCENT",
        EMA_HVD_CONSTANTS["cap_upper_percent"],
        role="The widest upper limit EMA permits, as stated.",
        consumed_by=("EMA_ABEL_LIMIT_CALCULATION",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_PE_LOWER_PERCENT",
        EMA_HVD_CONSTANTS["point_estimate_lower_percent"],
        role="The GMR constraint EMA requires in addition to the interval.",
        consumed_by=("EMA_ABEL_PE_CONSTRAINT",),
    ),
    _from_regulatory_value(
        "EMA_ABEL_PE_UPPER_PERCENT",
        EMA_HVD_CONSTANTS["point_estimate_upper_percent"],
        role="Upper bound of the same constraint.",
        consumed_by=("EMA_ABEL_PE_CONSTRAINT",),
    ),
    # FDA narrow therapeutic index
    _from_regulatory_value(
        "FDA_NTI_SIGMA_W0",
        FDA_NTI_CONSTANTS["sigma_w0"],
        role="The reference-scaling constant in FDA's NTI criterion.",
        consumed_by=("FDA_NTI_REFERENCE_SCALED_CRITERION",),
    ),
    _from_regulatory_value(
        "FDA_NTI_DELTA",
        FDA_NTI_CONSTANTS["delta"],
        role=(
            "THE NORMATIVE CONSTANT, stated in Appendix F's prose as 1/0.9 "
            "and used as theta = [ln(Delta)/sigma_W0]^2."
        ),
        consumed_by=("FDA_NTI_REFERENCE_SCALED_CRITERION",),
    ),
    _from_regulatory_value(
        "FDA_NTI_VARIANCE_RATIO_LIMIT",
        FDA_NTI_CONSTANTS["variance_ratio_upper_limit"],
        role="Criterion (c): the upper limit for sigma_WT / sigma_WR.",
        consumed_by=("FDA_NTI_VARIABILITY_RATIO",),
    ),
    _from_regulatory_value(
        "FDA_NTI_UNSCALED_LOWER_PERCENT",
        FDA_NTI_CONSTANTS["unscaled_lower_percent"],
        role="Criterion (b): the ordinary limits, which must ALSO be passed.",
        consumed_by=("FDA_NTI_UNSCALED_ABE",),
    ),
    _from_regulatory_value(
        "FDA_NTI_UNSCALED_UPPER_PERCENT",
        FDA_NTI_CONSTANTS["unscaled_upper_percent"],
        role="Upper bound of criterion (b).",
        consumed_by=("FDA_NTI_UNSCALED_ABE",),
    ),
    # The acceptance limits `resolve_be_spec` constructs inline. Indexed here
    # because a constant that never reaches a table is exactly the one a
    # provenance audit misses.
    # THE TWO RECORDS THAT ARE NOT PINNED.
    #
    # Neither carries its own explanation any more. Both reference
    # `CONVENTIONAL_ACCEPTANCE_CITATION`, and the exception is registered in
    # `dossier.citations` against that CITATION - so these two constants and
    # the `AVERAGE_BE_2X2` capability that shares it all inherit one
    # explanation, and none of them can drift from the others.
    #
    # Their VERIFIED status rests on universal agreement about the number
    # rather than on a reading of a pinned document. That is precisely why the
    # pinned-citation count excludes them: "everybody knows this" and "we read
    # it here, at this section, in this issue" are different claims, and only
    # the second is a citation.
    ConstantRecord(
        constant_id="CONVENTIONAL_LOWER_PERCENT",
        value=80.00,
        kind=ConstantKind.NORMATIVE,
        citation=CONVENTIONAL_ACCEPTANCE_CITATION,
        verification=VerificationStatus.VERIFIED,
        role=(
            "The conventional acceptance interval's lower limit, applied by "
            "both regulators for the standard case."
        ),
        consumed_by=("AVERAGE_BE_2X2",),
    ),
    ConstantRecord(
        constant_id="CONVENTIONAL_UPPER_PERCENT",
        value=125.00,
        kind=ConstantKind.NORMATIVE,
        citation=CONVENTIONAL_ACCEPTANCE_CITATION,
        verification=VerificationStatus.VERIFIED,
        role="The conventional acceptance interval's upper limit.",
        consumed_by=("AVERAGE_BE_2X2",),
    ),
    ConstantRecord(
        constant_id="EMA_NTI_NARROWED_LOWER_PERCENT",
        value=90.00,
        kind=ConstantKind.NORMATIVE,
        citation=EMA_BIOEQUIVALENCE,
        verification=VerificationStatus.VERIFIED,
        role=(
            "EMA's narrowed lower limit for the AUC of an NTI drug. EMA "
            "NARROWS where FDA ADDS criteria."
        ),
        consumed_by=("EMA_NTI_NARROW_ABE",),
    ),
    ConstantRecord(
        constant_id="EMA_NTI_NARROWED_UPPER_PERCENT",
        value=111.11,
        kind=ConstantKind.NORMATIVE,
        citation=EMA_BIOEQUIVALENCE,
        verification=VerificationStatus.VERIFIED,
        role="EMA's narrowed upper limit for the AUC of an NTI drug.",
        consumed_by=("EMA_NTI_NARROW_ABE",),
    ),
)


# ------------------------------------------------------------ derived ---
#
# Each of these is numerically CLOSE to something normative, and each one is
# the wrong number to decide with. That is why they are indexed rather than
# hidden: a value that can be computed will be computed by somebody, and the
# defence is to name it, state what it is not, and test that no decision path
# reads it.

_DERIVED: tuple[ConstantRecord, ...] = (
    ConstantRecord(
        constant_id="DERIVED_SWR_AT_CV_30",
        value=math.sqrt(math.log(1 + 0.30**2)),
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="be-stats",
            document="derived from the 30% CV classification threshold",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "The sWR corresponding exactly to a 30% CV. NOT FDA's switching "
            "threshold, which FDA states as 0.294. The two differ in the "
            "fourth decimal and studies fall between them."
        ),
        derivation="sqrt(ln(1 + FDA_HVD_CLASSIFICATION_CV^2))",
        derived_from=(
            # The same 30% CV, stated by both regulators for different
            # purposes and on different scales. Both are listed because the
            # derived value's whole significance is that it sits between them:
            # it IS EMA's threshold expressed on the sWR scale, and it is NOT
            # FDA's, which FDA states as 0.294. Naming only one input would
            # make the record read as belonging to that regulator.
            "FDA_HVD_CLASSIFICATION_CV",
            "EMA_ABEL_CV_THRESHOLD_PERCENT",
        ),
        consumed_by=(),
        note=(
            "This is the substitution PR #54 reversed. The formula consumes "
            "FDA_HVD_CLASSIFICATION_CV; EMA_ABEL_CV_THRESHOLD_PERCENT is "
            "listed as an input because it is the SAME 30% on the percent "
            "scale, stated by EMA for a different purpose. The derived value "
            "IS EMA's threshold expressed on the sWR scale, which is why "
            "EMA's comparison is made on the CV scale instead. See "
            "validation/findings/VAL-FDA-HVD-002.md."
        ),
    ),
    ConstantRecord(
        constant_id="DERIVED_FDA_HVD_THETA",
        value=fda_hvd_theta(),
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="FDA",
            document="Statistical Approaches to Establishing Bioequivalence",
            section="Appendix G (formula, not a stated number)",
            document_version="final, May 2026",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "FDA's scaled HVD limit. DERIVED legitimately: the guidance gives "
            "a formula rather than a number, so the formula is the thing to "
            "preserve and its inputs are normative."
        ),
        derivation="(ln(1.25) / FDA_HVD_SIGMA_W0)^2",
        derived_from=("FDA_HVD_SIGMA_W0", "CONVENTIONAL_UPPER_PERCENT"),
        consumed_by=("FDA_HVD_RSABE",),
        note=(
            "The 1.25 is a LITERAL in `spec.fda_hvd_theta`, not a read of "
            "CONVENTIONAL_UPPER_PERCENT. The two are the same number on "
            "different scales and the code does not link them, so the input "
            "is named here for the reader while the note records that the "
            "link is documentary rather than mechanical."
        ),
    ),
    ConstantRecord(
        constant_id="DERIVED_FDA_NTI_THETA",
        value=fda_nti_theta(),
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="FDA",
            document="Statistical Approaches to Establishing Bioequivalence",
            section="Appendix F (formula, not a stated number)",
            document_version="final, May 2026",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "FDA's scaled NTI limit, computed from the PROSE constant "
            "Delta = 1/0.9. The one the engine decides with."
        ),
        derivation="(ln(FDA_NTI_DELTA) / FDA_NTI_SIGMA_W0)^2",
        derived_from=("FDA_NTI_DELTA", "FDA_NTI_SIGMA_W0"),
        consumed_by=("FDA_NTI_REFERENCE_SCALED_CRITERION",),
    ),
    ConstantRecord(
        constant_id="DERIVED_FDA_NTI_THETA_SAS_EXAMPLE",
        value=fda_nti_theta_sas_example(),
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="FDA",
            document="Statistical Approaches to Establishing Bioequivalence",
            section="Appendix F, SAS example code",
            document_version="final, May 2026",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "Theta as Appendix F's SAS EXAMPLE would compute it, from the "
            "printed 1.11111 rather than the prose ratio. NOT the rule. "
            "Provided so the difference can be measured rather than "
            "re-derived by hand, and read by no decision path."
        ),
        derivation="(ln(FDA_NTI_SAS_EXAMPLE_DELTA) / FDA_NTI_SIGMA_W0)^2",
        derived_from=("FDA_NTI_SAS_EXAMPLE_DELTA", "FDA_NTI_SIGMA_W0"),
        consumed_by=(),
    ),
    ConstantRecord(
        constant_id="DERIVED_EMA_ABEL_CAP_LOWER_PERCENT",
        value=ema_abel_cap_computed()[0],
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="be-stats",
            document="the ABEL formula evaluated at the cap",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "The lower cap as the formula gives it. EMA STATES 69.84 and "
            "be-stats applies the stated value; this exists to be compared "
            "against it, never used."
        ),
        # CORRECTED. This read `sqrt(ln(1.25))`, which is the right NUMBER and
        # names the wrong input: the 1.25 there is not the acceptance ratio, it
        # is 1 + (50/100)^2 from the cap CV. The two coincide because the cap
        # sits at CVwR = 50%, and writing the coincidence rather than the input
        # made the record look as though the cap were derived from the
        # acceptance limits. It is not.
        derivation=(
            "100 * exp(-EMA_ABEL_K * sqrt(ln(1 + "
            "(EMA_ABEL_CAP_CV_PERCENT/100)^2)))"
        ),
        derived_from=("EMA_ABEL_K", "EMA_ABEL_CAP_CV_PERCENT"),
        consumed_by=(),
        note="See validation/findings/VAL-EMA-ABEL-002.md.",
    ),
    ConstantRecord(
        constant_id="DERIVED_EMA_ABEL_CAP_UPPER_PERCENT",
        value=ema_abel_cap_computed()[1],
        kind=ConstantKind.DERIVED,
        citation=Citation(
            authority="be-stats",
            document="the ABEL formula evaluated at the cap",
        ),
        verification=VerificationStatus.DERIVED,
        role=(
            "The upper cap as the formula gives it. EMA STATES 143.19. The "
            "stated pair is not exactly reciprocal because each limit was "
            "rounded independently."
        ),
        derivation=(
            "100 * exp(+EMA_ABEL_K * sqrt(ln(1 + "
            "(EMA_ABEL_CAP_CV_PERCENT/100)^2)))"
        ),
        derived_from=("EMA_ABEL_K", "EMA_ABEL_CAP_CV_PERCENT"),
        consumed_by=(),
    ),
)


# ------------------------------------------------------- illustrative ---

_ILLUSTRATIVE: tuple[ConstantRecord, ...] = (
    _from_regulatory_value(
        "FDA_NTI_SAS_EXAMPLE_DELTA",
        FDA_NTI_SAS_EXAMPLE_DELTA,
        kind=ConstantKind.ILLUSTRATIVE,
        role=(
            "The five-decimal approximation printed in Appendix F's SAS "
            "example. The normative value is the prose ratio 1/0.9."
        ),
        consumed_by=(),
    ),
    _from_regulatory_value(
        "FDA_IVPT_SWR_THRESHOLD",
        FDA_IVPT_NOTE,
        kind=ConstantKind.ILLUSTRATIVE,
        role=(
            "The SAME NUMBER as FDA's HVD switch, in section III.A, governing "
            "in vitro permeation testing with the OPPOSITE inequality. "
            "Indexed so that finding 0.294 in the guidance is not by itself "
            "evidence about which rule applies."
        ),
        consumed_by=(),
    ),
)


#: The full index, keyed by `constant_id`.
CONSTANT_INDEX: dict[str, ConstantRecord] = {
    record.constant_id: record
    for record in (*_NORMATIVE, *_DERIVED, *_ILLUSTRATIVE)
}


def constant(constant_id: str) -> ConstantRecord:
    """One record, or a KeyError naming what is available."""
    try:
        return CONSTANT_INDEX[constant_id]
    except KeyError:
        raise KeyError(
            f"No constant {constant_id!r}. Known: "
            f"{', '.join(sorted(CONSTANT_INDEX))}"
        ) from None


def constants_of_kind(kind: ConstantKind) -> list[ConstantRecord]:
    return [r for r in CONSTANT_INDEX.values() if r.kind is kind]


def provenance_coverage() -> dict[str, int]:
    """Coverage, split so that each number means one thing.

    A CORRECTION THIS FUNCTION EXISTS TO PREVENT REPEATING

    An earlier version returned `total`, `verified`, `derived` and
    `unverified`, and the report built on it said "29/29 carry document,
    section and version". That was false, and the shape of the data made it
    easy to say: nothing here counted SECTIONS, so a reader summarising the
    output could reach for the strongest available reading and find nothing
    contradicting it.

    Three of the six derived records intentionally carry no regulatory
    section - `be-stats` computed them and no regulator states them - and two
    NORMATIVE records were not pinned to a section at all, which is a real gap
    the old shape hid.

    So the metrics are now split by kind, and each denominator is the set the
    requirement actually applies to. Counts and not percentages, because "94%"
    with no denominator is a number nobody can check.
    """
    normative = constants_of_kind(ConstantKind.NORMATIVE)
    derived = constants_of_kind(ConstantKind.DERIVED)
    illustrative = constants_of_kind(ConstantKind.ILLUSTRATIVE)

    return {
        # ---- every constant, whatever its kind ----
        "total": len(CONSTANT_INDEX),
        #: authority, a source label, a role and a verification classification.
        #: The floor every record clears.
        "classified": sum(
            1
            for r in CONSTANT_INDEX.values()
            if r.citation.authority and r.citation.document and r.role
        ),
        # ---- normative: the regulator wrote the number ----
        "normative": len(normative),
        #: authority AND document AND section AND version, none empty.
        "normative_pinned": sum(1 for r in normative if r.has_pinned_citation),
        #: Not pinned, and saying why. Outstanding work, not an exemption.
        "normative_exceptions": sum(
            1 for r in normative if not r.has_pinned_citation
        ),
        "normative_verified": sum(
            1
            for r in normative
            if r.verification is VerificationStatus.VERIFIED
        ),
        # ---- derived: this package computed it ----
        "derived": len(derived),
        "derived_with_derivation": sum(1 for r in derived if r.derivation),
        "derived_with_inputs": sum(1 for r in derived if r.derived_from),
        "derived_status": sum(
            1
            for r in derived
            if r.verification is VerificationStatus.DERIVED
        ),
        # ---- illustrative: in the document, and not the rule ----
        "illustrative": len(illustrative),
        "illustrative_unconsumed": sum(
            1 for r in illustrative if not r.consumed_by
        ),
    }


def unpinned_normative_constants() -> list[ConstantRecord]:
    """Normative constants without a full citation, each with its stated why.

    Surfaced as its own function so the gap can be printed rather than
    inferred from a shortfall between two counts.
    """
    return [
        r
        for r in constants_of_kind(ConstantKind.NORMATIVE)
        if not r.has_pinned_citation
    ]


def derivation_inputs(constant_id: str) -> list[ConstantRecord]:
    """The normative records a derived value is computed from.

    Answers "what normative inputs produced this?" by resolving ids, so no
    numerical constant is ever copied into a derived record.
    """
    return [CONSTANT_INDEX[i] for i in constant(constant_id).derived_from]
