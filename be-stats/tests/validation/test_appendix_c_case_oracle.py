"""The nine synthetic cases against ReplicateBE.jl.

TIER 3. AN IMPLEMENTATION, NOT A REGULATOR.

ReplicateBE.jl earned its place as an oracle in PR #61 by reproducing EMA's
published SAS Method C output exactly on the fully replicate design - estimate,
90% interval and both within-subject CVs. That is the whole basis for trusting
it, and it extends exactly as far as it was tested: fully replicate only. It is
NOT used here for partial replicate, where PR #61 measured it disagreeing with
the published result by 2.94 denominator df.

WHAT THIS ADDS THAT DATA SET I CANNOT

Data set I is one point, and an unusual one - it sits on the correlation
boundary, which is where the only disagreement between the two implementations
lives. These cases put the comparison at eight further points, including four
where the confidence limit falls two hundredths of a percentage point either
side of an acceptance limit.

THE TOLERANCE IS ONE NUMBER, AND IT IS THE ONE THAT MATTERS

Estimate, standard error and denominator df are not independently interesting -
they exist to produce a confidence interval, and only the interval decides
anything. So the tolerance is stated once, on the interval:

    the two implementations' 90% limits must agree to 0.01 percentage points

That is five times finer than the rounding in every published figure this
package is checked against, and around two thousand times finer than the
margin that separates a pass from a fail in cases F to I. It also avoids the
trap of picking three separate tolerances and then discovering that a df
difference which looked negligible in isolation was not.

Each quantity is still compared individually, so a failure says WHICH one
moved - but those comparisons are diagnostic, and the interval is the gate.

ORIENTATION IS RESOLVED ONCE, FOR ALL NINE CASES TOGETHER

ReplicateBE sorts the formulation levels, so its coefficient may be R - T. The
Julia script deliberately does not choose; it emits the raw coefficient. Here a
SINGLE global sign is determined and required to hold for every case. Choosing
per case would be circular - it would guarantee agreement on the sign no matter
how wrong the fit - whereas nine cases agreeing on one sign is evidence.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest
from scipy import stats

from be_stats.appendix_c import (
    ALPHA,
    AppendixCDataset,
    fit_appendix_c,
)
from be_stats.replicate import (
    ReplicateObservation,
    parse_sequence,
    parse_treatment,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads(
    (ROOT / "validation/appendix_c/cases/full_replicate_cases.json").read_text(
        "utf-8"
    )
)["cases"]

#: CI points this at the run it just produced, so the job compares against a
#: LIVE oracle rather than against a file that could have been committed stale.
#: Locally it falls back to the committed frozen run.
FROZEN = Path(
    os.environ.get(
        "BE_STATS_APPENDIX_C_CASE_ORACLE",
        ROOT / "validation/appendix_c/oracle/replicatebe_cases_frozen.json",
    )
)

#: The gate. Percentage points on each confidence limit.
CI_TOLERANCE_PERCENT = 0.01

pytestmark = pytest.mark.skipif(
    not FROZEN.exists(),
    reason=(
        f"no ReplicateBE.jl case oracle at {FROZEN}. Julia runs in the pinned "
        "validation image, not on a developer machine; the validation-r "
        "workflow produces this file and FAILS if these comparisons skip."
    ),
)


def oracle() -> dict:
    return json.loads(FROZEN.read_text("utf-8"))


def observations(key: str) -> list[ReplicateObservation]:
    return [
        ReplicateObservation(
            subject_id=str(row["subject"]),
            sequence=parse_sequence(row["sequence"]),
            period=row["period"],
            treatment=parse_treatment(row["treatment"]),
            endpoint="Cmax",
            value=row["value"],
        )
        for row in CASES[key]["observations"]
    ]


def fit(key: str):
    return fit_appendix_c(AppendixCDataset.build(observations(key)))


def interval_percent(estimate: float, standard_error: float, df: float):
    half_width = float(stats.t.ppf(1.0 - ALPHA, df)) * standard_error
    return (
        100.0 * math.exp(estimate - half_width),
        100.0 * math.exp(estimate + half_width),
    )


def fitted_cases() -> dict[str, dict]:
    """Only cases ReplicateBE actually fitted. Never silently - see below."""
    return {
        key: case
        for key, case in oracle()["cases"].items()
        if case.get("status") == "FITTED"
    }


def global_orientation() -> float:
    """+1 or -1, decided once, on the whole set.

    Chosen as the sign that agrees with this package on the MAJORITY of cases,
    then required (by the test below) to agree on ALL of them. If the two
    disagreed on orientation for some cases and not others, no single sign
    would work and that test fails - which is the outcome that should follow,
    rather than nine locally convenient choices papering over it.
    """
    agree = 0
    for key, case in fitted_cases().items():
        if math.copysign(1.0, case["estimate_raw"]) == math.copysign(
            1.0, fit(key).estimate
        ):
            agree += 1
    return 1.0 if agree * 2 >= len(fitted_cases()) else -1.0


# --------------------------------------------------------------- the gate ---


def test_every_case_was_fitted_by_the_oracle():
    """A case the oracle could not fit is unresolved, never agreement.

    Case E sits on the correlation boundary, and ReplicateBE parameterises the
    correlation through a link that sends its parameter to infinity there. It
    may legitimately fail to converge. If it does, that is a finding about the
    two parameterisations - and it must not be reachable by the comparison
    tests below quietly passing over a missing case.
    """
    cases = oracle()["cases"]
    assert set(cases) == set(CASES)

    not_fitted = {
        key: case.get("status") for key, case in cases.items()
        if case.get("status") != "FITTED"
    }
    assert not not_fitted, (
        f"the oracle did not fit {not_fitted}. Record this in "
        "VAL-FDA-APPENDIX-C-003 rather than loosening a tolerance."
    )


@pytest.mark.parametrize("key", sorted(CASES))
def test_the_confidence_interval_agrees_with_the_oracle(key: str):
    """The comparison that decides. Both limits, 0.01 percentage points."""
    case = oracle()["cases"][key]
    if case.get("status") != "FITTED":
        pytest.fail(f"case {key} was not fitted by the oracle: {case.get('status')}")

    f = fit(key)
    ours = interval_percent(f.estimate, f.standard_error, f.degrees_of_freedom)
    theirs = interval_percent(
        global_orientation() * case["estimate_raw"],
        case["standard_error"],
        case["denominator_df"],
    )

    assert ours[0] == pytest.approx(theirs[0], abs=CI_TOLERANCE_PERCENT)
    assert ours[1] == pytest.approx(theirs[1], abs=CI_TOLERANCE_PERCENT)


# -------------------------------------------------------------- diagnostic ---


def test_a_single_orientation_works_for_every_case():
    """One sign for all nine, or the comparison is not a comparison."""
    sign = global_orientation()
    for key, case in fitted_cases().items():
        assert math.copysign(1.0, sign * case["estimate_raw"]) == math.copysign(
            1.0, fit(key).estimate
        ), f"case {key} needs the opposite orientation to the rest"


@pytest.mark.parametrize("key", sorted(CASES))
def test_the_point_estimate_agrees(key: str):
    case = oracle()["cases"][key]
    if case.get("status") != "FITTED":
        pytest.skip("covered by test_every_case_was_fitted_by_the_oracle")
    assert fit(key).estimate == pytest.approx(
        global_orientation() * case["estimate_raw"], abs=1e-6
    )


@pytest.mark.parametrize("key", sorted(CASES))
def test_the_standard_error_agrees(key: str):
    case = oracle()["cases"][key]
    if case.get("status") != "FITTED":
        pytest.skip("covered by test_every_case_was_fitted_by_the_oracle")
    assert fit(key).standard_error == pytest.approx(
        case["standard_error"], rel=1e-4
    )


@pytest.mark.parametrize("key", sorted(CASES))
def test_the_denominator_df_agrees_within_its_decision_impact(key: str):
    """df is compared through what it does, not as a number in its own right.

    A df difference matters only through the t quantile it selects, and the
    same absolute difference means very different things at 22 df and at 208.
    So the assertion is on the quantile: 1e-3 relative, which moves a
    confidence limit by well under the 0.01 percentage points the gate allows.

    The raw difference is reported alongside it, because the SIZE of the
    difference is the evidence for where it comes from. On Data set I it is
    0.35 df at the boundary; if the interior cases here agree to machine
    precision and only case E does not, the boundary explanation is confirmed.
    """
    case = oracle()["cases"][key]
    if case.get("status") != "FITTED":
        pytest.skip("covered by test_every_case_was_fitted_by_the_oracle")

    ours = fit(key).degrees_of_freedom
    theirs = case["denominator_df"]
    q_ours = float(stats.t.ppf(1.0 - ALPHA, ours))
    q_theirs = float(stats.t.ppf(1.0 - ALPHA, theirs))

    assert q_ours == pytest.approx(q_theirs, rel=1e-3), (
        f"df {ours:.4f} against {theirs:.4f} (difference {ours - theirs:+.4f})"
    )


def test_the_oracle_records_what_it_is_and_which_version_produced_it():
    """A comparison whose provenance is missing is not usable as evidence."""
    payload = oracle()
    assert payload["oracle"]["package"] == "ReplicateBE.jl"
    assert payload["oracle"]["version_pinned"] == "1.0.15"
    assert payload["oracle"]["julia_version"]
    assert "3" in payload["tier"]

    # Located by name, not by proximity to the expected value - the circularity
    # PR #61 caught and rejected.
    for key, case in fitted_cases().items():
        assert "name:" in case["coefficient_located_by"], (
            f"case {key} fell back to positional lookup: "
            f"{case['coefficient_located_by']}"
        )
