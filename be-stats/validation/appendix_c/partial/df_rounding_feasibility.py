"""How much denominator df does EMA's two-decimal output actually pin down?

THE QUESTION THIS EXISTS TO ANSWER

VAL-FDA-APPENDIX-C-002 records a 2.94 df disagreement on EMA Data set II:

    df implied by the published CI    19.603
    df reported by ReplicateBE.jl     22.540

The first number has been carried through three PRs and it looks precise to
three decimals. It is not a published value. It is the result of INVERTING a
confidence interval that EMA printed to two decimal places, using a standard
error EMA never published at all.

Inverting rounded output amplifies the rounding. Before anyone runs SAS to
settle which df is right, the cheaper question is whether the published output
distinguishes them at all - and that is pure arithmetic.

THE KEY SIMPLIFICATION

The half-width on the log scale depends only on the RATIO of the two published
limits, not on the point estimate:

    half_width = (log U - log L) / 2 = log(U / L) / 2

So the estimate's own rounding does not enter the half-width, and the feasible
half-width follows directly from the rounding intervals of L and U:

    L in [97.045, 97.055)      U in [107.755, 107.765)

Then t(0.95, df) = half_width / SE, and t is strictly decreasing in df, so each
extreme of the half-width maps to one end of a df interval. A LARGER half-width
means a LARGER t and therefore a SMALLER df.

WHAT IS ASSUMED, AND HOW CIRCULAR IT IS

The standard error is not published, so one has to be assumed. The value used
is 0.0303172, which VAL-FDA-APPENDIX-C-001 and -002 record as agreed EXACTLY
by nlme, glmmTMB and ReplicateBE.jl - three independent fits. That is much
weaker than assuming ReplicateBE's df, but it is not nothing, so the analysis
below reports sensitivity to the SE as well and does not rest on a point value.

Usage:  python df_rounding_feasibility.py [output.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scipy import optimize, stats

#: EMA/618604/2008 Rev. 13, Method C, Data set II. Printed to two decimals.
PUBLISHED_ESTIMATE = 102.26
PUBLISHED_LOWER = 97.05
PUBLISHED_UPPER = 107.76

#: Half a unit in the last printed place. EMA prints two decimals, so a
#: printed 97.05 means a true value in [97.045, 97.055).
HALF_ULP = 0.005

#: Agreed to every digit shown by nlme, glmmTMB and ReplicateBE.jl. NOT
#: published by EMA - see the module docstring on how circular this is.
AGREED_SE = 0.030317219371948898

#: The two candidate answers this analysis is asked to discriminate.
DF_INVERTED_FROM_PUBLISHED_CI = 19.603
DF_REPLICATEBE = 22.540250688073332

ALPHA = 0.05  # one-sided; the 90% interval FDA's ALPHA=0.1 asks for


def df_for_t(t_value: float) -> float:
    """Invert t(0.95, df) = t_value. Decreasing in df, so bracket generously."""
    if t_value <= stats.t.ppf(1.0 - ALPHA, 1e7):
        return math.inf
    return float(
        optimize.brentq(
            lambda d: float(stats.t.ppf(1.0 - ALPHA, d)) - t_value,
            1e-6,
            1e7,
            xtol=1e-12,
            rtol=1e-14,
        )
    )


def df_interval_from_ratio(standard_error: float) -> tuple[float, float]:
    """The df interval implied by the two published limits alone.

    Uses only log(U/L), so the point estimate and its own rounding play no
    part. Widest half-width pairs the largest admissible U with the smallest
    admissible L, and gives the SMALLEST df.
    """
    widest = math.log(
        (PUBLISHED_UPPER + HALF_ULP) / (PUBLISHED_LOWER - HALF_ULP)
    ) / 2.0
    narrowest = math.log(
        (PUBLISHED_UPPER - HALF_ULP) / (PUBLISHED_LOWER + HALF_ULP)
    ) / 2.0
    # Larger half-width -> larger t -> smaller df.
    return (
        df_for_t(widest / standard_error),
        df_for_t(narrowest / standard_error),
    )


def reproduces_published(estimate_log: float, standard_error: float, df: float):
    """Does this (estimate, SE, df) print exactly what EMA printed?

    All three published numbers, at the precision they were printed to. This
    is the strictest form of the question and the one that matters: a df is
    compatible with the source if and only if it reproduces the source.
    """
    half = float(stats.t.ppf(1.0 - ALPHA, df)) * standard_error
    estimate = 100.0 * math.exp(estimate_log)
    lower = 100.0 * math.exp(estimate_log - half)
    upper = 100.0 * math.exp(estimate_log + half)
    return (
        round(estimate, 2) == PUBLISHED_ESTIMATE
        and round(lower, 2) == PUBLISHED_LOWER
        and round(upper, 2) == PUBLISHED_UPPER,
        (estimate, lower, upper),
    )


def feasible_df_window(
    estimate_log: float, standard_error: float
) -> tuple[float | None, float | None]:
    """Scan df for the contiguous window that reproduces all three numbers.

    A scan rather than a solve, deliberately: the constraint is a conjunction
    of three rounding predicates and the feasible set is not guaranteed a
    priori to be a single interval. Scanning finds out rather than assuming.

    The scan is bracketed by the ratio-only interval, which is a strict
    superset: the ratio constraint is implied by the two limit constraints, so
    nothing satisfying all three can lie outside it. A small margin is added so
    the bracket cannot clip a genuine endpoint.
    """
    ratio_lo, ratio_hi = df_interval_from_ratio(standard_error)
    if not math.isfinite(ratio_hi):
        return None, None
    span = ratio_hi - ratio_lo
    lo = max(1e-3, ratio_lo - 0.05 * span - 0.01)
    hi = ratio_hi + 0.05 * span + 0.01

    steps = 4000
    hits: list[float] = []
    for i in range(steps + 1):
        df = lo + (hi - lo) * i / steps
        ok, _ = reproduces_published(estimate_log, standard_error, df)
        if ok:
            hits.append(df)
    if not hits:
        return None, None
    return min(hits), max(hits)


def standard_error_that_would_make_df_compatible(df: float) -> tuple[float, float]:
    """What would the SE have to be for this df to reprint EMA's interval?

    THE DECISIVE SENSITIVITY, and the reason this analysis does not stop at
    "22.540 is outside the range".

    The df conclusion is only as good as the assumed standard error, which EMA
    never published. Rather than assert that the SE is right, invert the
    question: hold the candidate df fixed, and ask what SE the published
    interval would then require. Comparing that with the SE three engines agree
    on turns a claim about df into a claim about SE - which is checkable
    against three independent fits instead of none.
    """
    t_value = float(stats.t.ppf(1.0 - ALPHA, df))
    widest = math.log(
        (PUBLISHED_UPPER + HALF_ULP) / (PUBLISHED_LOWER - HALF_ULP)
    ) / 2.0
    narrowest = math.log(
        (PUBLISHED_UPPER - HALF_ULP) / (PUBLISHED_LOWER + HALF_ULP)
    ) / 2.0
    return narrowest / t_value, widest / t_value


def feasible_df_over_all_admissible_estimates(
    standard_error: float,
) -> tuple[float | None, float | None]:
    """Union of the strict window over every estimate that prints as 102.26.

    The strict window depends on which point estimate is used, and the true one
    is unknown - EMA printed 102.26 and the fits give 102.2644. Fixing either
    would be a choice; taking the union over the whole rounding band is not.
    """
    best_lo: float | None = None
    best_hi: float | None = None
    steps = 41
    for i in range(steps):
        percent = (PUBLISHED_ESTIMATE - HALF_ULP) + (
            2.0 * HALF_ULP * i / (steps - 1)
        )
        lo, hi = feasible_df_window(math.log(percent / 100.0), standard_error)
        if lo is None:
            continue
        best_lo = lo if best_lo is None else min(best_lo, lo)
        best_hi = hi if best_hi is None else max(best_hi, hi)
    return best_lo, best_hi


def main() -> int:
    estimate_log = math.log(PUBLISHED_ESTIMATE / 100.0)

    # 1. The ratio-only interval: what the two printed limits pin down, with
    #    the point estimate playing no part at all.
    ratio_lo, ratio_hi = df_interval_from_ratio(AGREED_SE)

    # 2. The strict interval: df values that actually reprint EMA's output,
    #    using the estimate implied by the published 102.26.
    strict_lo, strict_hi = feasible_df_window(estimate_log, AGREED_SE)

    # 3. Sensitivity to the assumed SE, which is the one unpublished input.
    sensitivity = {}
    for pct in (0.1, 0.5, 1.0):
        for sign, label in ((-1, "minus"), (1, "plus")):
            se = AGREED_SE * (1.0 + sign * pct / 100.0)
            lo, hi = df_interval_from_ratio(se)
            sensitivity[f"se_{label}_{pct}pct"] = {
                "standard_error": se,
                "df_low": lo,
                "df_high": hi,
            }

    # 2b. The same, but not privileging any single point estimate.
    union_lo, union_hi = feasible_df_over_all_admissible_estimates(AGREED_SE)

    # 4. Invert the question onto the one unpublished input.
    se_needed = {}
    for name, df in (
        ("df_replicatebe", DF_REPLICATEBE),
        ("df_inverted_from_published_ci", DF_INVERTED_FROM_PUBLISHED_CI),
    ):
        lo, hi = standard_error_that_would_make_df_compatible(df)
        se_needed[name] = {
            "df": df,
            "standard_error_low": lo,
            "standard_error_high": hi,
            "agreed_standard_error": AGREED_SE,
            "relative_shift_low_percent": 100.0 * (lo - AGREED_SE) / AGREED_SE,
            "relative_shift_high_percent": 100.0 * (hi - AGREED_SE) / AGREED_SE,
        }

    verdict_replicatebe = ratio_lo <= DF_REPLICATEBE <= ratio_hi
    verdict_inverted = ratio_lo <= DF_INVERTED_FROM_PUBLISHED_CI <= ratio_hi

    report = {
        "schema": "be-stats/appendix-c-partial-df-rounding/1",
        "question": (
            "Does EMA's two-decimal published output for Data set II "
            "distinguish df 19.603 from df 22.540 at all?"
        ),
        "published": {
            "estimate_percent": PUBLISHED_ESTIMATE,
            "ci_lower_percent": PUBLISHED_LOWER,
            "ci_upper_percent": PUBLISHED_UPPER,
            "printed_to_decimals": 2,
            "standard_error": None,
            "denominator_df": None,
        },
        "assumed_standard_error": {
            "value": AGREED_SE,
            "basis": (
                "Agreed to every digit shown by nlme, glmmTMB and "
                "ReplicateBE.jl - three independent fits. NOT published by "
                "EMA. See VAL-FDA-APPENDIX-C-001 and -002."
            ),
        },
        "df_range_compatible_with_two_decimal_rounding": {
            "method": (
                "log(U/L)/2 depends only on the ratio of the published limits, "
                "so the point estimate and its rounding do not enter. Each "
                "extreme of the admissible half-width inverts to one end of a "
                "df interval; t is decreasing in df, so the widest half-width "
                "gives the smallest df."
            ),
            "df_low_compatible_with_rounding": ratio_lo,
            "df_high_compatible_with_rounding": ratio_hi,
        },
        "df_range_that_reprints_all_three_published_numbers": {
            "method": (
                "Scan of df, keeping those for which estimate, lower and upper "
                "all round to the published two decimals."
            ),
            "using_the_published_estimate_exactly": {
                "df_low": strict_lo,
                "df_high": strict_hi,
            },
            "union_over_every_estimate_that_prints_as_102_26": {
                "df_low": union_lo,
                "df_high": union_hi,
                "why": (
                    "The strict window moves with the point estimate, and the "
                    "true estimate is unknown - EMA printed 102.26, the fits "
                    "give 102.2644. Fixing either would be a choice; the union "
                    "over the rounding band is not."
                ),
            },
        },
        "standard_error_each_candidate_df_would_require": se_needed,
        "candidates": {
            "df_inverted_from_published_ci": {
                "value": DF_INVERTED_FROM_PUBLISHED_CI,
                "inside_rounding_compatible_range": verdict_inverted,
                "note": (
                    "NOT a published df. It is one inversion of rounded output "
                    "against an unpublished SE, and has been quoted to three "
                    "decimals throughout this project."
                ),
            },
            "df_replicatebe": {
                "value": DF_REPLICATEBE,
                "inside_rounding_compatible_range": verdict_replicatebe,
            },
        },
        "sensitivity_to_the_assumed_standard_error": sensitivity,
    }

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "df_rounding_feasibility.json"
    )
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("EMA Data set II - what the published two decimals pin down")
    print(f"  assumed SE (unpublished, three engines agree): {AGREED_SE:.9f}")
    print()
    print("  df compatible with the printed CI, from the RATIO alone:")
    print(f"    [{ratio_lo:.4f}, {ratio_hi:.4f}]")
    print("  df that reprints all three published numbers:")
    print(
        f"    at the published estimate exactly: [{strict_lo:.4f}, {strict_hi:.4f}]"
        if strict_lo is not None
        else "    NONE"
    )
    print(
        f"    union over all estimates printing 102.26: "
        f"[{union_lo:.4f}, {union_hi:.4f}]"
        if union_lo is not None
        else "    NONE"
    )
    print()
    print(f"  19.603 (inverted)   inside ratio range: {verdict_inverted}")
    print(f"  22.540 (ReplicateBE) inside ratio range: {verdict_replicatebe}")
    print()
    print("  SE each candidate df would require, against the agreed 0.0303172:")
    for key, value in se_needed.items():
        print(
            f"    {key:<32} SE in "
            f"[{value['standard_error_low']:.7f}, {value['standard_error_high']:.7f}]"
            f"  = {value['relative_shift_low_percent']:+.2f}% to "
            f"{value['relative_shift_high_percent']:+.2f}%"
        )
    print()
    for key, value in sensitivity.items():
        print(f"  {key:<22} df in [{value['df_low']:.4f}, {value['df_high']:.4f}]")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
