"""The nine synthetic cases against ReplicateBE.jl.

TIER 3. AN IMPLEMENTATION, NOT A REGULATOR.

ReplicateBE.jl earned its place as an oracle in PR #61 by reproducing EMA's
published SAS Method C output exactly on the fully replicate design - estimate,
90% interval and both within-subject CVs. That is the whole basis for trusting
it, and it extends exactly as far as it was tested.

WHAT THE FIRST RUN FOUND, AND WHY IT IS NOT A LOOSENED TOLERANCE

Seven of the nine cases agree to six decimal places on all five covariance
parameters, the standard error and the denominator df. Two do not, and they are
exactly the two where this package fits a NEGATIVE subject-by-formulation
correlation:

    case   be-stats rho     ReplicateBE rho      SE difference
    B         -0.0226           7.0e-14              +0.94%
    D         -0.0966           2.4e-15              +3.16%
    all others  >= 0         agrees to 1e-6          <0.01%

Those two oracle values are not small; they are ZERO AS A LINK FUNCTION CAN
EXPRESS IT. ReplicateBE parameterises the correlation through `rholink =
:psigmoid`, whose range excludes negative values, so reaching zero requires
sending its parameter to minus infinity - and 1e-14 is what the optimiser
returns when it tries. Two unrelated datasets landing fourteen orders of
magnitude below every other case is a parameter running to its limit, not a
coincidence.

FDA's model has no such limit. `FA0(2)` is `G = LL'` with
`L = [[l11, 0], [l21, l22]]`, giving `sigma_BTBR = l11*l21` - and `l21` is
unconstrained in sign. A negative subject-by-formulation covariance is INSIDE
the model FDA specifies and outside the oracle's parameterisation.

FDA's model can. `FA0(2)` is `G = LL'` with `L = [[l11, 0], [l21, l22]]`, giving
`sigma_BTBR = l11*l21` - and `l21` is unconstrained in sign. A negative
subject-by-formulation covariance is INSIDE the model FDA specifies and outside
the oracle's parameterisation.

AND THE DISAGREEMENT IS ADJUDICATED, NOT ASSUMED

Case D is balanced, complete and interior, so the identity in
`test_appendix_c_synthetic_cases.py` applies: the classical subject-level
analysis - no mixed model, no REML, no optimiser - gives a standard error of
0.12720778. This package gives 0.12720778. ReplicateBE gives 0.12331506.

So the two excluded cases are excluded because the oracle demonstrably cannot
represent them, established from the ORACLE'S OWN reported parameters and
confirmed by a third route that shares code with neither. Cases are never
dropped because a comparison failed; the exclusion criterion is checked below
rather than asserted, and it would stop excluding them the moment ReplicateBE
reported a negative rho.

WHAT CASE E SETTLED

PR #61 left the 0.35 df difference on EMA Data set I unexplained, with the
boundary as the leading hypothesis. Case E is the synthetic boundary case, and
it behaves identically: 111.3107 against 111.6010, a difference of 0.29 df at
rho = 1, while every interior case agrees to four decimal places. The
hypothesis is confirmed - the difference is how the two parameterisations take
the same limit, and it appears only at the limit.

THE TOLERANCE IS ONE NUMBER, AND IT IS THE ONE THAT MATTERS

Estimate, standard error and denominator df exist to produce a confidence
interval, and only the interval decides anything. So the gate is stated once,
on the interval: the two implementations' 90% limits must agree to 0.01
percentage points. Each quantity is still compared individually so a failure
says WHICH one moved, but those comparisons are diagnostic.
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
#: Locally it falls back to the committed run.
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


def oracle_rho(case: dict) -> float:
    """ReplicateBE stores theta as (s2_WR, s2_WT, s2_BR, s2_BT, rho)."""
    return float(case["theta"][4])


#: What counts as "the link ran to its limit". Every genuine correlation in
#: this case set is above 0.38; the two pinned ones are below 1e-13. Any
#: threshold between those separates them, and 1e-9 is nowhere near either.
PINNED_AT_ZERO = 1e-9

#: And what counts as a negative correlation on this side - comfortably clear
#: of an interior fit that merely landed near zero.
CLEARLY_NEGATIVE = -1e-6


def oracle_cannot_represent(key: str) -> bool:
    """Is this a fit the oracle's parameterisation excludes?

    A property of the two FITS, never of whether a comparison passed. BOTH
    conditions are required: this package puts the correlation clearly below
    zero, AND the oracle's correlation has collapsed to the limit of its link.
    A case where the oracle simply happened to fit a small positive correlation
    would still be compared.
    """
    case = oracle()["cases"].get(key, {})
    if case.get("status") != "FITTED":
        return False
    return (
        fit(key).subject_correlation < CLEARLY_NEGATIVE
        and abs(oracle_rho(case)) < PINNED_AT_ZERO
    )


#: Resolved once at collection time so the parametrisation is stable.
EXCLUDED = tuple(sorted(k for k in CASES if FROZEN.exists() and oracle_cannot_represent(k)))
COMPARABLE = tuple(sorted(set(CASES) - set(EXCLUDED)))


def fitted_cases() -> dict[str, dict]:
    return {
        key: case
        for key, case in oracle()["cases"].items()
        if case.get("status") == "FITTED"
    }


def global_orientation() -> float:
    """+1 or -1, decided once, on the whole set.

    Chosen as the sign agreeing with this package on the majority of cases,
    then required to agree on ALL of them. Choosing per case would guarantee
    agreement on the sign however wrong the fit.
    """
    agree = sum(
        math.copysign(1.0, case["estimate_raw"])
        == math.copysign(1.0, fit(key).estimate)
        for key, case in fitted_cases().items()
    )
    return 1.0 if agree * 2 >= len(fitted_cases()) else -1.0


# ---------------------------------------------- the exclusion, established ---


def test_the_oracle_fitted_every_case():
    """A case the oracle could not FIT at all is unresolved, never agreement.

    Distinct from the exclusion below: these two fitted, converged and reported
    parameters. They just reported a rho the model permits and their
    parameterisation does not.
    """
    cases = oracle()["cases"]
    assert set(cases) == set(CASES)

    not_fitted = {
        key: case.get("status")
        for key, case in cases.items()
        if case.get("status") != "FITTED"
    }
    assert not not_fitted, (
        f"the oracle did not fit {not_fitted}. Record it in "
        "VAL-FDA-APPENDIX-C-003 rather than loosening a tolerance."
    )


def test_the_oracle_pins_rho_at_zero_for_exactly_the_negative_cases():
    """The exclusion criterion, measured rather than assumed.

    Two claims, and the second is what makes the first non-circular:

      - for every case where this package fits rho < 0, the oracle's rho has
        collapsed below 1e-13 - its link's limit, on two unrelated datasets
      - for every case where this package fits rho >= 0, the oracle agrees to
        1e-6

    A parameterisation that merely disagreed would not produce that pattern. A
    constrained one produces exactly it. The separation is fourteen orders of
    magnitude wide, so nothing here depends on where the threshold is put.
    """
    for key, case in fitted_cases().items():
        ours = fit(key).subject_correlation
        theirs = oracle_rho(case)
        if ours < CLEARLY_NEGATIVE:
            assert abs(theirs) < PINNED_AT_ZERO, (
                f"case {key}: be-stats rho {ours:+.6f}, oracle {theirs:+.6g} - "
                "the oracle is no longer pinned at its limit, so this case "
                "should be compared rather than excluded"
            )
        else:
            assert theirs == pytest.approx(ours, abs=1e-6), key


def test_exactly_the_pinned_cases_are_excluded():
    """No case is excluded for any other reason, and none is excluded silently."""
    assert set(EXCLUDED) == {"B", "D"}
    assert len(COMPARABLE) == 7
    assert set(COMPARABLE) | set(EXCLUDED) == set(CASES)
    for key in EXCLUDED:
        assert fit(key).subject_correlation < CLEARLY_NEGATIVE
        assert abs(oracle_rho(oracle()["cases"][key])) < PINNED_AT_ZERO


@pytest.mark.parametrize("key", ["D"])
def test_a_third_route_adjudicates_the_excluded_case(key: str):
    """Case D is decided by an analysis that shares code with neither side.

    It is balanced, complete and interior, so the classical subject-level
    analysis applies - and that analysis contains no mixed model, no REML and
    no optimiser. It agrees with this package to eight decimal places and
    differs from the oracle by 3.2%.

    Without this the exclusion would rest on reading ReplicateBE's source. With
    it, the exclusion rests on a number.

    (Case B is incomplete, so the identity does not apply and no third route
    exists for it. Its exclusion rests on the same pinned rho and on the
    pattern being established across both.)
    """
    from tests.validation.test_appendix_c_synthetic_cases import (
        classical_subject_level,
    )

    _, classical_se, _ = classical_subject_level(key)
    ours = fit(key).standard_error
    theirs = oracle()["cases"][key]["standard_error"]

    assert ours == pytest.approx(classical_se, abs=1e-8)
    assert abs(theirs - classical_se) / classical_se > 0.01


# --------------------------------------------------------------- the gate ---


@pytest.mark.parametrize("key", COMPARABLE)
def test_the_confidence_interval_agrees_with_the_oracle(key: str):
    """The comparison that decides. Both limits, 0.01 percentage points."""
    case = oracle()["cases"][key]
    f = fit(key)

    half = float(stats.t.ppf(1.0 - ALPHA, f.degrees_of_freedom)) * f.standard_error
    ours = (
        100.0 * math.exp(f.estimate - half),
        100.0 * math.exp(f.estimate + half),
    )

    estimate = global_orientation() * case["estimate_raw"]
    their_half = (
        float(stats.t.ppf(1.0 - ALPHA, case["denominator_df"]))
        * case["standard_error"]
    )
    theirs = (
        100.0 * math.exp(estimate - their_half),
        100.0 * math.exp(estimate + their_half),
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


@pytest.mark.parametrize("key", COMPARABLE)
def test_the_point_estimate_agrees(key: str):
    assert fit(key).estimate == pytest.approx(
        global_orientation() * oracle()["cases"][key]["estimate_raw"], abs=1e-6
    )


@pytest.mark.parametrize("key", COMPARABLE)
def test_the_standard_error_agrees(key: str):
    assert fit(key).standard_error == pytest.approx(
        oracle()["cases"][key]["standard_error"], rel=1e-4
    )


@pytest.mark.parametrize("key", COMPARABLE)
def test_all_five_covariance_parameters_agree(key: str):
    """Same model, two parameterisations, one fitted covariance.

    ReplicateBE stores CSH coordinates - two within variances, two between
    variances and a correlation. This package stores a Cholesky factor of G and
    log residual variances. Agreement after mapping is what shows FA0(2) and
    CSH are the same model rather than two models with similar answers, which
    is the substitution FDA explicitly permits.
    """
    var_wr, var_wt, var_br, var_bt, rho = oracle()["cases"][key]["theta"]
    f = fit(key)

    assert f.within_subject_variance_reference == pytest.approx(var_wr, rel=1e-5)
    assert f.within_subject_variance_test == pytest.approx(var_wt, rel=1e-5)
    assert f.between_subject_variance_reference == pytest.approx(var_br, rel=1e-4)
    assert f.between_subject_variance_test == pytest.approx(var_bt, rel=1e-4)
    assert f.subject_correlation == pytest.approx(rho, abs=1e-6)


@pytest.mark.parametrize("key", COMPARABLE)
def test_the_denominator_df_agrees_within_its_decision_impact(key: str):
    """df compared through what it does, not as a number in its own right.

    A df difference matters only through the t quantile it selects, and the
    same absolute difference means very different things at 22 df and at 208.
    1e-3 relative on the quantile moves a confidence limit by well under the
    0.01 percentage points the gate allows.
    """
    ours = fit(key).degrees_of_freedom
    theirs = oracle()["cases"][key]["denominator_df"]

    assert float(stats.t.ppf(1.0 - ALPHA, ours)) == pytest.approx(
        float(stats.t.ppf(1.0 - ALPHA, theirs)), rel=1e-3
    ), f"df {ours:.4f} against {theirs:.4f} (difference {ours - theirs:+.4f})"


def test_the_df_difference_appears_only_at_the_boundary():
    """PR #61's open question, closed.

    Data set I differs by 0.35 df and sits on the correlation boundary. If that
    is a boundary effect then the synthetic boundary case must show it and the
    interior cases must not. It does: case E differs by about 0.29 df, and
    every interior comparable case agrees to four decimal places.

    Asserted in BOTH directions. "The interior cases agree" alone would also be
    satisfied if the boundary case agreed too, which would leave Data set I
    unexplained.
    """
    departures = {
        key: fit(key).degrees_of_freedom
        - oracle()["cases"][key]["denominator_df"]
        for key in COMPARABLE
    }

    interior = {k: v for k, v in departures.items() if not fit(k).on_correlation_boundary}
    boundary = {k: v for k, v in departures.items() if fit(k).on_correlation_boundary}

    assert boundary, "no boundary case among the comparable ones"
    for key, difference in interior.items():
        assert abs(difference) < 1e-3, f"interior case {key} departs by {difference:+.4f}"
    for key, difference in boundary.items():
        assert 0.05 < abs(difference) < 1.0, (
            f"boundary case {key} departs by {difference:+.4f}; the boundary "
            "explanation for Data set I depends on this being nonzero"
        )


def test_the_oracle_records_what_it_is_and_which_version_produced_it():
    """A comparison whose provenance is missing is not usable as evidence."""
    payload = oracle()
    assert payload["oracle"]["package"] == "ReplicateBE.jl"
    assert payload["oracle"]["version_pinned"] == "1.0.15"
    assert payload["oracle"]["julia_version"]
    assert "3" in payload["tier"]

    # Located by name, not by proximity to the expected value - the
    # circularity PR #61 caught and rejected.
    for key, case in fitted_cases().items():
        assert "name:" in case["coefficient_located_by"], (
            f"case {key} fell back to positional lookup: "
            f"{case['coefficient_located_by']}"
        )
