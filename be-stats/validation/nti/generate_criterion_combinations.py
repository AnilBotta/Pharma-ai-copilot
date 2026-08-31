"""Four fully replicate datasets, one per NTI criterion-combination.

WHY THIS EXISTS SEPARATELY FROM THE APPENDIX C CASES

FDA's NTI procedure requires all three of Appendix F step 5 to hold. Until
criterion (b) was implementable the combination logic could not be exercised at
all: (b) was permanently `None`, so the endpoint was permanently undecided and
every combination collapsed to the same answer.

Now that all three are computed, the AND has to be tested where it can actually
fail - and the way it fails matters. An implementation that returned the
conjunction of whichever criteria happened to be present, or that treated a
`None` as a pass, would agree with a correct one on the all-pass case and
disagree on exactly the three cases below.

    PASS PASS PASS   overall PASS
    FAIL PASS PASS   overall FAIL   (a) scaled mean
    PASS FAIL PASS   overall FAIL   (b) unscaled 80-125, i.e. Appendix C
    PASS PASS FAIL   overall FAIL   (c) variability ratio

WHAT EACH ONE IS, AND WHY IT LOOKS THE WAY IT DOES

The parameters were searched for over a small fixed grid, taking the first
combination that produced each pattern. Two of the four are worth reading
twice, because they look wrong until the procedure is taken seriously:

  (a) fails at a TRUE RATIO OF 1.00. Criterion (a) is reference-scaled with
      sigma_W0 fixed at 0.10, so for a drug with a within-reference CV of 5%
      the criterion is far stricter than 80-125% - the implied limit on the
      mean difference is about 1.05 * sigma_WR, which is roughly 94.9-105.4%.
      A perfectly matched product can fail it on sampling variability alone.
      That is FDA's procedure, not an artefact of the search.

  (c) fails while (a) and (b) pass. Criterion (c) asks whether the TEST product
      is as reproducible as the reference - a question about the product, not
      about the mean - so a test formulation with twice the reference's
      within-subject CV fails it while its mean sits comfortably in the middle
      of the acceptance range.

Usage:  python generate_criterion_combinations.py [output.json]
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appendix_c"))

from generate_cases import simulate, to_observations  # noqa: E402

from be_stats.nti import assess_nti_endpoint  # noqa: E402
from be_stats.replicate import ReplicateDataset  # noqa: E402

PERIOD_EFFECTS = (0.0, 0.02, -0.01, 0.03)

#: The four patterns, and what each is FOR.
WANTED = {
    (True, True, True): (
        "all_pass",
        "The only combination that approves. Everything else here exists to "
        "show that it is the only one.",
    ),
    (False, True, True): (
        "scaled_mean_fails",
        "Criterion (a) alone fails, at a TRUE RATIO OF 1.00. With a "
        "within-reference CV of 5% the reference-scaled criterion is much "
        "stricter than 80-125% - about 94.9-105.4% - and a perfectly matched "
        "product can fail it on sampling variability. FDA's procedure, not an "
        "artefact.",
    ),
    (True, False, True): (
        "unscaled_abe_fails",
        "Criterion (b) alone fails - the Appendix C interval escapes "
        "80-125% while the reference-scaled criterion, which widens with "
        "sigma_WR, still passes. This is the case that could not exist before "
        "Appendix C was implemented, because (b) was permanently None.",
    ),
    (True, True, False): (
        "variability_ratio_fails",
        "Criterion (c) alone fails: the test product has twice the "
        "reference's within-subject CV. Its mean sits in the middle of the "
        "acceptance range and both mean-based criteria pass, which is exactly "
        "why FDA asks the reproducibility question separately.",
    ),
}


def pattern(rows: list[dict]):
    observations = to_observations(rows)
    result = assess_nti_endpoint(
        ReplicateDataset.build(observations), observations=observations
    )
    return (
        (
            result.scaled_mean_criterion.passes
            if result.scaled_mean_criterion
            else None
        ),
        result.unscaled_abe_criterion.passes,
        (
            result.variability_ratio_criterion.passes
            if result.variability_ratio_criterion
            else None
        ),
    ), result


def build() -> dict:
    """First hit on a fixed grid for each pattern. No per-pattern tuning.

    The grid is small and declared here in full, so "searched for" means
    something checkable. Nothing is rejected on the basis of the OVERALL
    verdict - only on the three-criterion pattern, which is the property the
    case is being built to exhibit.
    """
    grid = itertools.product(
        [(18, 18), (12, 12), (24, 24)],
        [0.05, 0.12, 0.30, 0.38],
        [1.0, 2.0, 3.2],
        [1.00, 1.06, 1.14, 1.22],
        range(6),
    )

    found: dict[tuple, dict] = {}
    for n, cv_wr, ratio, gmr, seed in grid:
        rows = simulate(
            np.random.default_rng(1000 + seed),
            n_per_sequence=n,
            cv_within_test=min(cv_wr * ratio, 0.85),
            cv_within_reference=cv_wr,
            cv_between_test=0.35,
            cv_between_reference=0.35,
            correlation=0.5,
            true_gmr=gmr,
            period_effects=PERIOD_EFFECTS,
        )
        try:
            observed, result = pattern(rows)
        except Exception:  # a grid point the procedure refuses outright
            continue
        if observed in WANTED and observed not in found:
            name, purpose = WANTED[observed]
            found[observed] = {
                "name": name,
                "purpose": purpose,
                "criteria": {
                    "a_scaled_mean": observed[0],
                    "b_unscaled_abe": observed[1],
                    "c_variability_ratio": observed[2],
                },
                "expected_decided": result.decided,
                "expected_passes": result.passes,
                "parameters": {
                    "n_per_sequence": list(n),
                    "cv_within_reference": cv_wr,
                    "cv_within_test": min(cv_wr * ratio, 0.85),
                    "true_gmr": gmr,
                    "seed": 1000 + seed,
                },
                "observations": rows,
            }
        if len(found) == len(WANTED):
            break

    missing = set(WANTED) - set(found)
    if missing:
        raise RuntimeError(f"grid produced no dataset for {missing}")

    return {
        "schema": "be-stats/nti-criterion-combinations/1",
        "generator": "validation/nti/generate_criterion_combinations.py",
        "design": "fully replicate, TRTR/RTRT - NTI requires it",
        "note": (
            "Simulated. These test the COMBINATION logic of Appendix F step 5, "
            "not the individual criteria - each of those has its own "
            "validation. Committed as data; regenerating is inspection."
        ),
        "cases": {case["name"]: case for case in found.values()},
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "cases" / "criterion_combinations.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for name, case in payload["cases"].items():
        c = case["criteria"]
        print(
            f"{name:<26} a={str(c['a_scaled_mean']):<5} "
            f"b={str(c['b_unscaled_abe']):<5} c={str(c['c_variability_ratio']):<5} "
            f"-> decided={case['expected_decided']} passes={case['expected_passes']}"
        )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
