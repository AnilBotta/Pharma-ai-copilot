"""A near miss for FDA NTI tier 1B, reproduced and recorded - NOT adopted.

WHAT THIS FILE IS

FDA's Drug Topics presentation on generic narrow therapeutic index drugs
prints, on slide 24, the reference-scaled BE limits the NTI procedure implies at
several reference within-subject CVs. It is the only numerical NTI table the
recorded search found in FDA material, so it is exactly the document the next
person will find again and be tempted to promote.

This file reproduces the table from the package's own constants and states,
as assertions, the three reasons it is not tier-1B evidence. The rejection is
in `dossier.evidence_search.FDA_NTI_TIER_1B_SEARCH`; this is the arithmetic
that rejection rests on.

WHAT THE TABLE ACTUALLY IS

Under Appendix F the scaled criterion (mu_T - mu_R)^2 <= theta * sigma_WR^2 is
equivalent, at the population level, to |ln GMR| <= sqrt(theta) * sigma_WR,
i.e. limits exp(+/- sqrt(theta) * sWR). Those are a function of two constants
and a CV - no dataset, no estimate, no confidence bound. Reproducing them checks
theta and the CV-to-sWR conversion, and nothing about the procedure applied to
data.
"""

from __future__ import annotations

import math

import pytest

from be_stats import CAPABILITY_VALIDATION, VALIDATION, Capability, Method
from be_stats.conversions import cv_to_log_sd
from be_stats.dossier.evidence import EVIDENCE_MANIFEST
from be_stats.dossier.evidence_search import (
    FDA_NTI_TIER_1B_SEARCH,
    SearchVerdict,
    adopted_sources,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import ValidationStatus
from be_stats.spec import (
    FDA_NTI_CONSTANTS,
    FDA_NTI_SAS_EXAMPLE_DELTA,
    fda_nti_theta,
    fda_nti_theta_sas_example,
)

#: Slide 24, as printed: CVwR percent -> (lower, upper) percent.
PRINTED: dict[float, tuple[float, float]] = {
    5.0: (94.87, 105.41),
    10.0: (90.02, 111.08),
    15.0: (85.35, 117.02),
    20.0: (81.17, 123.20),
}
#: "> 21.42" - where the scaled limits reach the unscaled 80.00-125.00%.
PRINTED_CROSSOVER_CV_PERCENT = 21.42

#: The one printed value that does not reproduce. Named rather than skipped.
NON_REPRODUCING = (15.0, "lower")


def scaled_limits(cv_percent: float, theta: float) -> tuple[float, float]:
    half_width = math.sqrt(theta) * cv_to_log_sd(cv_percent / 100.0)
    return 100.0 * math.exp(-half_width), 100.0 * math.exp(half_width)


def _cases():
    for cv, (lower, upper) in PRINTED.items():
        for side, printed in (("lower", lower), ("upper", upper)):
            if (cv, side) == NON_REPRODUCING:
                continue
            yield pytest.param(cv, side, printed, id=f"cv{cv:g}-{side}")


@pytest.mark.parametrize("cv,side,printed", list(_cases()))
def test_seven_printed_limits_reproduce_from_the_constants(cv, side, printed):
    lower, upper = scaled_limits(cv, fda_nti_theta())
    computed = lower if side == "lower" else upper
    assert round(computed, 2) == pytest.approx(printed, abs=1e-9), (
        f"CVwR {cv}% {side}: computed {computed:.4f}, printed {printed}"
    )


def test_the_crossover_to_the_unscaled_limits_reproduces():
    """'>21.42': where exp(sqrt(theta) * sWR) reaches 1.25."""
    swr = math.log(1.25) / math.sqrt(fda_nti_theta())
    cv_percent = 100.0 * math.sqrt(math.expm1(swr**2))
    assert round(cv_percent, 2) == PRINTED_CROSSOVER_CV_PERCENT


def test_the_one_row_that_does_not_reproduce_is_internally_inconsistent():
    """Reason (3). Recorded, not corrected.

    The limits are reciprocal by construction, so the printed upper limit fixes
    the lower one. 117.02 implies 85.46; the constants give 85.46; the slide
    prints 85.35. The table disagrees with itself before it disagrees with
    anything here, and choosing which printed number to believe would be
    inferring an expected value rather than reproducing one - the GL52 lesson.
    """
    lower, _ = scaled_limits(15.0, fda_nti_theta())
    printed_lower, printed_upper = PRINTED[15.0]

    assert round(lower, 2) == 85.46
    assert round(lower, 2) != printed_lower
    assert round(10_000.0 / printed_upper, 2) == 85.46, (
        "the printed upper limit's reciprocal also gives 85.46"
    )


def test_the_table_cannot_adjudicate_the_normative_delta():
    """Part of reason (2), and the reason it is no help on the one open point.

    The normative Delta is 1/0.9; Appendix F's SAS prints 1.11111. If the table
    distinguished them it would at least bear on that choice. It does not: both
    constants give every printed value identically at two decimals.
    """
    assert FDA_NTI_CONSTANTS["delta"].value == 1.0 / 0.9
    assert FDA_NTI_SAS_EXAMPLE_DELTA.value == 1.11111

    for cv in (*PRINTED, PRINTED_CROSSOVER_CV_PERCENT):
        normative = scaled_limits(cv, fda_nti_theta())
        example = scaled_limits(cv, fda_nti_theta_sas_example())
        assert [round(v, 2) for v in normative] == [round(v, 2) for v in example]


def test_it_is_recorded_as_a_rejected_near_miss_and_not_adopted():
    matches = [s for s in FDA_NTI_TIER_1B_SEARCH if "Drug Topics" in s.document]
    assert len(matches) == 1
    source = matches[0]

    assert source.verdict is SearchVerdict.NUMBERS_OUT_OF_SCOPE
    assert "speaker" in source.rejected_because
    assert "85.35" in source.rejected_because
    assert "no issue date" in source.document_version, (
        "the date is not inferred from anywhere but the document"
    )
    assert adopted_sources(FDA_NTI_TIER_1B_SEARCH) == []


def test_reproducing_the_table_promotes_nothing():
    """No tier-1B record names the NTI method, and no status moved."""
    for record in EVIDENCE_MANIFEST:
        if record.tier is EvidenceTier.TIER_1B:
            assert "FDA_NTI_RSABE" not in record.capabilities, record.evidence_id

    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    for capability in Capability:
        if capability.name.startswith("FDA_NTI"):
            assert CAPABILITY_VALIDATION[capability] is not ValidationStatus.VALIDATED
