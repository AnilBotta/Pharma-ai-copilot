"""FDA narrow therapeutic index: two criteria computed, the verdict withheld.

    python examples/fda_nti_endpoint.py

Two endpoints from one fully replicate study. AUC has a test product about as
reproducible as the reference; Cmax has one markedly less reproducible, which
criterion c is there to catch.

Neither endpoint is decided, and that is the release's position rather than a
failure of the data: criterion b needs FDA's Appendix C model, which this
package does not fit. Two of three criteria do not make a verdict.

The data are SYNTHETIC, from a fixed seed. This demonstrates the pipeline; it is
not evidence about it.
"""

from __future__ import annotations

import math
import random

from be_stats import (
    NtiDesignError,
    ReplicateDataset,
    ReplicateObservation,
    Treatment,
    assess_nti_endpoint,
    assess_nti_study,
    parse_sequence,
)

SEED = 20260826
REFERENCE_GEOMETRIC_MEAN = 1000.0


def endpoint_data(
    endpoint: str,
    cv_wr: float,
    cv_wt: float,
    true_ratio: float,
    seed: int,
    n_per_sequence: int = 12,
) -> ReplicateDataset:
    sigma_r = math.sqrt(math.log1p(cv_wr**2))
    sigma_t = math.sqrt(math.log1p(cv_wt**2))
    rng = random.Random(seed)
    observations = []
    for label in ("TRTR", "RTRT"):
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject_effect = rng.gauss(0.0, 0.35)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                is_test = treatment is Treatment.TEST
                mean_log = math.log(REFERENCE_GEOMETRIC_MEAN) + subject_effect
                if is_test:
                    mean_log += math.log(true_ratio)
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k + 1:02d}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=round(
                            math.exp(
                                mean_log
                                + rng.gauss(0.0, sigma_t if is_test else sigma_r)
                            ),
                            2,
                        ),
                    )
                )
    return ReplicateDataset.build(observations)


def main() -> None:
    datasets = {
        "AUC0-t": endpoint_data("AUC0-t", 0.11, 0.12, 0.98, SEED),
        "Cmax": endpoint_data("Cmax", 0.10, 0.34, 0.96, SEED + 4),
    }
    results = assess_nti_study(datasets)

    print("=" * 74)
    print("be-stats — FDA narrow therapeutic index drugs, Appendix F")
    print("=" * 74)

    for result in results.values():
        print()
        print("-" * 74)
        print(result.summary())

    print()
    print("=" * 74)
    print("Endpoint summary")
    print("=" * 74)
    for name, result in results.items():
        a = result.scaled_mean_criterion.passes
        c = result.variability_ratio_criterion.passes
        print(
            f"  {name:<8} a={_mark(a)}  b={_mark(result.unscaled_abe_criterion.passes)}"
            f"  c={_mark(c)}   ->  {_verdict(result.passes)}"
        )
    print()
    print("Criterion b is not computed in this release, so no endpoint is")
    print("decided. Two of three criteria are not a verdict — an endpoint")
    print("never tested against the unscaled limits is untested, not passing.")

    print()
    print("-" * 74)
    print("The design gate, on a partial replicate study:")
    partial = _partial_replicate()
    try:
        assess_nti_endpoint(partial)
    except NtiDesignError as exc:
        print(f"  NtiDesignError: {str(exc)[:180]}...")

    print()
    print("Provenance for Cmax:")
    for line in results["Cmax"].provenance():
        print(f"  - {line[:150]}{'...' if len(line) > 150 else ''}")


def _mark(value: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "----"}[value]


def _verdict(value: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "NOT DECIDED"}[value]


def _partial_replicate() -> ReplicateDataset:
    observations = []
    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(4):
            for period in range(1, 4):
                observations.append(
                    ReplicateObservation(
                        f"{label}-{k}", sequence, period,
                        sequence.expected_treatment(period), "AUC0-t",
                        1000.0 + 20 * k + 7 * period,
                    )
                )
    return ReplicateDataset.build(observations)


if __name__ == "__main__":
    main()
