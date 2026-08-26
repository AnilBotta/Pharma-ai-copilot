"""Tier 4: simulation. Supplemental verification, and nothing more.

WHAT THIS CAN AND CANNOT SHOW

It can show that the partial-replicate estimator recovers a variance it was
given - that it is unbiased for sigma_WR^2, and that its sampling spread
matches a chi-square on the degrees of freedom it reports. Those are strong
checks on the arithmetic: a factor-of-two error in the denominator, a wrong
degrees-of-freedom count, or a mean taken across sequences instead of within
them would all fail here and none of them would fail a single hand fixture.

It cannot show that this is the estimator FDA specifies. Simulation validates
an implementation against its own definition; only a regulator-published worked
dataset validates the definition. See validation/README.md, tier 1B.

WHY THE DEGREES-OF-FREEDOM CHECK IS THE INTERESTING ONE

Unbiasedness would survive several wrong denominators paired with compensating
errors. The variance of the estimate would not: `Var(s^2) = 2 sigma^4 / df`
pins df directly, so reproducing it confirms the reported `n - m` is the real
one rather than a number attached to the result for display.

TOLERANCES ARE DERIVED, NOT CHOSEN

Every tolerance below comes from the Monte Carlo standard error at the
replicate count actually used, computed in the test. None was picked by running
it and widening until it passed.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from be_stats.reference_variance import estimate_reference_variance
from be_stats.replicate import ReplicateDataset, ReplicateObservation, parse_sequence

#: Fixed, so a failure is reproducible and a pass is not a lottery.
SEED = 20260826
#: Enough that the Monte Carlo error is small against the effect being tested,
#: few enough that the suite stays quick. The tolerance below is computed FROM
#: this number, so changing it cannot silently loosen the test.
REPLICATES = 1200
SUBJECTS_PER_SEQUENCE = 8

TRUE_CV_WR = 0.32
TRUE_SIGMA_WR = math.sqrt(math.log1p(TRUE_CV_WR**2))
TRUE_VARIANCE = TRUE_SIGMA_WR**2

#: n - m for this design: 24 subjects across 3 sequences.
EXPECTED_DF = 3 * SUBJECTS_PER_SEQUENCE - 3


def simulate_one(rng: random.Random):
    """One partial-replicate study from a known within-reference variance.

    A between-subject effect is included deliberately. sWR must be blind to it
    - it cancels in `Rij1 - Rij2` - and an estimator that accidentally picked
    it up would show a large positive bias here.
    """
    observations = []
    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(SUBJECTS_PER_SEQUENCE):
            subject_effect = rng.gauss(0.0, 0.45)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean_log = math.log(1000.0) + subject_effect
                if treatment.value == "T":
                    mean_log += math.log(0.95)
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint="AUC",
                        value=math.exp(mean_log + rng.gauss(0.0, TRUE_SIGMA_WR)),
                    )
                )
    return estimate_reference_variance(ReplicateDataset.build(observations))


@pytest.fixture(scope="module")
def estimates() -> list[float]:
    rng = random.Random(SEED)
    values = []
    for _ in range(REPLICATES):
        result = simulate_one(rng)
        assert result.estimable
        assert result.degrees_of_freedom == EXPECTED_DF
        values.append(result.variance_wr)
    return values


def test_the_estimator_is_unbiased_for_the_variance(estimates):
    """E[sWR^2] = sigma_WR^2.

    The tolerance is four Monte Carlo standard errors. For a chi-square
    estimate, sd(s^2) = sigma^2 sqrt(2/df), so the standard error of the mean
    over R replicates is sigma^2 sqrt(2/df)/sqrt(R). Computed, not guessed.
    """
    mean_estimate = statistics.fmean(estimates)
    standard_error = TRUE_VARIANCE * math.sqrt(2.0 / EXPECTED_DF) / math.sqrt(REPLICATES)
    tolerance = 4.0 * standard_error

    assert abs(mean_estimate - TRUE_VARIANCE) < tolerance, (
        f"mean estimate {mean_estimate:.6f} against true {TRUE_VARIANCE:.6f}; "
        f"4 Monte Carlo SE is {tolerance:.6f}"
    )


def test_the_between_subject_effect_does_not_leak_into_swr(estimates):
    """The simulation carries a between-subject sd of 0.45 - larger than
    sigma_WR itself. An estimator that let any of it through would be biased
    upward by far more than the tolerance above, which the previous test would
    catch. This states the intent so the 0.45 is not later "simplified" away."""
    mean_estimate = statistics.fmean(estimates)
    between_subject_variance = 0.45**2
    assert mean_estimate < TRUE_VARIANCE + 0.1 * between_subject_variance


def test_the_sampling_spread_confirms_the_reported_degrees_of_freedom(estimates):
    """Var(s^2) = 2 sigma^4 / df, which pins df rather than merely displaying it.

    The tolerance is the sampling error of a standard deviation estimated from
    R replicates, sd/sqrt(2R), taken at four times - again computed here.
    """
    observed_sd = statistics.stdev(estimates)
    expected_sd = TRUE_VARIANCE * math.sqrt(2.0 / EXPECTED_DF)
    standard_error = expected_sd / math.sqrt(2.0 * REPLICATES)
    tolerance = 4.0 * standard_error

    assert abs(observed_sd - expected_sd) < tolerance, (
        f"sd of estimates {observed_sd:.6f} against chi-square expectation "
        f"{expected_sd:.6f} at df={EXPECTED_DF}; 4 SE is {tolerance:.6f}. A "
        "mismatch here means the reported degrees of freedom are not the ones "
        "the estimator actually has."
    )


def test_a_wrong_denominator_would_have_been_caught(estimates):
    """Names the failure this suite exists to detect.

    The commonest error in this formula is dividing by `n - m` instead of
    `2(n - m)`, which doubles every estimate. Asserted as a property of the
    measured mean rather than by re-implementing the mistake.
    """
    mean_estimate = statistics.fmean(estimates)
    assert mean_estimate == pytest.approx(TRUE_VARIANCE, rel=0.05)
    assert mean_estimate != pytest.approx(2.0 * TRUE_VARIANCE, rel=0.05)
    assert mean_estimate != pytest.approx(0.5 * TRUE_VARIANCE, rel=0.05)


FULLY_SUBJECTS_PER_SEQUENCE = 12
#: n - m for TRTR/RTRT: 24 subjects across 2 sequences.
FULLY_EXPECTED_DF = 2 * FULLY_SUBJECTS_PER_SEQUENCE - 2


def simulate_one_fully_replicate(rng: random.Random):
    """A four-period study, where each subject also has two TEST measurements.

    Those test measurements are simulated with a DIFFERENT within-subject
    variability from the reference ones, deliberately. sWR must be blind to
    them: an estimator that pooled test and reference variability would be
    pulled toward the wrong number, and this is the design where that mistake
    is possible at all.
    """
    observations = []
    for label in ("TRTR", "RTRT"):
        sequence = parse_sequence(label)
        for k in range(FULLY_SUBJECTS_PER_SEQUENCE):
            subject_effect = rng.gauss(0.0, 0.45)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                is_test = treatment.value == "T"
                mean_log = math.log(1000.0) + subject_effect
                # Test variability set to twice the reference's.
                sigma = 2.0 * TRUE_SIGMA_WR if is_test else TRUE_SIGMA_WR
                if is_test:
                    mean_log += math.log(0.95)
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint="AUC",
                        value=math.exp(mean_log + rng.gauss(0.0, sigma)),
                    )
                )
    return estimate_reference_variance(ReplicateDataset.build(observations))


@pytest.fixture(scope="module")
def fully_estimates() -> list[float]:
    rng = random.Random(SEED + 1)
    values = []
    for _ in range(REPLICATES):
        result = simulate_one_fully_replicate(rng)
        assert result.estimable
        assert result.regulatory_m == 2, "m = 2 for TRTR/RTRT"
        assert result.degrees_of_freedom == FULLY_EXPECTED_DF
        values.append(result.variance_wr)
    return values


def test_the_fully_replicate_estimator_is_unbiased_too(fully_estimates):
    """The estimator implemented after reading Appendix G, checked the same way.

    Its correctness was previously asserted by declining to run it. It now runs,
    so it needs the same evidence the partial one has.
    """
    mean_estimate = statistics.fmean(fully_estimates)
    standard_error = (
        TRUE_VARIANCE * math.sqrt(2.0 / FULLY_EXPECTED_DF) / math.sqrt(REPLICATES)
    )
    assert abs(mean_estimate - TRUE_VARIANCE) < 4.0 * standard_error


def test_the_test_measurements_do_not_reach_swr(fully_estimates):
    """The simulation gives test observations twice the reference variability.

    An estimator that pooled them would land near 2.5x the truth rather than
    at it - far outside the tolerance above. Stated so the asymmetry in the
    simulation is not later "tidied up".
    """
    mean_estimate = statistics.fmean(fully_estimates)
    assert mean_estimate == pytest.approx(TRUE_VARIANCE, rel=0.05)
    pooled_if_wrong = (TRUE_VARIANCE + 4.0 * TRUE_VARIANCE) / 2.0
    assert mean_estimate != pytest.approx(pooled_if_wrong, rel=0.10)


def test_the_fully_replicate_sampling_spread_confirms_its_own_df(fully_estimates):
    observed_sd = statistics.stdev(fully_estimates)
    expected_sd = TRUE_VARIANCE * math.sqrt(2.0 / FULLY_EXPECTED_DF)
    tolerance = 4.0 * expected_sd / math.sqrt(2.0 * REPLICATES)
    assert abs(observed_sd - expected_sd) < tolerance, (
        f"sd {observed_sd:.6f} against chi-square expectation {expected_sd:.6f} "
        f"at df={FULLY_EXPECTED_DF}"
    )


def test_this_is_tier_4_and_promotes_nothing():
    """A simulation cannot raise a validation status."""
    from be_stats import CAPABILITY_VALIDATION, Capability, ValidationStatus

    assert (
        CAPABILITY_VALIDATION[Capability.FDA_HVD_REFERENCE_VARIANCE]
        is ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
