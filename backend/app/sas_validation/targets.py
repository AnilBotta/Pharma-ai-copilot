"""Predefined validation targets, and the evidence status of every number in them.

WHY EACH REFERENCE VALUE CARRIES ITS OWN PROVENANCE

The partial-replicate target exists to settle a question three pull requests
failed to settle, and it will be looked at by someone deciding whether an
oracle is closed. That person must be able to see, without reading a finding,
which of the numbers on the screen came from a regulator and which came from
software.

So a reference value is never a bare float. It carries what published it and
how far that goes:

    REGULATOR_PUBLISHED        EMA printed this, to the precision shown
    INDEPENDENT_CANDIDATE      our own independent derivation, corroborated
                               but not regulator-confirmed
    EXTERNAL_IMPLEMENTATION    another package's output, not confirmed either

The comparison is run against the INCOMING SAS RESULT NEUTRALLY. These values
are investigation context displayed beside it, never a target to match and
never a pass criterion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EvidenceStatus(StrEnum):
    REGULATOR_PUBLISHED = "regulator_published"
    INDEPENDENT_CANDIDATE = "independent_candidate"
    EXTERNAL_IMPLEMENTATION = "external_implementation"


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    quantity: str
    value: float | None
    status: EvidenceStatus
    source: str
    note: str = ""

    @property
    def is_regulator_confirmed(self) -> bool:
        return self.status is EvidenceStatus.REGULATOR_PUBLISHED


@dataclass(frozen=True, slots=True)
class ValidationTarget:
    """A dataset plus the model to fit to it, and why anyone cares."""

    case_id: str
    title: str
    regulatory_method: str
    design: str
    dataset_source: str
    purpose: str
    references: tuple[ReferenceValue, ...] = field(default_factory=tuple)
    #: What a reviewer is being asked to decide. Not what the software decides.
    reviewer_question: str = ""

    def regulator_published(self) -> tuple[ReferenceValue, ...]:
        return tuple(r for r in self.references if r.is_regulator_confirmed)

    def unconfirmed(self) -> tuple[ReferenceValue, ...]:
        return tuple(r for r in self.references if not r.is_regulator_confirmed)


APPENDIX_C_PARTIAL_EMA_DATASET_II = ValidationTarget(
    case_id="FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II",
    title="FDA Appendix C on a partial replicate design - EMA Data set II",
    regulatory_method="fda_replicate_standard_abe_partial",
    design="2x3x3 partial replicate (TRR / RTR / RRT), 24 subjects, 72 observations",
    dataset_source=(
        "EMA/618604/2008 Rev. 13, PKWP Q&A annex, Data set II. The same raw "
        "data EMA analysed with SAS 9.1 for its Method C column."
    ),
    purpose=(
        "Resolve the standing partial-replicate denominator degrees of freedom "
        "blocker recorded in VAL-FDA-APPENDIX-C-PARTIAL-001. A licensed SAS "
        "PROC MIXED run reporting the denominator df directly is the one piece "
        "of evidence that would close it."
    ),
    reviewer_question=(
        "Does this SAS output, from a named SAS version on the shipped dataset "
        "and the shipped program, establish the denominator df for the "
        "rank-deficient partial-replicate case? Agreement with any number "
        "below is not by itself an answer."
    ),
    references=(
        ReferenceValue(
            quantity="estimate_percent",
            value=102.26,
            status=EvidenceStatus.REGULATOR_PUBLISHED,
            source="EMA/618604/2008 Rev. 13, Method C",
            note="Printed to two decimals.",
        ),
        ReferenceValue(
            quantity="ci_lower_percent",
            value=97.05,
            status=EvidenceStatus.REGULATOR_PUBLISHED,
            source="EMA/618604/2008 Rev. 13, Method C",
            note="Printed to two decimals.",
        ),
        ReferenceValue(
            quantity="ci_upper_percent",
            value=107.76,
            status=EvidenceStatus.REGULATOR_PUBLISHED,
            source="EMA/618604/2008 Rev. 13, Method C",
            note="Printed to two decimals.",
        ),
        ReferenceValue(
            quantity="standard_error",
            value=None,
            status=EvidenceStatus.REGULATOR_PUBLISHED,
            source="EMA/618604/2008 Rev. 13, Method C",
            note=(
                "NOT PUBLISHED. EMA prints no standard error for this data "
                "set, which is why the denominator df could not be recovered "
                "from the published output alone."
            ),
        ),
        ReferenceValue(
            quantity="denominator_df",
            value=None,
            status=EvidenceStatus.REGULATOR_PUBLISHED,
            source="EMA/618604/2008 Rev. 13, Method C",
            note="NOT PUBLISHED. This is the quantity the SAS run is for.",
        ),
        ReferenceValue(
            quantity="denominator_df",
            value=19.8906,
            status=EvidenceStatus.INDEPENDENT_CANDIDATE,
            source=(
                "be-stats validation/external/independent_satterthwaite.py, "
                "observed information with rank-1 boundary reduction "
                "(VAL-FDA-APPENDIX-C-PARTIAL-001)"
            ),
            note=(
                "BEST-SUPPORTED INDEPENDENT CANDIDATE - NOT REGULATOR-CONFIRMED. "
                "It reproduces EMA's published interval at the printed "
                "precision, which is strong corroboration and not proof that "
                "SAS DDFM=SATTERTH uses this construction."
            ),
        ),
        ReferenceValue(
            quantity="denominator_df",
            value=22.5403,
            status=EvidenceStatus.EXTERNAL_IMPLEMENTATION,
            source="ReplicateBE.jl 1.0.15 on Julia 1.10.5",
            note=(
                "EXTERNAL IMPLEMENTATION RESULT - NOT REGULATOR-CONFIRMED. Its "
                "estimate and standard error agree with every other engine "
                "tried; under that corroborated standard error this df falls "
                "outside the range compatible with EMA's published interval. "
                "The package's own stated scope covers two-sequence full "
                "replicate designs, not this three-sequence partial replicate."
            ),
        ),
    ),
)


TARGETS: dict[str, ValidationTarget] = {
    APPENDIX_C_PARTIAL_EMA_DATASET_II.case_id: APPENDIX_C_PARTIAL_EMA_DATASET_II,
}


def get_target(case_id: str) -> ValidationTarget:
    try:
        return TARGETS[case_id]
    except KeyError:
        raise KeyError(
            f"unknown validation case {case_id!r}. Known: {sorted(TARGETS)}"
        ) from None


__all__ = [
    "APPENDIX_C_PARTIAL_EMA_DATASET_II",
    "TARGETS",
    "EvidenceStatus",
    "ReferenceValue",
    "ValidationTarget",
    "get_target",
]
