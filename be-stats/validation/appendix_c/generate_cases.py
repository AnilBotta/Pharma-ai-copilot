"""Generate the frozen synthetic full-replicate cases A-I.

WHY SYNTHETIC CASES EXIST WHEN A REGULATOR'S DATASET IS ALREADY IN HAND

EMA Data set I is the only Appendix C result any regulator has published, and
it is one point in a nine-dimensional space. It happens to sit ON the
correlation boundary, which is a demanding place to land but a narrow one: it
says nothing about whether the fit is right when rho is 0.02, when the two
residual variances differ by a factor of five, when the sequences are unequal,
or when the confidence limit falls a hair either side of 80.00.

These nine cases put a comparison at each of those places. They are simulated
FROM the Appendix C model itself, which means they cannot validate the model -
only an independent implementation fitting the same numbers can do that, and
that is what the ReplicateBE.jl comparison is for. What they can do is put the
optimiser, the Satterthwaite df and the containment rule under conditions the
one real dataset never reaches.

THE DATA IS COMMITTED, NOT THE SEED

Regenerating from a seed makes the cases hostage to NumPy's generator, SciPy's
version and this file staying byte-identical. The oracle would then be
comparing against data that could quietly change underneath it. So this script
is run ONCE, its output is committed as JSON, and both Python and Julia read
that file. Re-running it is a way to inspect how the cases were built, not a
step in the validation.

HOW THE BOUNDARY CASES ARE PLACED

Cases F-I need a confidence limit at a specified distance from 80.00 or 125.00,
which sounds like a search and is not. Multiplying every TEST measurement by k
shifts the log estimate by exactly log k and leaves every variance component,
the standard error and the df untouched - so the whole interval slides rigidly
and the k that puts a limit exactly where it is wanted is available in closed
form. No search, no tolerance, no dependence on the optimiser converging to the
same place twice.

Usage:  python generate_cases.py [output.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from be_stats.appendix_c import (  # noqa: E402
    ALPHA,
    AppendixCDataset,
    fit_appendix_c,
)
from be_stats.conversions import cv_to_log_sd  # noqa: E402
from be_stats.replicate import (  # noqa: E402
    ReplicateObservation,
    parse_sequence,
    parse_treatment,
)

#: One seed for the whole file. Each case draws from the same stream in a fixed
#: order, so the cases are reproducible together and not individually - which is
#: correct, because they are frozen as a set.
SEED = 20260829

#: TRTR / RTRT. Fully replicate is the entire scope of this module.
SEQUENCES = ("TRTR", "RTRT")


def simulate(
    rng: np.random.Generator,
    *,
    n_per_sequence: tuple[int, int],
    cv_within_test: float,
    cv_within_reference: float,
    cv_between_test: float,
    cv_between_reference: float,
    correlation: float,
    true_gmr: float,
    period_effects: tuple[float, ...],
    drop: tuple[tuple[int, int], ...] = (),
) -> list[dict]:
    """Draw one dataset from the Appendix C model.

    The model is simulated in the coordinates FDA specifies it in: a
    subject-level random vector (b_T, b_R) with an unstructured 2x2 covariance,
    plus a residual whose variance depends on WHICH TREATMENT was given. A
    simulator with one residual variance would be simulating a different model
    and every case here would silently become easier than it should be.
    """
    sd_wt = cv_to_log_sd(cv_within_test)
    sd_wr = cv_to_log_sd(cv_within_reference)
    sd_bt = cv_to_log_sd(cv_between_test)
    sd_br = cv_to_log_sd(cv_between_reference)

    g = np.array(
        [
            [sd_bt**2, correlation * sd_bt * sd_br],
            [correlation * sd_bt * sd_br, sd_br**2],
        ]
    )
    # Cholesky rather than a multivariate sampler: at correlation 0.999 the
    # matrix is nearly singular and the factor is what the model is actually
    # parameterised by, so drawing through it keeps the simulation and the fit
    # in the same coordinates.
    chol = np.linalg.cholesky(g + 1e-14 * np.eye(2))

    rows: list[dict] = []
    subject = 0
    for sequence, n in zip(SEQUENCES, n_per_sequence):
        for _ in range(n):
            subject += 1
            b_test, b_reference = chol @ rng.standard_normal(2)
            for period, letter in enumerate(sequence, start=1):
                if (subject, period) in drop:
                    continue
                is_test = letter == "T"
                mean = (
                    math.log(true_gmr) + b_test if is_test else b_reference
                ) + period_effects[period - 1]
                sd = sd_wt if is_test else sd_wr
                rows.append(
                    {
                        "subject": str(subject),
                        "sequence": sequence,
                        "period": period,
                        "treatment": "T" if is_test else "R",
                        "value": float(math.exp(mean + sd * rng.standard_normal())),
                    }
                )
    return rows


def to_observations(rows: list[dict]) -> list[ReplicateObservation]:
    return [
        ReplicateObservation(
            subject_id=row["subject"],
            sequence=parse_sequence(row["sequence"]),
            period=row["period"],
            treatment=parse_treatment(row["treatment"]),
            endpoint="Cmax",
            value=row["value"],
        )
        for row in rows
    ]


def fit(rows: list[dict]):
    return fit_appendix_c(AppendixCDataset.build(to_observations(rows)))


def shift_test_values(rows: list[dict], factor: float) -> list[dict]:
    """Multiply every TEST measurement by `factor`.

    Exactly equivalent to adding log(factor) to the treatment effect: the
    residuals, the subject effects and therefore all five covariance
    parameters, the standard error and the df are unchanged. This is what makes
    the boundary placement below closed-form.
    """
    return [
        dict(row, value=row["value"] * factor) if row["treatment"] == "T" else dict(row)
        for row in rows
    ]


def place_limit(rows: list[dict], *, limit_percent: float, margin: float) -> list[dict]:
    """Slide the interval until the named limit sits `margin` percent inside it.

    A positive margin puts the limit INSIDE the acceptance range by that many
    percentage points; a negative one puts it outside. Which limit is being
    placed follows from which end of the range it is: 80 is approached from
    above by the lower limit, 125 from below by the upper.
    """
    base = fit(rows)
    t = float(stats.t.ppf(1.0 - ALPHA, base.degrees_of_freedom))
    half_width = t * base.standard_error

    if limit_percent < 100.0:
        # Lower limit must land at limit + margin.
        target_log = math.log((limit_percent + margin) / 100.0) + half_width
    else:
        # Upper limit must land at limit - margin.
        target_log = math.log((limit_percent - margin) / 100.0) - half_width

    return shift_test_values(rows, math.exp(target_log - base.estimate))


#: Recorded in the output so the boundary case can be traced to the draw it
#: came from. Filled in by `first_boundary_draw`.
BOUNDARY_SEED: dict[str, int] = {}


def first_boundary_draw(**common) -> list[dict]:
    """The first draw from a fixed seed sequence whose fit lands on the boundary.

    A boundary solution cannot be simulated on demand. Even at a true
    correlation of exactly 1 the fitted value crosses onto the boundary only
    when sampling noise pushes the estimated subject-by-formulation variance
    below the floor a PSD G allows - a coin flip, near enough, at forty
    subjects, and something that never happened in any seed tried at
    twenty-eight.

    So one has to be searched for, and searching invites the obvious criticism:
    a seed picked because it gave a pleasing answer is not evidence of
    anything. This takes the FIRST seed from 0 upward that satisfies a
    condition stated in advance - the fit is on the boundary - and records
    which seed that was. The condition is a property of the DATA, not of any
    agreement with an oracle, and nothing downstream of this function has been
    computed yet. Rejecting seeds until the comparison passed would be a
    different act entirely, and this is not that.
    """
    for seed in range(200):
        rows = simulate(
            np.random.default_rng(seed),
            n_per_sequence=(20, 20),
            cv_within_test=0.30,
            cv_within_reference=0.30,
            correlation=1.0,
            true_gmr=1.02,
            **common,
        )
        if fit(rows).on_correlation_boundary:
            BOUNDARY_SEED["E"] = seed
            return rows
    raise RuntimeError(
        "no seed below 200 produced a boundary solution - the optimiser or the "
        "parameterisation has changed, and that is the finding"
    )


def build() -> dict:
    rng = np.random.default_rng(SEED)

    # A modest period trend in every case. A simulator with no period effect
    # would leave the PER terms in the model estimating nothing, and a bug that
    # dropped them would pass unnoticed.
    periods = (0.0, 0.03, -0.02, 0.05)

    common = dict(
        cv_between_test=0.45,
        cv_between_reference=0.45,
        period_effects=periods,
    )

    cases: dict[str, dict] = {}

    def add(key: str, name: str, purpose: str, rows: list[dict]) -> None:
        cases[key] = {"name": name, "purpose": purpose, "observations": rows}

    central = simulate(
        rng,
        n_per_sequence=(12, 12),
        cv_within_test=0.25,
        cv_within_reference=0.25,
        correlation=0.50,
        true_gmr=1.00,
        **common,
    )
    add(
        "A",
        "central_balanced",
        "The ordinary case. Balanced sequences, equal residual variances, an "
        "interior correlation and a true ratio of 1. Nothing here is "
        "difficult, which is the point: if this one disagrees, none of the "
        "harder ones tell you anything.",
        central,
    )

    add(
        "B",
        "unbalanced_with_missing_periods",
        "Twenty subjects against ten, plus four dropped observations. "
        "Unbalanced sequences break the algebraic shortcuts that make a "
        "balanced design tractable by hand, and the dropped periods force the "
        "available-case rule to do something visible - three subjects "
        "contribute three observations and one contributes two.",
        simulate(
            rng,
            n_per_sequence=(20, 10),
            cv_within_test=0.28,
            cv_within_reference=0.32,
            correlation=0.40,
            true_gmr=1.05,
            drop=((3, 2), (7, 4), (11, 1), (24, 2), (24, 3)),
            **common,
        ),
    )

    add(
        "C",
        "unequal_residual_variances",
        "Within-subject CV of 20% on test against 45% on reference. This is "
        "the whole reason Appendix C carries REPEATED/GRP=TRT: a model with a "
        "single residual variance fits this data too, and gets a different "
        "standard error. The case exists to make that difference visible.",
        simulate(
            rng,
            n_per_sequence=(16, 16),
            cv_within_test=0.20,
            cv_within_reference=0.45,
            correlation=0.55,
            true_gmr=0.97,
            **common,
        ),
    )

    add(
        "D",
        "correlation_near_zero",
        "Simulated at a subject-by-formulation correlation of 0.02, the "
        "opposite extreme from the only real dataset available, where it is 1. "
        "The FITTED correlation lands slightly negative, which is ordinary "
        "sampling noise around a true value of nearly zero and is itself worth "
        "having: a negative correlation is perfectly admissible under FA0(2) "
        "and an implementation that forced it non-negative would fail here. "
        "Near zero the two subject effects are almost independent and G is "
        "well conditioned, so a disagreement here cannot be blamed on the "
        "boundary.",
        simulate(
            rng,
            n_per_sequence=(14, 14),
            cv_within_test=0.30,
            cv_within_reference=0.30,
            correlation=0.02,
            true_gmr=1.02,
            **common,
        ),
    )

    add(
        "E",
        "correlation_on_the_boundary",
        "Simulated at correlation exactly 1 with equal between-subject "
        "variances, so the true subject-by-formulation variance is zero and "
        "the fit lands ON the boundary - l22 driven to 1e-9, rho to 1.000000, "
        "with no bound applied.\n\n"
        "This is the case the oracle comparison needs most, and it took two "
        "attempts to build. Simulating at rho = 0.999 with 28 subjects never "
        "reached the boundary in any seed tried: the fitted correlation "
        "settled around 0.96-0.97 and the df came out at exactly n-2, "
        "indistinguishable from the interior cases. Forty subjects at rho = 1 "
        "reaches it in roughly half of all seeds, because the boundary is hit "
        "when sampling noise pushes the estimated subject-by-formulation "
        "variance below the floor that a PSD G permits, and that floor is "
        "easier to cross with a tighter estimate.\n\n"
        "The df tells the two regimes apart unmistakably. Interior balanced "
        "fits give exactly n-2, because the contrast collapses onto the "
        "subject-difference statistic. On the boundary that term vanishes and "
        "the contrast becomes essentially within-subject, so the df jumps to "
        "the within-subject scale - about 100 here, and 208 on Data set I. "
        "Any implementation that quietly kept the interior form would be off "
        "by a factor of three, not a rounding.",
        first_boundary_draw(**common),
    )

    # F-I: the containment decision, placed to the hundredth of a percentage
    # point on each side of each limit. 0.02 is wide enough that a correct
    # implementation is never in doubt and narrow enough that an error in the
    # df or the standard error large enough to matter would flip the verdict.
    add(
        "F",
        "lower_limit_just_inside_80",
        "Lower confidence limit at 80.02%. PASSES, by two hundredths of a "
        "percentage point.",
        place_limit(central, limit_percent=80.0, margin=0.02),
    )
    add(
        "G",
        "lower_limit_just_outside_80",
        "Lower confidence limit at 79.98%. FAILS, by the same margin. Together "
        "with F this pins the direction of the comparison as well as its "
        "strictness - an implementation that had the inequality backwards "
        "would pass exactly one of them.",
        place_limit(central, limit_percent=80.0, margin=-0.02),
    )
    add(
        "H",
        "upper_limit_just_inside_125",
        "Upper confidence limit at 124.98%. PASSES.",
        place_limit(central, limit_percent=125.0, margin=0.02),
    )
    add(
        "I",
        "upper_limit_just_outside_125",
        "Upper confidence limit at 125.02%. FAILS. The upper limit is not a "
        "mirror of the lower one on the log scale - log(1.25) and -log(0.8) "
        "are the same number, but the estimate is not centred between them - "
        "so both ends need their own pair.",
        place_limit(central, limit_percent=125.0, margin=-0.02),
    )

    return {
        "schema": "be-stats/appendix-c-full-replicate-cases/1",
        "generator": "validation/appendix_c/generate_cases.py",
        "seed": SEED,
        "boundary_case_seed": dict(BOUNDARY_SEED),
        "design": "fully replicate, TRTR/RTRT",
        "note": (
            "Simulated from the Appendix C model. These cases exercise the "
            "implementation across conditions the one published dataset does "
            "not reach; they are not evidence that the model is the right "
            "model. Committed as data - regenerating is inspection, not "
            "validation."
        ),
        "cases": cases,
    }


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "cases" / "full_replicate_cases.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for key, case in payload["cases"].items():
        rows = case["observations"]
        f = fit(rows)
        t = float(stats.t.ppf(1.0 - ALPHA, f.degrees_of_freedom))
        half = t * f.standard_error
        print(
            f"{key}  {case['name']:<34} n={f.n_subjects:>3} obs={len(rows):>3}  "
            f"GMR={100 * math.exp(f.estimate):7.3f}  "
            f"CI={100 * math.exp(f.estimate - half):7.3f},"
            f"{100 * math.exp(f.estimate + half):8.3f}  "
            f"df={f.degrees_of_freedom:8.4f}  rho={f.subject_correlation:+.6f}"
        )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
