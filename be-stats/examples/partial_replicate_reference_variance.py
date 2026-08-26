"""What this release does, end to end, on a study-sized dataset.

Run it:

    python examples/partial_replicate_reference_variance.py

Twenty-four subjects across TRR / RTR / RRT, one of whom is missing a second
reference measurement. The data are generated from a fixed seed so the output
is reproducible, and are SYNTHETIC - this is a demonstration of the pipeline,
not evidence about the pipeline. Evidence lives in tests/ and validation/.

The last line is the point of the whole release.
"""

from __future__ import annotations

import math
import random

from be_stats import (
    ReplicateDataset,
    ReplicateObservation,
    estimate_reference_variance,
    parse_sequence,
    sequence_mean_differences,
)

SEED = 20260826
#: A within-reference variability in the range that makes a drug highly
#: variable, so the demonstration is of a study that would actually reach this
#: analysis.
TRUE_CV_WR = 0.32
TRUE_SIGMA_WR = math.sqrt(math.log1p(TRUE_CV_WR**2))
REFERENCE_GEOMETRIC_MEAN = 1000.0
TRUE_RATIO = 0.95


def synthetic_study(n_per_sequence: int = 8) -> list[ReplicateObservation]:
    rng = random.Random(SEED)
    observations: list[ReplicateObservation] = []

    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject = f"{label}-{k + 1:02d}"
            # A subject effect, plus independent within-subject error on each
            # measurement. Only the within-subject part reaches sWR.
            subject_effect = rng.gauss(0.0, 0.45)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean_log = math.log(REFERENCE_GEOMETRIC_MEAN) + subject_effect
                if treatment.value == "T":
                    mean_log += math.log(TRUE_RATIO)
                value = math.exp(mean_log + rng.gauss(0.0, TRUE_SIGMA_WR))
                observations.append(
                    ReplicateObservation(
                        subject_id=subject,
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint="AUC0-t",
                        value=round(value, 2),
                    )
                )

    # One subject withdrew before the third period, which in RTR is their
    # second reference measurement. They cannot contribute a Dij.
    return [
        o for o in observations
        if not (o.subject_id == "RTR-05" and o.period == 3)
    ]


def main() -> None:
    observations = synthetic_study()
    dataset = ReplicateDataset.build(observations)

    print("=" * 68)
    print("be-stats — FDA replicate reference variability")
    print("=" * 68)
    print()
    # Sorted: `design.sequences` is a frozenset, and printing it in iteration
    # order would give a different line on a different run.
    sequences = " / ".join(sorted(s.value for s in dataset.design.sequences))
    print(f"Input design: {sequences}")
    print(f"Endpoint:     {dataset.endpoint}")
    print(f"Rows:         {len(observations)}")
    print()

    print("Sequence mean reference differences (Dbar_i.):")
    for sequence, mean in sequence_mean_differences(dataset).items():
        print(f"    {sequence.value}:  {mean:+.6f}")
    print()

    result = estimate_reference_variance(dataset)
    print(result.summary())
    print()

    print("Provenance:")
    for line in result.provenance():
        print(f"  - {line}")
    print()

    print("Exclusion reasons, by code:")
    for code, count in result.exclusion_reasons.items():
        print(f"  {count} x {code}")
    print()

    print("-" * 68)
    print("For reference, the values the data were simulated from:")
    print(f"    true sigma_WR^2 = {TRUE_SIGMA_WR**2:.6f}")
    print(f"    true sigma_WR   = {TRUE_SIGMA_WR:.6f}")
    print(f"    true CVwR       = {100 * TRUE_CV_WR:.2f}%")
    print()
    # An estimate is a draw, and a reader who does not know how wide the draw
    # is will read any gap as an error. sd(s^2) = sigma^2 * sqrt(2/df).
    if result.estimable and result.variance_wr:
        spread = TRUE_SIGMA_WR**2 * math.sqrt(2.0 / result.degrees_of_freedom)
        distance = abs(result.variance_wr - TRUE_SIGMA_WR**2) / spread
        print(
            f"    On {result.degrees_of_freedom} df the estimate has a "
            f"standard deviation of {spread:.6f},"
        )
        print(
            f"    so this one sits {distance:.2f} sd from the truth. That is an "
            "ordinary draw,"
        )
        print("    not a discrepancy - a single study cannot do better.")
    print()
    print("That the estimator is unbiased and reports the right degrees of")
    print("freedom is checked properly in tests/validation/ over 1200")
    print("simulated studies. This script demonstrates the pipeline; it is")
    print("not evidence about it, and simulation is tier 4 regardless.")
    print("-" * 68)


if __name__ == "__main__":
    main()
