"""The nine synthetic full-replicate cases, and the identity that checks them.

WHY THESE CASES CAN BE CHECKED WITHOUT AN ORACLE AT ALL

The cases were built to put the fit under conditions EMA Data set I never
reaches. That would ordinarily leave them dependent on ReplicateBE.jl to say
whether the answers are right - a tier-3 comparison, run in CI, against an
implementation rather than a regulator.

They are not entirely, and the reason is an algebraic identity that emerged
while building them:

    FOR A BALANCED, COMPLETE, FULLY REPLICATE DESIGN WITH AN INTERIOR
    OPTIMUM, THE APPENDIX C MIXED MODEL REDUCES EXACTLY TO THE CLASSICAL
    SUBJECT-LEVEL ANALYSIS - the one-sample analysis of the per-subject
    (mean log T - mean log R) differences, averaged over sequences - AND
    ITS SATTERTHWAITE DENOMINATOR DF IS EXACTLY n - 2.

The classical route uses no mixed model, no REML, no optimiser, no covariance
structure and no Satterthwaite formula. It is thirty lines of arithmetic over
subject means. When it reproduces the estimate AND the standard error to eight
decimal places, and the df to six, the estimate, the standard error and the df
have each been checked against something sharing no code with them.

WHAT KIND OF EVIDENCE THIS IS, STATED CAREFULLY

It is an INDEPENDENT ALGEBRAIC CROSS-CHECK - mathematical and structural
conformance, established by a route with no part of the mixed-model
implementation in it.

It is NOT tier 1A. In this package tier 1A means conformance to a REGULATOR'S
stated algorithm or decision rule, and no regulator states this identity;
it is a property of the model that happens to be true and happens to be
checkable. Calling it tier 1A would promote a mathematical fact into a
regulatory attestation, which is the same category error as calling EMA's
published output an FDA validation.

Its reach is also bounded, and the bounds are the next section.

WHERE THE IDENTITY STOPS, AND WHY THAT IS THE INTERESTING PART

It holds only under all three conditions, and each failure is diagnostic:

    case B  incomplete    - the estimates DIFFER, because available-case
                            analysis uses the partial subjects that the
                            subject-level route has to discard
    case E  boundary      - the ESTIMATE still matches, but the standard
                            error and df do not: with the
                            subject-by-formulation term collapsed onto its
                            floor, the contrast is no longer dominated by the
                            subject-difference statistic and the df moves to
                            the within-subject scale, from 38 to 111

Case E is the same regime as Data set I, where the df is 208 rather than 75.
That is the whole explanation of a number which otherwise looks impossible,
and it is why the tolerance against the Julia oracle is stated in df rather
than in percent.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from scipy import stats

from be_stats.appendix_c import (
    ALPHA,
    AppendixCDataset,
    analyse_replicate_abe_full,
    fit_appendix_c,
    within_acceptance_range,
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

#: Balanced, complete, interior. The identity below holds for exactly these.
CLASSICAL = ("A", "C", "D", "F", "G", "H", "I")


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


def classical_subject_level(key: str) -> tuple[float, float, int]:
    """The textbook analysis, sharing no code with the module under test.

    Per subject, the mean log test minus the mean log reference. Average those
    within each sequence, then average the two sequence means - which is what
    removes the period effect, since T and R occupy opposite periods in TRTR
    and RTRT. The variance comes from the pooled within-sequence scatter of the
    subject differences, on n - 2 degrees of freedom.
    """
    subjects: dict[str, dict] = {}
    for row in CASES[key]["observations"]:
        entry = subjects.setdefault(
            str(row["subject"]), {"sequence": row["sequence"], "T": [], "R": []}
        )
        entry[row["treatment"]].append(math.log(row["value"]))

    by_sequence: dict[str, list[float]] = {}
    for entry in subjects.values():
        difference = sum(entry["T"]) / len(entry["T"]) - sum(entry["R"]) / len(
            entry["R"]
        )
        by_sequence.setdefault(entry["sequence"], []).append(difference)

    sequences = sorted(by_sequence)
    means = [sum(by_sequence[s]) / len(by_sequence[s]) for s in sequences]
    estimate = sum(means) / len(means)

    n = sum(len(by_sequence[s]) for s in sequences)
    residual = sum(
        (d - m) ** 2 for s, m in zip(sequences, means) for d in by_sequence[s]
    )
    pooled = residual / (n - len(sequences))
    variance = sum(pooled / len(by_sequence[s]) for s in sequences) / len(
        sequences
    ) ** 2
    return estimate, math.sqrt(variance), n - len(sequences)


# ----------------------------------------------- the identity, seven times ---


@pytest.mark.parametrize("key", CLASSICAL)
def test_the_fit_reproduces_the_classical_analysis_exactly(key: str):
    """Estimate and standard error, by two routes with nothing in common.

    The tolerance is 1e-8 on both - not a statistical tolerance but a numerical
    one, because the two are the SAME NUMBER and only the optimiser's
    convergence separates them.
    """
    f = fit(key)
    estimate, standard_error, _ = classical_subject_level(key)

    assert not f.on_correlation_boundary, "identity requires an interior optimum"
    assert f.estimate == pytest.approx(estimate, abs=1e-8)
    assert f.standard_error == pytest.approx(standard_error, abs=1e-8)


@pytest.mark.parametrize("key", CLASSICAL)
def test_the_satterthwaite_df_is_exactly_n_minus_two(key: str):
    """The df has an exact known value here, so it is checked against it.

    This is the strongest available statement about the Satterthwaite
    implementation, and it needs no oracle. The contrast collapses onto the
    subject-difference statistic, which carries exactly n - 2 degrees of
    freedom; a df computed from the fitted covariance and the REML information
    matrix must land on that integer.

    1e-5 is convergence slack, not statistical tolerance. Observed departures
    are around 1e-7.
    """
    f = fit(key)
    _, _, expected = classical_subject_level(key)

    assert expected == f.n_subjects - 2
    assert f.degrees_of_freedom == pytest.approx(float(expected), abs=1e-5)


# ------------------------------------------- and the two places it must not ---


def test_the_incomplete_case_does_not_match_the_classical_route():
    """Case B: available-case analysis is not complete-case analysis.

    The subject-level route can only use subjects with both treatments
    observed. PROC MIXED uses every observation. They must therefore disagree,
    and a version of this module that silently dropped incomplete subjects
    would make them agree - which is what this asserts cannot happen.
    """
    f = fit("B")
    estimate, _, _ = classical_subject_level("B")

    assert abs(f.estimate - estimate) > 1e-3
    assert f.n_subjects == 30
    assert len(CASES["B"]["observations"]) == 115  # not 120


def test_the_boundary_case_keeps_the_estimate_but_not_the_df():
    """Case E: the regime that explains Data set I.

    On the boundary the subject-by-formulation variance collapses to its floor,
    the contrast stops being dominated by the subject-difference term, and the
    df moves to the within-subject scale - here from 38 to about 111, on 40
    subjects. That is the same pattern as Data set I, where the df is 208 on
    77 subjects rather than 75.

    The point estimate is unaffected, because it never depended on the
    covariance at all.

    The standard error differs too, and in the direction that is easy to get
    backwards: it is LARGER than the classical one here, not smaller, so the
    narrower interval comes entirely from the df. Asserted as measured rather
    than as reasoned - the first version of this test claimed the opposite from
    a plausible-sounding argument about recovering within-subject information,
    and the numbers said otherwise.
    """
    f = fit("E")
    estimate, standard_error, subject_df = classical_subject_level("E")

    assert f.on_correlation_boundary
    assert f.subject_correlation == pytest.approx(1.0, abs=1e-6)

    # The estimate does not care about the covariance.
    assert f.estimate == pytest.approx(estimate, abs=1e-8)

    # The precision does, on both counts.
    assert subject_df == 38
    assert f.degrees_of_freedom == pytest.approx(111.31, abs=0.01)
    assert f.degrees_of_freedom > 2.5 * subject_df
    assert abs(f.standard_error - standard_error) / standard_error > 0.01


def test_the_boundary_case_was_the_first_seed_tried():
    """Guards against the criticism the search invites.

    A boundary solution has to be searched for - it happens on roughly half of
    all draws at a true correlation of 1, and on none of the draws tried at 28
    subjects. The search takes the first seed satisfying a condition fixed in
    advance. Recording that it was seed 0 is what makes "first seed that landed
    on the boundary" checkable rather than merely claimed.
    """
    payload = json.loads(
        (
            ROOT / "validation/appendix_c/cases/full_replicate_cases.json"
        ).read_text("utf-8")
    )
    assert payload["boundary_case_seed"] == {"E": 0}


# ------------------------------------------------------- the decision rule ---


@pytest.mark.parametrize(
    "key,limit,expected",
    [
        ("F", 80.0, True),
        ("G", 80.0, False),
        ("H", 125.0, True),
        ("I", 125.0, False),
    ],
)
def test_the_containment_decision_at_two_hundredths_of_a_point(
    key: str, limit: float, expected: bool
):
    """Four cases placed 0.02 percentage points either side of each limit.

    The placement is exact rather than searched: multiplying every test
    measurement by a constant shifts the log estimate by exactly that constant
    and leaves the standard error and df untouched, so the interval slides
    rigidly and the required constant is available in closed form.

    F and G differ by four hundredths of a percentage point on the lower limit
    and must return opposite verdicts. An implementation with the inequality
    backwards passes exactly one of each pair, which is why both sides of both
    limits are here rather than one example of each.
    """
    result = analyse_replicate_abe_full(observations(key))

    assert result.decided
    assert result.passes is expected

    # "Inside" means towards the middle of the range from whichever end: the
    # lower limit moves UP off 80, the upper limit moves DOWN off 125.
    inside = 0.02 if expected else -0.02
    if limit < 100.0:
        achieved, target = result.ci_lower_percent, limit + inside
    else:
        achieved, target = result.ci_upper_percent, limit - inside
    assert achieved == pytest.approx(target, abs=5e-4)


def test_containment_is_inclusive_at_each_limit_exactly():
    """A limit sitting exactly on 80.00 or 125.00 is contained.

    FDA requires the interval to be WITHIN 80 to 125 percent, and an interval
    touching a limit is within it - so the comparison is `>=`, not `>`.

    This calls the rule directly rather than constructing a dataset, because
    no dataset can be constructed that lands there. Sliding case A's interval
    onto 80.00 gets to 79.99999998, which a correct implementation must reject;
    the difference between `>` and `>=` never becomes observable that way. It
    is observable here.
    """
    assert within_acceptance_range(80.00, 125.00) is True
    assert within_acceptance_range(80.00, 124.00) is True
    assert within_acceptance_range(81.00, 125.00) is True

    # And strictly outside, by one representable step at each end.
    assert within_acceptance_range(math.nextafter(80.00, 0.0), 125.00) is False
    assert within_acceptance_range(80.00, math.nextafter(125.00, 200.0)) is False


def test_an_interval_slid_onto_the_lower_limit_lands_just_below_it():
    """The floating-point fact the test above exists because of.

    Not a defect and not a tolerance to be widened: sliding an interval onto
    80.00 by an exact multiplicative shift produces a number a hair under it,
    and rejecting that number is correct. Recorded as a test so the next person
    to see 79.99999998 in a failure knows it was expected.
    """
    f = fit("A")
    half_width = float(stats.t.ppf(1.0 - ALPHA, f.degrees_of_freedom)) * (
        f.standard_error
    )
    factor = math.exp(math.log(0.80) + half_width - f.estimate)

    result = analyse_replicate_abe_full(
        [
            ReplicateObservation(
                subject_id=str(row["subject"]),
                sequence=parse_sequence(row["sequence"]),
                period=row["period"],
                treatment=parse_treatment(row["treatment"]),
                endpoint="Cmax",
                value=row["value"] * (factor if row["treatment"] == "T" else 1.0),
            )
            for row in CASES["A"]["observations"]
        ]
    )

    assert result.ci_lower_percent == pytest.approx(80.0, abs=1e-6)
    assert result.ci_lower_percent < 80.0
    assert result.passes is False


# ------------------------------------------------------------ determinism ---


@pytest.mark.parametrize("key", sorted(CASES))
def test_refitting_gives_bit_identical_results(key: str):
    """No random starts, no optimiser shopping, no wall-clock dependence.

    A result that moves between runs cannot be validated, because the value
    recorded in a validation report would not be the value a reviewer
    reproduces. The starting values are method-of-moments and the optimiser
    sequence is fixed, so equality here is exact rather than approximate.
    """
    first, second = fit(key), fit(key)

    assert first.estimate == second.estimate
    assert first.standard_error == second.standard_error
    assert first.degrees_of_freedom == second.degrees_of_freedom
    assert list(first.theta) == list(second.theta)
    assert first.converged and second.converged
    assert not first.fallback_used


@pytest.mark.parametrize("key", sorted(CASES))
def test_every_case_converges_and_reports_a_usable_result(key: str):
    f = fit(key)
    assert f.converged
    assert math.isfinite(f.estimate)
    assert f.standard_error > 0.0
    assert f.degrees_of_freedom > 1.0
    assert f.within_subject_variance_test > 0.0
    assert f.within_subject_variance_reference > 0.0
    assert f.subject_by_formulation_variance >= -1e-12
    assert -1.0 - 1e-9 <= f.subject_correlation <= 1.0 + 1e-9


def test_the_case_set_covers_what_it_claims_to():
    """The cases are only useful if they are actually different from each other.

    Asserted rather than assumed: a regeneration that quietly collapsed the
    spread - all interior, all balanced, all comfortably passing - would leave
    nine tests passing and nothing being tested.
    """
    fits = {key: fit(key) for key in CASES}

    assert len(CASES) == 9
    assert any(f.on_correlation_boundary for f in fits.values())
    assert any(f.subject_correlation < 0.0 for f in fits.values())
    assert any(
        f.within_subject_variance_reference > 3.0 * f.within_subject_variance_test
        for f in fits.values()
    )
    assert any(len(CASES[k]["observations"]) != 4 * f.n_subjects for k, f in fits.items())
    assert len({f.n_subjects for f in fits.values()}) >= 4

    verdicts = {
        key: analyse_replicate_abe_full(observations(key)).passes for key in CASES
    }
    assert True in verdicts.values() and False in verdicts.values()
