"""The whole Appendix G flow, for a study whose two endpoints diverge.

    python examples/fda_hvd_endpoint_decision.py

AUC is well behaved and takes ordinary average BE. Cmax is highly variable and
takes reference scaling. Same subjects, same study, two methods - which is what
"determine BE for the individual PK parameter" means, and the reason a
study-level classification would be wrong.

The data are SYNTHETIC, from a fixed seed. This demonstrates the pipeline; it
is not evidence about it.
"""

from __future__ import annotations

import math
import random

from be_stats import (
    ReplicateDataset,
    ReplicateObservation,
    Treatment,
    assess_study,
    parse_sequence,
)

SEED = 20260826
REFERENCE_GEOMETRIC_MEAN = 1000.0


def endpoint_data(
    endpoint: str, cv_wr: float, true_ratio: float, seed: int, n_per_sequence: int = 8
) -> ReplicateDataset:
    sigma = math.sqrt(math.log1p(cv_wr**2))
    rng = random.Random(seed)
    observations = []
    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject = f"{label}-{k + 1:02d}"
            subject_effect = rng.gauss(0.0, 0.45)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                mean_log = math.log(REFERENCE_GEOMETRIC_MEAN) + subject_effect
                if treatment is Treatment.TEST:
                    mean_log += math.log(true_ratio)
                observations.append(
                    ReplicateObservation(
                        subject_id=subject,
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=round(math.exp(mean_log + rng.gauss(0.0, sigma)), 2),
                    )
                )
    # One subject withdrew before the third period. In RTR that is their second
    # reference measurement, so they contribute to neither quantity; in TRR it
    # would still leave both references intact.
    return ReplicateDataset.build(
        [o for o in observations if not (o.subject_id == "RTR-05" and o.period == 3)]
    )


def main() -> None:
    datasets = {
        "AUC0-t": endpoint_data("AUC0-t", cv_wr=0.20, true_ratio=0.96, seed=SEED),
        "Cmax": endpoint_data("Cmax", cv_wr=0.45, true_ratio=0.92, seed=SEED + 7),
    }
    results = assess_study(datasets)

    print("=" * 72)
    print("be-stats — FDA highly variable drugs, Appendix G")
    print("=" * 72)

    for name, result in results.items():
        print()
        print("-" * 72)
        print(result.summary())

    print()
    print("=" * 72)
    print("Endpoint summary")
    print("=" * 72)
    for name, result in results.items():
        verdict = {True: "meets criteria", False: "does NOT meet criteria", None: "not decided"}[
            result.passes
        ]
        print(
            f"  {name:<8} sWR={result.swr:.4f}  CVwR={result.cv_wr * 100:5.1f}%  "
            f"{str(result.selected_method):<14} {verdict}"
        )
    print()
    print("Each endpoint chose its own method from its own sWR. Neither")
    print("inherited a scaled acceptance region from the other.")
    print()
    print("Provenance for", list(results)[-1] + ":")
    for line in results[list(results)[-1]].provenance():
        print(f"  - {line}")


if __name__ == "__main__":
    main()
