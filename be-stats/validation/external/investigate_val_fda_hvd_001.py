"""The investigation behind VAL-FDA-HVD-001, kept so it can be re-run.

WHAT WAS OBSERVED

The first run of the external validation harness (PR #58) reported, for
`RSABE-002-BOUNDARY-NEAR`:

    p_be_sabec   be-stats 0.87055   PowerTOST 0.85817   diff 0.01238

That passed the declared tolerance of 0.01549 and was flagged as a FINDING,
because 0.01238 is about 4.61 of the comparison's own Monte Carlo standard
errors. Two other RSABE cases - CVwR 0.40 and CVwR 0.60 - agreed closely. So
the disagreement was specific to the scenario sitting near the switch.

WHAT THIS SCRIPT ESTABLISHES

That the two sides were computing DIFFERENT QUANTITIES, and that each was
computing its own quantity correctly.

    PowerTOST's `p(BE-sABEc)` is the MIXED decision: the scaled criterion for
    studies above the switch, conventional ABE for studies below it, without
    the point-estimate constraint.

    The be-stats harness computed the SCALED CRITERION ALONE, for every
    simulated study, regardless of which side of the switch it fell.

At CVwR = 0.31 roughly 43% of simulated studies fall below the switch, and
conventional ABE is harder than the scaled criterion there, so the mixed
quantity is lower. At CVwR = 0.40 and 0.60 almost nothing falls below the
switch, the two quantities coincide, and the cases agreed.

THE INSTRUMENT, AND WHY IT IS NOT AN ORACLE

Experiment A below re-implements PowerTOST's OWN simulation in Python -
`.pwr.SABE.isc` in `R/power_RSABE2L_isc.R` - so the hypothesis could be tested
without R, which is unavailable outside CI in this environment.

    THAT REPRODUCTION IS AN INVESTIGATION INSTRUMENT, NOT EVIDENCE.

It is a transcription of the oracle's source, so it cannot corroborate the
oracle. It is here to explain a discrepancy, and its conclusion is confirmed
independently by the corrected case files, which drive the real PowerTOST in
CI. Nothing in this file feeds `report.json`.

Usage:
    PYTHONPATH=src:validation/external python validation/external/investigate_val_fda_hvd_001.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scipy import stats

from be_stats.hvd import point_estimate_constraint, scaled_criterion
from be_stats.reference_variance import estimate_reference_variance
from be_stats.spec import FDA_HVD_CONSTANTS, fda_hvd_theta
from be_stats.treatment_contrast import estimate_treatment_contrast
from simulate import DESIGNS, _allocate, _simulate_study

FINDING_ID = "VAL-FDA-HVD-001"
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "findings" / f"{FINDING_ID}-evidence.json"

#: The scenario the finding was raised on. Copied from
#: `cases/rsabe_002_boundary_near.json` and not parameterised, because the
#: point of a finding record is that it names one reproducible scenario.
SCENARIO = {
    "design": "2x2x4",
    "cv_wr": 0.31,
    "cv_wt": 0.31,
    "theta0": 0.90,
    "n": 36,
}

LN_LOWER = math.log(0.80)
LN_UPPER = math.log(1.25)

#: FDA Appendix G, and what be-stats applies.
FDA_SWR_SWITCH = FDA_HVD_CONSTANTS["swr_switching_threshold"].value

#: PowerTOST 1.5-7, `R/scABEL.R` line 17: `reg_const("FDA")` carries
#: `CVswitch = 0.3`, and `R/power_RSABE2L_isc.R` line 156 converts it as
#: `s2switch <- log(CVswitch^2 + 1)`. On the sWR scale that is 0.29356..., not
#: 0.294. See VAL-FDA-HVD-002.
POWERTOST_CVSWITCH = 0.30
POWERTOST_SWR_SWITCH = math.sqrt(math.log(POWERTOST_CVSWITCH**2 + 1.0))


# ------------------------------------------------------- the be-stats side ---


@dataclass(slots=True)
class BeStatsComponents:
    """Every decision component be-stats can produce, per simulated study."""

    scaled_pass: int = 0
    pe_pass: int = 0
    below_switch: int = 0
    #: PowerTOST's unscaled branch reproduced on the be-stats contrast. See
    #: `_powertost_unscaled_branch` for why this is not a be-stats result.
    instrument_unscaled_pass: int = 0
    instrument_mixed_pass: int = 0
    evaluated: int = 0
    swr_values: list[float] = field(default_factory=list)

    def proportions(self) -> dict[str, float]:
        n = self.evaluated
        return {
            "p_scaled_criterion_alone": self.scaled_pass / n,
            "p_point_estimate_constraint": self.pe_pass / n,
            "fraction_below_switch": self.below_switch / n,
            "instrument_p_mixed": self.instrument_mixed_pass / n,
            "instrument_p_unscaled_alone": self.instrument_unscaled_pass / n,
            "nsims_evaluated": float(n),
        }


def _powertost_unscaled_branch(contrast) -> bool:
    """PowerTOST's `BE_ABE`, evaluated on the be-stats treatment contrast.

    NOT A be-stats RESULT, AND NOT AN FDA RESULT.

    PowerTOST decides the below-switch branch by a TOST on the same
    intra-subject contrast it uses above the switch:

        BE_ABE <- ((ln_lBEL <= lCL) & (uCL <= ln_uBEL))      # line 240

    FDA does not. Appendix C specifies a mixed model with five covariance
    parameters, which `be_stats.replicate_abe` records and refuses to
    approximate. So this function reproduces the ORACLE's convention in order
    to explain the oracle's number. It must never reach a caller asking what
    FDA would conclude, and nothing in `be_stats` imports it.
    """
    return LN_LOWER <= contrast.ci_lower and contrast.ci_upper <= LN_UPPER


def run_be_stats_side(
    *,
    cv_wr: float,
    cv_wt: float,
    theta0: float,
    n: int,
    design: str,
    nsims: int,
    seed: int,
    swr_switch: float = FDA_SWR_SWITCH,
) -> BeStatsComponents:
    labels = DESIGNS[design]
    n_by_sequence = _allocate(n, len(labels))
    sigma_wt = math.sqrt(math.log1p(cv_wt**2))
    sigma_wr = math.sqrt(math.log1p(cv_wr**2))
    rng = random.Random(seed)
    out = BeStatsComponents()

    for _ in range(nsims):
        dataset = _simulate_study(
            labels=labels,
            n_by_sequence=n_by_sequence,
            sigma_wt=sigma_wt,
            sigma_wr=sigma_wr,
            theta0=theta0,
            endpoint="AUC",
            rng=rng,
        )
        variance = estimate_reference_variance(dataset)
        contrast = estimate_treatment_contrast(dataset)
        if not variance.estimable or not contrast.estimable or variance.swr is None:
            continue

        out.evaluated += 1
        out.swr_values.append(variance.swr)
        below = variance.swr < swr_switch
        out.below_switch += int(below)

        scaled = scaled_criterion(contrast=contrast, reference_variance=variance).passes
        unscaled = _powertost_unscaled_branch(contrast)
        out.scaled_pass += int(scaled)
        out.instrument_unscaled_pass += int(unscaled)
        out.instrument_mixed_pass += int(unscaled if below else scaled)
        out.pe_pass += int(point_estimate_constraint(contrast).passes)

    if out.evaluated == 0:
        raise RuntimeError("no simulated study produced an estimable result")
    return out


# ---------------------------------------- the instrument: PowerTOST in Python -


def powertost_reproduction(
    *,
    cv_wr: float,
    theta0: float,
    n: int,
    nsims: int,
    seed: int,
    alpha: float = 0.05,
    swr_switch: float = POWERTOST_SWR_SWITCH,
) -> dict[str, float]:
    """`.pwr.SABE.isc` with `SABE_test="fda"`, transcribed. INSTRUMENT ONLY.

    PowerTOST 1.5-7, `R/power_RSABE2L_isc.R` lines 149-283, reached from
    `power.RSABE` via `.power.RSABE` at line 287. It simulates the deciding
    STATISTICS directly rather than subject data:

        pes   <- rnorm(nsi, mean=mlog, sd=sdm)
        sd2s  <- Emse*C3*rchisq(nsi, df)/df
        s2wRs <- s2wR*rchisq(nsi, dfRR)/dfRR

    which is the exact sampling distribution of the same quantities be-stats
    estimates from data, under the model both sides assume. That equivalence is
    checked by `verify_data_generating_process` below rather than asserted.
    """
    import numpy as np

    # `R/power_RSABE.R`, the 2x2x4 block: dfRR = n-2, df = n-2, seqs = 2, and
    # Emse = s2D + (s2wT + s2wR)/2 with s2D = 0 when no subject-by-formulation
    # interaction is assumed - which is what `power.RSABE(CV=<scalar>)` means.
    s2w = math.log1p(cv_wr**2)
    seqs = 2
    df = n - 2
    df_rr = n - 2
    per_sequence = _allocate(n, seqs)
    c3 = sum(1.0 / x for x in per_sequence) / seqs**2
    emse = s2w
    sdm = math.sqrt(emse * c3)

    rng = np.random.default_rng(seed)
    t_crit = stats.t.ppf(1.0 - alpha, df)
    chisq_crit = stats.chi2.ppf(1.0 - alpha, df_rr)
    theta = fda_hvd_theta()

    pes = rng.normal(math.log(theta0), sdm, nsims)
    se = np.sqrt(emse * c3 * rng.chisquare(df, nsims) / df)
    s2wrs = s2w * rng.chisquare(df_rr, nsims) / df_rr
    hw = t_crit * se

    be_abe = (LN_LOWER <= pes - hw) & (pes + hw <= LN_UPPER)

    # Howe's Approximation I, in PowerTOST's names. `Em - SEs^2` is be-stats'
    # `x`, `Es` is `-y`, `Cm` is `bound_x`, `Cs` is `-bound_y`, and `SABEc95`
    # is `critbound`. The algebraic identity is recorded in the finding.
    em = pes**2 - se**2
    es = theta * s2wrs
    cm = (np.abs(pes) + hw) ** 2
    cs = es * df_rr / chisq_crit
    be_rsabe = (em - es + np.sqrt((cm - em) ** 2 + (cs - es) ** 2)) <= 0

    below = np.sqrt(s2wrs) < swr_switch
    be_mixed = np.where(below, be_abe, be_rsabe)
    be_pe = (pes >= LN_LOWER) & (pes <= LN_UPPER)

    return {
        "p_scaled_criterion_alone": float(be_rsabe.mean()),
        "p_unscaled_alone": float(be_abe.mean()),
        "p_mixed": float(be_mixed.mean()),
        "p_point_estimate_constraint": float(be_pe.mean()),
        "p_overall_be": float((be_mixed & be_pe).mean()),
        "fraction_below_switch": float(below.mean()),
        "nsims": float(nsims),
    }


# ------------------------------------------------------------ experiments ---


def verify_data_generating_process(nsims: int, seed: int) -> dict:
    """Does be-stats' simulated sWR have the distribution PowerTOST assumes?

    PowerTOST draws `s2wRs <- s2wR*rchisq(nsims, dfRR)/dfRR`. If the harness's
    subject-level simulation produces sWR^2 with any other distribution, the
    two sides are not simulating the same study and no comparison between them
    means anything - which is the first thing to rule out, not the last.

    Checked three ways: the mean, the variance, and a Kolmogorov-Smirnov test
    against the exact scaled chi-square. Reported, never asserted, because a
    p-value that gates a build eventually gets loosened.
    """
    components = run_be_stats_side(
        cv_wr=SCENARIO["cv_wr"],
        cv_wt=SCENARIO["cv_wt"],
        theta0=SCENARIO["theta0"],
        n=SCENARIO["n"],
        design=SCENARIO["design"],
        nsims=nsims,
        seed=seed,
    )
    import numpy as np

    df_rr = SCENARIO["n"] - 2
    s2w = math.log1p(SCENARIO["cv_wr"] ** 2)
    observed = np.array(components.swr_values) ** 2
    ks = stats.kstest(observed * df_rr / s2w, "chi2", args=(df_rr,))
    return {
        "what": "distribution of the be-stats sWR^2 against the exact "
        "scaled chi-square PowerTOST samples from",
        "nsims": nsims,
        "seed": seed,
        "degrees_of_freedom": df_rr,
        "expected_mean_s2wr": s2w,
        "observed_mean_s2wr": float(observed.mean()),
        "expected_variance_s2wr": 2.0 * s2w**2 / df_rr,
        "observed_variance_s2wr": float(observed.var(ddof=1)),
        "ks_statistic": float(ks.statistic),
        "ks_p_value": float(ks.pvalue),
        "interpretation": "reported, not asserted; a build must not hinge on "
        "a p-value that can be loosened",
    }


def experiment_a(nsims: int, seed: int) -> dict:
    """Isolate the scaled criterion, removing switching from both sides.

    The be-stats side already computes the scaled criterion for every study.
    The instrument is driven with the switch disabled, which is what
    `reg_const("USER", CVswitch = 0, ...)` does to the real PowerTOST - and
    what `cases/rsabe_*.json` now ask for.
    """
    be = run_be_stats_side(nsims=nsims, seed=seed, **SCENARIO).proportions()
    pt = powertost_reproduction(
        cv_wr=SCENARIO["cv_wr"],
        theta0=SCENARIO["theta0"],
        n=SCENARIO["n"],
        nsims=nsims * 5,
        seed=seed,
        swr_switch=0.0,
    )
    return _paired(
        "A",
        "scaled criterion alone, switching disabled on both sides",
        be["p_scaled_criterion_alone"],
        pt["p_scaled_criterion_alone"],
        nsims,
        nsims * 5,
    )


def experiment_b(nsims: int, seed: int) -> dict:
    """The mixed procedure, which is what PowerTOST reports as p(BE-sABEc)."""
    be = run_be_stats_side(nsims=nsims, seed=seed, **SCENARIO).proportions()
    pt = powertost_reproduction(
        cv_wr=SCENARIO["cv_wr"],
        theta0=SCENARIO["theta0"],
        n=SCENARIO["n"],
        nsims=nsims * 5,
        seed=seed,
    )
    result = _paired(
        "B",
        "mixed procedure - PowerTOST's actual p(BE-sABEc)",
        be["instrument_p_mixed"],
        pt["p_mixed"],
        nsims,
        nsims * 5,
    )
    result["caveat"] = (
        "The be-stats side of experiment B uses the INSTRUMENT's unscaled "
        "branch, because be-stats refuses the unscaled replicate branch until "
        "Appendix C is implemented. This experiment therefore explains the "
        "oracle's number; it does not validate be-stats, and it is not a "
        "case file."
    )
    return result


def experiment_switch_probability(nsims: int, seed: int) -> dict:
    """Compare the two switching rules directly, in probability.

    The be-stats fraction is empirical over simulated studies. The comparators
    are exact: sWR^2 * dfRR / sigma^2_wR is chi-square on dfRR degrees of
    freedom, so P(sWR < c) = pchisq(dfRR * c^2 / sigma^2_wR, dfRR) with no
    simulation at all.
    """
    components = run_be_stats_side(nsims=nsims, seed=seed, **SCENARIO)
    df_rr = SCENARIO["n"] - 2
    s2w = math.log1p(SCENARIO["cv_wr"] ** 2)

    def exact(threshold: float) -> float:
        return float(stats.chi2.cdf(df_rr * threshold**2 / s2w, df_rr))

    exact_fda = exact(FDA_SWR_SWITCH)
    exact_pt = exact(POWERTOST_SWR_SWITCH)
    observed = components.below_switch / components.evaluated
    se = math.sqrt(exact_fda * (1 - exact_fda) / components.evaluated)
    return {
        "experiment": "switch probability",
        "what": "how often each rule routes a study to the unscaled branch",
        "fda_swr_threshold": FDA_SWR_SWITCH,
        "powertost_swr_threshold": POWERTOST_SWR_SWITCH,
        "threshold_difference": FDA_SWR_SWITCH - POWERTOST_SWR_SWITCH,
        "exact_p_below_fda": exact_fda,
        "exact_p_below_powertost": exact_pt,
        "probability_difference": exact_fda - exact_pt,
        "be_stats_observed_fraction_below": observed,
        "be_stats_vs_exact_sigmas": abs(observed - exact_fda) / se if se else None,
        "nsims": nsims,
        "seed": seed,
    }


def sweep(nsims: int, seed: int) -> list[dict]:
    """Across the switch, which is where the two quantities separate.

    The prediction being tested is specific: the gap between the scaled
    criterion alone and the mixed procedure should be largest where the most
    studies fall below the switch, and should vanish once essentially none do.
    A sweep that only showed a gap at one CV would be consistent with many
    explanations; a sweep whose gap tracks the switching fraction is consistent
    with one.
    """
    rows = []
    for cv in (0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33, 0.35, 0.40, 0.60):
        components = run_be_stats_side(
            cv_wr=cv,
            cv_wt=cv,
            theta0=SCENARIO["theta0"],
            n=SCENARIO["n"],
            design=SCENARIO["design"],
            nsims=nsims,
            seed=seed,
        )
        p = components.proportions()
        rows.append(
            {
                "cv_wr": cv,
                "sigma_wr": math.sqrt(math.log1p(cv**2)),
                "fraction_below_switch": p["fraction_below_switch"],
                "p_scaled_criterion_alone": p["p_scaled_criterion_alone"],
                "instrument_p_mixed": p["instrument_p_mixed"],
                "gap": p["p_scaled_criterion_alone"] - p["instrument_p_mixed"],
                "nsims": nsims,
            }
        )
    return rows


def reproducibility(nsims_high: int, seeds: tuple[int, ...]) -> dict:
    """Is the original 0.01238 a stable feature or a seed accident?

    Point 2 of the brief. If the gap is Monte Carlo variation it will move
    around across seeds and shrink with nsims; if it is a difference between
    two definitions it will sit still.
    """
    rows = []
    for seed in seeds:
        components = run_be_stats_side(nsims=nsims_high, seed=seed, **SCENARIO)
        p = components.proportions()
        rows.append(
            {
                "seed": seed,
                "nsims": nsims_high,
                "p_scaled_criterion_alone": p["p_scaled_criterion_alone"],
                "instrument_p_mixed": p["instrument_p_mixed"],
                "gap": p["p_scaled_criterion_alone"] - p["instrument_p_mixed"],
                "fraction_below_switch": p["fraction_below_switch"],
            }
        )
    gaps = [r["gap"] for r in rows]
    return {
        "runs": rows,
        "gap_mean": sum(gaps) / len(gaps),
        "gap_min": min(gaps),
        "gap_max": max(gaps),
        "gap_range": max(gaps) - min(gaps),
        "original_observed_difference": 0.01238,
        "interpretation": "a difference that survives every seed and does not "
        "shrink with nsims is not Monte Carlo variation",
    }


def _paired(
    name: str, what: str, left: float, right: float, n_left: int, n_right: int
) -> dict:
    pooled = (left * n_left + right * n_right) / (n_left + n_right)
    variance = pooled * (1 - pooled) * (1 / n_left + 1 / n_right)
    sigmas = abs(left - right) / math.sqrt(variance) if variance > 0 else None
    return {
        "experiment": name,
        "what": what,
        "be_stats": left,
        "instrument": right,
        "difference": left - right,
        "sigmas": sigmas,
        "nsims_be_stats": n_left,
        "nsims_instrument": n_right,
    }


# ------------------------------------------------------------------- main ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nsims", type=int, default=20000)
    parser.add_argument("--nsims-high", type=int, default=50000)
    parser.add_argument("--sweep-nsims", type=int, default=8000)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="small counts, for checking the script runs rather than for evidence",
    )
    args = parser.parse_args(argv)

    if args.quick:
        args.nsims, args.nsims_high, args.sweep_nsims = 400, 600, 300

    seeds = (20260828, 20260829, 20260830)
    evidence = {
        "finding_id": FINDING_ID,
        "generated": datetime.now(timezone.utc).isoformat(),
        "scenario": dict(SCENARIO),
        "instrument_disclaimer": (
            "`powertost_reproduction` is a transcription of PowerTOST 1.5-7 "
            "R/power_RSABE2L_isc.R. It explains the oracle; it cannot "
            "corroborate it. The corroboration is the corrected case files "
            "driving the real PowerTOST in CI."
        ),
        "data_generating_process": verify_data_generating_process(
            args.nsims, seeds[0]
        ),
        "experiment_a": experiment_a(args.nsims, seeds[0]),
        "experiment_b": experiment_b(args.nsims, seeds[0]),
        "switch_probability": experiment_switch_probability(args.nsims, seeds[0]),
        "sweep": sweep(args.sweep_nsims, seeds[0]),
        "reproducibility": reproducibility(args.nsims_high, seeds),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    dgp = evidence["data_generating_process"]
    print(f"{FINDING_ID} investigation")
    print("=" * 70)
    print(
        f"DGP        sWR^2 mean {dgp['observed_mean_s2wr']:.6f} vs exact "
        f"{dgp['expected_mean_s2wr']:.6f}, KS p = {dgp['ks_p_value']:.3f}"
    )
    for key in ("experiment_a", "experiment_b"):
        e = evidence[key]
        print(
            f"{e['experiment']:<10} {e['what']}\n"
            f"           be-stats {e['be_stats']:.5f}  instrument "
            f"{e['instrument']:.5f}  diff {e['difference']:+.5f}  "
            f"({e['sigmas']:.2f} sigma)"
        )
    sw = evidence["switch_probability"]
    print(
        f"switch     FDA {sw['fda_swr_threshold']} -> P(below) "
        f"{sw['exact_p_below_fda']:.5f};  PowerTOST "
        f"{sw['powertost_swr_threshold']:.6f} -> {sw['exact_p_below_powertost']:.5f}"
        f"  (difference {sw['probability_difference']:+.5f})"
    )
    print()
    print(f"{'CVwR':>6} {'below switch':>13} {'scaled':>9} {'mixed':>9} {'gap':>9}")
    for row in evidence["sweep"]:
        print(
            f"{row['cv_wr']:>6.2f} {row['fraction_below_switch']:>13.4f} "
            f"{row['p_scaled_criterion_alone']:>9.5f} "
            f"{row['instrument_p_mixed']:>9.5f} {row['gap']:>9.5f}"
        )
    rep = evidence["reproducibility"]
    print()
    print(
        f"gap across {len(rep['runs'])} seeds at nsims={args.nsims_high}: "
        f"{rep['gap_min']:.5f} to {rep['gap_max']:.5f} "
        f"(range {rep['gap_range']:.5f}); originally observed "
        f"{rep['original_observed_difference']}"
    )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
