"""An independent REML fit and Satterthwaite df, written from the definitions.

VALIDATION-ONLY. NOT PRODUCTION CODE, AND IT MUST NEVER BE IMPORTED BY IT.

This file deliberately imports NOTHING from `be_stats`. It exists to answer one
question that the production implementation cannot be asked to answer about
itself: for EMA Data set II - a three-sequence PARTIAL replicate - what is the
Satterthwaite denominator df under FDA's Appendix C model?

    df implied by EMA's published CI     19.603   (an inversion, not a source)
    df reported by ReplicateBE.jl 1.0.15 22.540

A third implementation only helps if it is genuinely independent, so this one
differs from production in every choice where a choice exists.

WHERE IT DIFFERS FROM PRODUCTION, AND WHY THAT MATTERS

    parameterisation   production uses a Cholesky factor of G plus LOG residual
                       variances, chosen so the rho = 1 boundary is an interior
                       point. This uses the five covariance parameters DIRECTLY:
                       (s2_BT, s2_BR, s_BTBR, s2_WT, s2_WR).

                       That single change is what makes everything below exact.
                       V is LINEAR in these parameters - V = sum_j theta_j G_j
                       with constant G_j - so every derivative has a closed
                       form and the second derivatives of V vanish identically.
                       Production's parameterisation is non-linear, which is why
                       it must difference its gradient to reach the Hessian.

    information        production differentiates its analytic gradient
                       numerically. This computes BOTH the observed and the
                       expected information in closed form:

                           I_obs[j,k] = y'P V_j P V_k P y - tr(P V_j P V_k)/2
                           I_exp[j,k] = tr(P V_j P V_k) / 2

                       Reporting both is not thoroughness for its own sake. If
                       the 19.6-vs-22.5 gap is the difference between observed
                       and expected information, that IS the answer, and no
                       amount of care about anything else would find it.

    contrast gradient  closed form, g_j = L'C X'V^-1 V_j V^-1 X C L, rather than
                       differenced.

    linear algebra     dense whole-sample matrices, no block structure and no
                       profiling. Slower and more obviously correct. At n = 298
                       the cost is irrelevant and the independence is the point.

CONTROL BEFORE CONCLUSION

Data set II is the question, so it cannot also be the check. Data set I is the
control: EMA published its interval, and the production code reproduces it. An
independent implementation that cannot reproduce Data set I has no standing to
adjudicate Data set II, and this script refuses to report a partial-replicate
verdict unless the control passes first.

Usage:
    python independent_satterthwaite.py <datasets.json> [output.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import linalg, optimize, stats

ALPHA = 0.05  # one-sided; FDA's ALPHA=0.1 gives the 90% interval

#: Sequence letters as EMA printed them. Data set I uses A for TEST and B for
#: reference, so ABAB is TRTR - the opposite reading inverts every result.
SEQUENCE_CODES = {
    "ABAB": "TRTR",
    "BABA": "RTRT",
    "1": "TRR",
    "2": "RTR",
    "3": "RRT",
}

PUBLISHED = {
    "data_set_i": {
        "estimate_percent": 115.66,
        "ci": (107.10, 124.89),
        "design": "2x2x4 fully replicate, 77 subjects, 8 incomplete",
        "role": "CONTROL - the implementation must reproduce this to be trusted",
    },
    "data_set_ii": {
        "estimate_percent": 102.26,
        "ci": (97.05, 107.76),
        "design": "2x3x3 partial replicate (TRR/RTR/RRT), 24 subjects",
        "role": "THE QUESTION",
    },
}


# --------------------------------------------------------------- the model ---


def build(rows: list[dict]) -> dict:
    """Design matrices for MODEL Y = SEQ PER TRT, plus the Z indicators.

    Reference-cell coding with the TEST indicator LAST, so the 'T vs. R'
    contrast is the unit vector on the final column. Rows are ordered by
    subject so the covariance is block diagonal by construction.
    """
    records = []
    for row in rows:
        sequence = SEQUENCE_CODES[str(row["sequence"])]
        treatment = str(row["formulation"]).strip().upper()
        records.append(
            {
                "subject": str(row["subject"]),
                "sequence": sequence,
                "period": int(row["period"]),
                "is_test": treatment in ("T", "A"),
                "y": math.log(float(row["value"])),
            }
        )
    records.sort(key=lambda r: (r["subject"], r["period"]))

    sequences = sorted({r["sequence"] for r in records})
    periods = sorted({r["period"] for r in records})
    subjects = sorted({r["subject"] for r in records})

    columns = [np.ones(len(records))]
    names = ["intercept"]
    for s in sequences[1:]:
        columns.append(np.array([1.0 if r["sequence"] == s else 0.0 for r in records]))
        names.append(f"sequence[{s}]")
    for p in periods[1:]:
        columns.append(np.array([1.0 if r["period"] == p else 0.0 for r in records]))
        names.append(f"period[{p}]")
    columns.append(np.array([1.0 if r["is_test"] else 0.0 for r in records]))
    names.append("treatment[T]")

    x = np.column_stack(columns)
    y = np.array([r["y"] for r in records])
    is_test = np.array([r["is_test"] for r in records], dtype=bool)
    subject_index = np.array([subjects.index(r["subject"]) for r in records])

    return {
        "X": x,
        "y": y,
        "is_test": is_test,
        "subject_index": subject_index,
        "column_names": names,
        "n_subjects": len(subjects),
        "n_observations": len(records),
        "records": records,
    }


def basis_matrices(data: dict) -> list[np.ndarray]:
    """The five constant G_j with V = sum_j theta_j G_j.

    theta = (s2_BT, s2_BR, s_BTBR, s2_WT, s2_WR).

    V is LINEAR in these, which is the entire reason this implementation can be
    exact where production has to difference. Built densely and once.
    """
    n = data["n_observations"]
    test = data["is_test"].astype(float)
    reference = 1.0 - test
    same_subject = (
        data["subject_index"][:, None] == data["subject_index"][None, :]
    ).astype(float)

    tt = np.outer(test, test) * same_subject
    rr = np.outer(reference, reference) * same_subject
    tr = (np.outer(test, reference) + np.outer(reference, test)) * same_subject

    return [
        tt,                    # s2_BT
        rr,                    # s2_BR
        tr,                    # s_BTBR   (appears twice, off-diagonal)
        np.diag(test),         # s2_WT
        np.diag(reference),    # s2_WR
    ]


def covariance(theta: np.ndarray, bases: list[np.ndarray]) -> np.ndarray:
    return sum(t * b for t, b in zip(theta, bases))


def is_admissible(theta: np.ndarray) -> bool:
    """G positive semi-definite and both residual variances positive.

    FA0(2) is PSD by construction; parameterising directly gives up that
    guarantee, so it is imposed explicitly. Note the determinant condition
    admits NEGATIVE s_BTBR, which FDA's model permits - a constraint to rho >= 0
    here would reproduce the very limitation PR #62 found in ReplicateBE.
    """
    s2_bt, s2_br, s_btbr, s2_wt, s2_wr = theta
    if s2_bt <= 0 or s2_br <= 0 or s2_wt <= 0 or s2_wr <= 0:
        return False
    return s2_bt * s2_br - s_btbr**2 >= -1e-14


def reml_objective(theta: np.ndarray, data: dict, bases: list[np.ndarray]) -> float:
    """-2 logREML alone, skipping everything the optimiser does not read.

    Separate from `reml_pieces` purely for speed. P is several dense 298x298
    products and is needed only once per fit, at the optimum, for the
    information matrices - but building it inside the objective made a
    twelve-start fit on Data set I take longer than the whole rest of this
    investigation.
    ONE factorisation, reused. Measured before and after, because the first
    version called np.linalg.solve three times on the same V and took 66 ms per
    evaluation on Data set I - which, at thousands of evaluations per start,
    was the whole reason a twelve-start fit never finished.
    """
    x, y = data["X"], data["y"]
    v = covariance(theta, bases)
    v = 0.5 * (v + v.T)
    try:
        factor = linalg.cho_factor(v, lower=True, check_finite=False)
    except (linalg.LinAlgError, np.linalg.LinAlgError):
        return math.inf
    logdet_v = 2.0 * float(np.sum(np.log(np.diag(factor[0]))))

    solved = linalg.cho_solve(
        factor, np.column_stack([x, y]), check_finite=False
    )
    vinv_x, vinv_y = solved[:, :-1], solved[:, -1]

    xtvix = x.T @ vinv_x
    sign_c, logdet_xtvix = np.linalg.slogdet(xtvix)
    if sign_c <= 0:
        return math.inf

    beta = np.linalg.solve(xtvix, x.T @ vinv_y)
    # r'V^-1 r expanded through the factorisation already computed, so no
    # further solve is needed: r = y - X beta, and V^-1 r = vinv_y - vinv_X beta.
    residual = y - x @ beta
    quadratic = float(residual @ (vinv_y - vinv_x @ beta))
    return logdet_v + logdet_xtvix + quadratic


def reml_pieces(theta: np.ndarray, data: dict, bases: list[np.ndarray]):
    """Returns (-2 logREML, V, Vinv, C, beta, P). Dense and unprofiled."""
    x, y = data["X"], data["y"]
    v = covariance(theta, bases)
    v = 0.5 * (v + v.T)

    sign, logdet_v = np.linalg.slogdet(v)
    if sign <= 0:
        return None

    vinv = np.linalg.inv(v)
    xtvix = x.T @ vinv @ x
    sign_c, logdet_xtvix = np.linalg.slogdet(xtvix)
    if sign_c <= 0:
        return None

    c = np.linalg.inv(xtvix)
    beta = c @ (x.T @ vinv @ y)
    residual = y - x @ beta
    quadratic = float(residual.T @ vinv @ residual)

    p = vinv - vinv @ x @ c @ x.T @ vinv
    objective = logdet_v + logdet_xtvix + quadratic
    return objective, v, vinv, c, beta, p


def fit(data: dict, bases: list[np.ndarray]) -> dict:
    """REML by direct minimisation over the five covariance parameters.

    Nelder-Mead then Powell, from each of several starts. Neither optimiser is
    production's, and the parameterisation differs too, so agreement on the
    answer is not agreement by shared machinery.

    MULTI-START IS NOT OPTIONAL HERE, AND THAT WAS LEARNED THE HARD WAY.

    A single start from the method of moments converged on Data set II to a
    point with -2logREML = -151.7627, worse than the -151.9744 available at
    ReplicateBE's reported covariance. The inferior optimum sat exactly on the
    rho = 1 boundary and gave a different standard error, which would have
    corrupted every comparison downstream.

    The partial replicate is why. Each subject contributes ONE test
    measurement, so s2_BT and s2_WT are exactly non-identifiable - only their
    sum is - and the likelihood has a flat ridge that a single local search
    slides along. Starting from several correlations and several splits of the
    total variance finds the ridge's true low point instead of the first place
    the simplex stalls.
    """
    y = data["y"]
    variance = float(np.var(y, ddof=1))

    # The ridge that made multi-start necessary is a PARTIAL-replicate problem:
    # it exists because each subject has one test measurement. A fully
    # replicate design has two, s2_BT and s2_WT separate cleanly, and the extra
    # starts buy nothing while costing a dense 298x298 solve per evaluation.
    # So the search is sized to the design rather than to the worst case.
    partial = data["n_observations"] < 4 * data["n_subjects"]
    correlations = (0.0, 0.3, 0.5, 0.7, 0.9, 0.99) if partial else (0.5,)
    betweens = (0.2, 0.4, 0.6, 0.8) if partial else (0.5,)

    starts = []
    for between in betweens:
        for rho in correlations:
            s2_bt = variance * between
            s2_br = variance * between
            starts.append(
                np.array([
                    s2_bt, s2_br, rho * math.sqrt(s2_bt * s2_br),
                    variance * (1.0 - between), variance * (1.0 - between),
                ])
            )

    def objective(theta: np.ndarray) -> float:
        if not is_admissible(theta):
            return 1e12
        value = reml_objective(theta, data, bases)
        return 1e12 if not math.isfinite(value) else value

    best_theta, best_value, any_success = None, math.inf, False
    for start in starts:
        # Caps sized for a five-parameter simplex, not for safety. An earlier
        # version allowed 100000 evaluations per start; on Data set I that is
        # a 298x298 inverse per evaluation and the run did not finish. Nelder-
        # Mead settles here in low thousands, and Powell polishes from there.
        first = optimize.minimize(
            objective, start, method="Nelder-Mead",
            options={"maxiter": 4000, "maxfev": 4000,
                     "xatol": 1e-12, "fatol": 1e-12},
        )
        second = optimize.minimize(
            objective, first.x, method="Powell",
            options={"maxfev": 6000, "xtol": 1e-12, "ftol": 1e-12},
        )
        for candidate in (first, second):
            if candidate.fun < best_value and is_admissible(candidate.x):
                best_value, best_theta = float(candidate.fun), candidate.x
                any_success = any_success or bool(candidate.success)

    pieces = reml_pieces(best_theta, data, bases)
    objective_value, v, vinv, c, beta, p = pieces
    return {
        "theta": best_theta,
        "minus2_logreml": objective_value,
        "V": v, "Vinv": vinv, "C": c, "beta": beta, "P": p,
        "converged": any_success,
        "n_starts": len(starts),
    }


# ------------------------------------------------- Satterthwaite, in closed form ---


def information_matrices(fitted: dict, data: dict, bases: list[np.ndarray]):
    """Observed and expected information for theta, both exact.

    Because V is linear in theta, all second derivatives of V vanish and:

        d(logL)/dtheta_j          = -1/2 [ tr(P V_j) - y'P V_j P y ]
        -d2(logL)/dtheta_j dtheta_k = y'P V_j P V_k P y - tr(P V_j P V_k)/2

    Taking expectations of the quadratic form, E[y'P V_j P V_k P y] =
    tr(P V_j P V_k), leaves the expected information as half that trace.

    No differencing anywhere.
    """
    p = fitted["P"]
    y = data["y"]
    py = p @ y
    k = len(bases)

    pv = [p @ b for b in bases]

    observed = np.zeros((k, k))
    expected = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            trace = float(np.trace(pv[i] @ pv[j]))
            quad = float(py.T @ bases[i] @ p @ bases[j] @ py)
            observed[i, j] = quad - 0.5 * trace
            expected[i, j] = 0.5 * trace
    observed = 0.5 * (observed + observed.T)
    expected = 0.5 * (expected + expected.T)
    return observed, expected


def contrast_gradient(fitted: dict, data: dict, bases: list[np.ndarray],
                      contrast: np.ndarray) -> np.ndarray:
    """g_j = d Var(L'beta) / d theta_j = L'C X'V^-1 V_j V^-1 X C L. Closed form."""
    x = data["X"]
    c, vinv = fitted["C"], fitted["Vinv"]
    a = vinv @ x @ c @ contrast
    return np.array([float(a.T @ b @ a) for b in bases])


#: G is treated as rank deficient - the fit sitting ON the PSD boundary - when
#: the correlation reaches this close to +/-1. Data set I reaches 1 - 1e-12.
BOUNDARY_TOLERANCE = 1e-8


def boundary_reduction(theta: np.ndarray) -> np.ndarray | None:
    """Jacobian onto the rank-1 surface, or None if the fit is interior.

    WHY A BOUNDARY SOLUTION NEEDS FEWER PARAMETERS, NOT A PSEUDO-INVERSE

    When rho reaches +/-1 the estimate sits on the edge of the PSD cone and
    cannot move outward. Counting five free covariance parameters there
    overstates the uncertainty in theta and understates the df - on Data set I
    it gives 75 where EMA's published interval requires about 208.

    So the constraint is imposed explicitly: s_BTBR = +/- sqrt(s2_BT * s2_BR),
    leaving phi = (s2_BT, s2_BR, s2_WT, s2_WR), and the information and the
    gradient are mapped into those coordinates by the chain rule.

    This is what SAS does when it holds a covariance parameter at a boundary,
    and - established rather than assumed - it reproduces EMA's published
    interval where the unconstrained version does not.
    """
    s2_bt, s2_br, s_btbr = theta[0], theta[1], theta[2]
    denominator = math.sqrt(s2_bt * s2_br)
    if denominator <= 0:
        return None
    if abs(abs(s_btbr / denominator) - 1.0) > BOUNDARY_TOLERANCE:
        return None

    sign = 1.0 if s_btbr >= 0 else -1.0
    jacobian = np.zeros((5, 4))
    jacobian[0, 0] = 1.0
    jacobian[1, 1] = 1.0
    jacobian[2, 0] = sign * 0.5 * math.sqrt(s2_br / s2_bt)
    jacobian[2, 1] = sign * 0.5 * math.sqrt(s2_bt / s2_br)
    jacobian[3, 2] = 1.0
    jacobian[4, 3] = 1.0
    return jacobian


def satterthwaite(fitted: dict, data: dict, bases: list[np.ndarray],
                  contrast: np.ndarray, information: np.ndarray) -> float:
    """df = 2 (L'CL)^2 / (g' Var(theta) g), Var(theta) = information^-1.

    Reduced onto the constraint surface first when the fit is on the boundary.

    The pseudo-inverse remains, for a DIFFERENT and unavoidable reason: in a
    partial replicate each subject has one test measurement, so s2_BT and s2_WT
    are exactly non-identifiable and the information matrix is genuinely rank
    deficient by one. The contrast depends only on their SUM, which is
    identified, so the df is well defined - and measured to be stable across
    eight orders of magnitude of pseudo-inverse cutoff.
    """
    variance = float(contrast.T @ fitted["C"] @ contrast)
    g = contrast_gradient(fitted, data, bases, contrast)

    jacobian = boundary_reduction(fitted["theta"])
    if jacobian is not None:
        information = jacobian.T @ information @ jacobian
        g = jacobian.T @ g

    denominator = float(g.T @ np.linalg.pinv(information) @ g)
    if denominator <= 0:
        return math.inf
    return 2.0 * variance**2 / denominator


def analyse(name: str, rows: list[dict]) -> dict:
    data = build(rows)
    bases = basis_matrices(data)
    fitted = fit(data, bases)

    contrast = np.zeros(data["X"].shape[1])
    contrast[-1] = 1.0  # treatment[T] is the last column

    estimate = float(contrast @ fitted["beta"])
    standard_error = math.sqrt(float(contrast.T @ fitted["C"] @ contrast))

    observed, expected = information_matrices(fitted, data, bases)
    df_observed = satterthwaite(fitted, data, bases, contrast, observed)
    df_expected = satterthwaite(fitted, data, bases, contrast, expected)

    result = {
        "design": PUBLISHED[name]["design"],
        "role": PUBLISHED[name]["role"],
        "n_observations": data["n_observations"],
        "n_subjects": data["n_subjects"],
        "column_names": data["column_names"],
        "rank_X": int(np.linalg.matrix_rank(data["X"])),
        "n_fixed_effects": int(data["X"].shape[1]),
        "converged": fitted["converged"],
        "n_optimiser_starts": fitted["n_starts"],
        "minus2_logreml": fitted["minus2_logreml"],
        "subject_correlation": (
            fitted["theta"][2]
            / math.sqrt(fitted["theta"][0] * fitted["theta"][1])
        ),
        "on_psd_boundary": boundary_reduction(fitted["theta"]) is not None,
        "information_rank_observed": int(
            np.linalg.matrix_rank(
                information_matrices(fitted, data, bases)[0], tol=1e-6
            )
        ),
        "theta_named": {
            "s2_BT": fitted["theta"][0], "s2_BR": fitted["theta"][1],
            "s_BTBR": fitted["theta"][2], "s2_WT": fitted["theta"][3],
            "s2_WR": fitted["theta"][4],
        },
        "estimate_log": estimate,
        "estimate_percent": 100.0 * math.exp(estimate),
        "standard_error": standard_error,
        "denominator_df_observed_information": df_observed,
        "denominator_df_expected_information": df_expected,
        "published": PUBLISHED[name],
    }

    for label, df in (("observed", df_observed), ("expected", df_expected)):
        half = float(stats.t.ppf(1.0 - ALPHA, df)) * standard_error
        result[f"ci_percent_{label}_information"] = [
            100.0 * math.exp(estimate - half),
            100.0 * math.exp(estimate + half),
        ]
    return result


def reproduces(result: dict, information: str, tolerance: float = 0.005) -> bool:
    published = result["published"]
    ci = result[f"ci_percent_{information}_information"]
    return (
        abs(result["estimate_percent"] - published["estimate_percent"]) <= tolerance
        and abs(ci[0] - published["ci"][0]) <= tolerance
        and abs(ci[1] - published["ci"][1]) <= tolerance
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    datasets = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    results = {}
    for name in ("data_set_i", "data_set_ii"):
        if name not in datasets:
            continue
        results[name] = analyse(name, datasets[name])

    control = results.get("data_set_i")
    control_ok = control is not None and (
        reproduces(control, "observed") or reproduces(control, "expected")
    )

    report = {
        "schema": "be-stats/independent-satterthwaite/1",
        "what_this_is": (
            "A validation-only REML fit and Satterthwaite df written from the "
            "mathematical definitions, importing nothing from be_stats. "
            "Parameterised directly in the five covariance parameters, which "
            "makes V linear in theta and every derivative closed-form."
        ),
        "control_passed": control_ok,
        "control_note": (
            "Data set I is the control. Without it this is a third number "
            "rather than an adjudication."
        ),
        "results": results,
    }

    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "independent_satterthwaite.json"
    )
    out.write_text(json.dumps(report, indent=2, default=float) + "\n",
                   encoding="utf-8")

    for name, result in results.items():
        published = result["published"]
        print(f"=== {name}: {result['design']}")
        print(f"    role: {result['role']}")
        print(f"    n = {result['n_observations']} obs, "
              f"{result['n_subjects']} subjects, "
              f"rank(X) = {result['rank_X']} of {result['n_fixed_effects']}")
        print(f"    converged: {result['converged']} "
              f"({result['n_optimiser_starts']} starts)   "
              f"-2logREML = {result['minus2_logreml']:.6f}")
        print(f"    rho = {result['subject_correlation']:.10f}   "
              f"on PSD boundary: {result['on_psd_boundary']}   "
              f"information rank {result['information_rank_observed']} of 5")
        print(f"    estimate  {result['estimate_percent']:.5f}%   "
              f"published {published['estimate_percent']}")
        print(f"    SE        {result['standard_error']:.9f}")
        for label in ("observed", "expected"):
            df = result[f"denominator_df_{label}_information"]
            ci = result[f"ci_percent_{label}_information"]
            flag = "MATCHES" if reproduces(result, label) else "differs"
            print(f"    {label:<8} information: df {df:9.4f}   "
                  f"CI {ci[0]:.5f}, {ci[1]:.5f}   [{flag} published "
                  f"{published['ci'][0]}, {published['ci'][1]}]")
        theta = result["theta_named"]
        print("    theta: " + ", ".join(f"{k}={v:.8f}" for k, v in theta.items()))
        print()

    print(f"control passed: {control_ok}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
