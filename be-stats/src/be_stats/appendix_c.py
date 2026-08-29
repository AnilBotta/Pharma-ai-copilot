"""FDA Appendix C: unscaled average BE for a FULLY REPLICATE crossover.

THE MODEL, FROM THE SOURCE

FDA, *Statistical Approaches to Establishing Bioequivalence*, May 2026,
Appendix C:

    PROC MIXED;
    CLASSES SEQ SUBJ PER TRT;
    MODEL Y = SEQ PER TRT/ DDFM=SATTERTH;
    RANDOM TRT/TYPE=FA0(2) SUB=SUBJ G;
    REPEATED/GRP=TRT SUB=SUBJ;
    ESTIMATE 'T vs. R' TRT 1 -1/CL ALPHA=0.1;

Marginally, for subject i,

    y_i = X_i beta + Z_i b_i + e_i,   b_i ~ N(0, G),  e_i ~ N(0, R_i)
    V_i = Z_i G Z_i' + R_i

with `Z_i` the n_i x 2 treatment indicator, `G` the 2x2 subject-by-formulation
covariance, and `R_i` diagonal carrying sigma^2_WT on test rows and sigma^2_WR
on reference rows. Five parameters, exactly the five FDA's model estimates.

FULLY REPLICATE ONLY, AND WHY THAT IS A REGULATORY STATEMENT

PR #61 established a trustworthy numerical oracle for the fully replicate
design and NOT for the partial replicate one. ReplicateBE.jl reproduces EMA's
published SAS Method C output exactly on the 2x2x4 data set - estimate, 90%
interval, both within-subject CVs - and differs by 2.94 denominator degrees of
freedom on the 2x3x3 data set, a design its own validation claim never covered.

So this module fits 2x2x4 and REFUSES 2x3x3. That refusal is not a gap in the
arithmetic - the same code would happily produce a number - it is the absence
of anything to check that number against. See `VAL-FDA-APPENDIX-C-002`.

PARAMETERISATION, AND WHY IT MUST ADMIT THE BOUNDARY

    theta = (l11, l21, l22, log sigma^2_WT, log sigma^2_WR)  in R^5

    G = L L',   L = [[l11, 0], [l21, l22]]

That is FDA's FA0(2) exactly: `G = LL'` with `L` lower triangular, positive
semi-definite by construction, three free parameters spanning every symmetric
2x2.

The choice matters for one specific reason. On EMA Data set I - the data set
that validates everything else - the fitted subject-by-formulation correlation
is EXACTLY 1.000. In correlation coordinates that is the edge of the parameter
space and an optimiser has to be stopped from walking out of it. In these
coordinates it is `l22 = 0`, an ORDINARY INTERIOR POINT of R^5. The optimiser
reaches it by walking downhill, needs no bound, and nothing has to be clamped.

A consequence worth stating: `L` and `-L` give the same `G`, so the objective
is even in `l22` and its derivative there is exactly zero. That is a real
stationary point, not a numerical accident.

Asymptotics for a covariance parameter on the boundary of the PSD cone are
non-standard, and the denominator df computed there inherits that. SAS reports
one anyway and so does ReplicateBE.jl; this module matches them and says so
rather than pretending the question does not arise.

WHAT THIS MODULE DOES NOT DO

No Appendix G `Iij` contrast. No EMA Method A. No single-residual-variance
model. No containment df. Each of those produces a plausible number from a
different model, and PR #61 measured the cost: lmerTest's Satterthwaite df on
EMA Data set II is 35.94 where SAS implies 19.60 - a correct formula on the
wrong covariance structure, wrong by a factor of 1.8 and looking entirely
principled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, stats

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import VIA_PRIMARY_DOCUMENT, ValidationStatus
from be_stats.replicate import (
    DataError,
    ReplicateDesign,
    ReplicateObservation,
    ReplicateSequence,
    Treatment,
    identify_design,
    validate_subject_rows,
)
from be_stats.replicate_abe import APPENDIX_C_MODEL

#: One-sided level. FDA's `ALPHA=0.1` on a two-sided ESTIMATE statement is the
#: 90% interval, i.e. 0.05 in each tail.
ALPHA = 0.05

#: The conventional acceptance range, inclusive at both ends.
LOWER_LIMIT_PERCENT = 80.00
UPPER_LIMIT_PERCENT = 125.00

#: The designs this module will fit. FULLY_REPLICATE only - see the module
#: docstring, and `VAL-FDA-APPENDIX-C-002` for the evidence.
SUPPORTED_DESIGNS: frozenset[ReplicateDesign] = frozenset(
    {ReplicateDesign.FULLY_REPLICATE}
)


class AppendixCNotSupported(DataError):
    """This design has no validated Appendix C path in this package."""


# ------------------------------------------------------------ the dataset ---


@dataclass(frozen=True, slots=True)
class AppendixCObservation:
    subject_id: str
    sequence: ReplicateSequence
    period: int
    treatment: Treatment
    log_value: float


@dataclass(frozen=True, slots=True)
class AppendixCDataset:
    """Validated rows for an Appendix C fit.

    AVAILABLE CASE, per FDA section III: "An available case analysis could be
    done using SAS PROC MIXED, which uses all observed data." Contrasted there
    with PROC GLM, which "removes all subjects with any missing observations".

    So a subject short of a period is KEPT. That is neither Appendix G's rule -
    which needs both reference replicates because sWR is built from their
    difference - nor EMA Method A's. Three models in this package, three
    inclusion rules, and PR #60 established that mixing them changes results.
    """

    design: ReplicateDesign
    endpoint: str
    observations: tuple[AppendixCObservation, ...]
    diagnostics: tuple[Diagnostic, ...]
    subjects_received: tuple[str, ...]

    @property
    def subjects(self) -> tuple[str, ...]:
        seen: list[str] = []
        for o in self.observations:
            if o.subject_id not in seen:
                seen.append(o.subject_id)
        return tuple(seen)

    @classmethod
    def build(cls, observations: list[ReplicateObservation]) -> AppendixCDataset:
        if not observations:
            raise DataError("No observations were supplied.")
        endpoints = {o.endpoint for o in observations}
        if len(endpoints) != 1:
            raise DataError(
                f"Observations span {len(endpoints)} endpoints "
                f"({', '.join(sorted(endpoints))}). One endpoint per dataset."
            )
        endpoint = endpoints.pop()
        design = identify_design({o.sequence for o in observations})

        subjects_received: list[str] = []
        grouped: dict[str, list[ReplicateObservation]] = {}
        for obs in observations:
            if obs.subject_id not in grouped:
                grouped[obs.subject_id] = []
                subjects_received.append(obs.subject_id)
            grouped[obs.subject_id].append(obs)

        kept: list[AppendixCObservation] = []
        diagnostics: list[Diagnostic] = []
        for subject_id in subjects_received:
            validated = validate_subject_rows(
                subject_id, grouped[subject_id], diagnostics
            )
            if validated is None:
                continue
            sequence, by_period = validated
            missing = [
                p for p in range(1, sequence.periods + 1) if p not in by_period
            ]
            if missing:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.MISSING_PERIOD,
                        Severity.ADVISORY,
                        subject_id,
                        "missing measurement at period "
                        + ", ".join(str(p) for p in missing)
                        + "; RETAINED, because Appendix C is an available case "
                        "analysis and PROC MIXED uses all observed data",
                        {"missing_periods": missing},
                    )
                )
            for period in sorted(by_period):
                row = by_period[period]
                kept.append(
                    AppendixCObservation(
                        subject_id=subject_id,
                        sequence=sequence,
                        period=period,
                        treatment=row.treatment,
                        log_value=row.log_value,
                    )
                )

        if not kept:
            raise DataError(
                "No subject survived validation. Diagnostics: "
                + "; ".join(str(d) for d in diagnostics)
            )
        return cls(
            design=design,
            endpoint=endpoint,
            observations=tuple(kept),
            diagnostics=tuple(diagnostics),
            subjects_received=tuple(subjects_received),
        )


# --------------------------------------------------------- the design matrix ---


def _design_matrices(
    rows: tuple[AppendixCObservation, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], int]:
    """X, Z, y and the column names, in reference-cell coding.

    Columns: intercept, sequence indicators (first omitted), period indicators
    (first omitted), and one TEST indicator whose coefficient IS mu_T - mu_R on
    the log scale. That last column is the ESTIMATE statement's contrast, so
    the contrast vector is a unit vector and no further algebra is needed.

    `Z` is the n x 2 treatment indicator, columns ordered (TEST, REFERENCE), so
    G[0,0] is the between-subject variance for TEST throughout.
    """
    sequences = sorted({r.sequence.value for r in rows})
    periods = sorted({r.period for r in rows})

    names = ["(Intercept)"]
    columns: list[np.ndarray] = [np.ones(len(rows))]
    for s in sequences[1:]:
        names.append(f"sequence[{s}]")
        columns.append(np.array([1.0 if r.sequence.value == s else 0.0 for r in rows]))
    for p in periods[1:]:
        names.append(f"period[{p}]")
        columns.append(np.array([1.0 if r.period == p else 0.0 for r in rows]))
    names.append("treatment[T-R]")
    columns.append(
        np.array([1.0 if r.treatment is Treatment.TEST else 0.0 for r in rows])
    )

    x = np.column_stack(columns)
    z = np.column_stack(
        [
            np.array([1.0 if r.treatment is Treatment.TEST else 0.0 for r in rows]),
            np.array(
                [1.0 if r.treatment is Treatment.REFERENCE else 0.0 for r in rows]
            ),
        ]
    )
    y = np.array([r.log_value for r in rows])
    return x, z, y, names, len(columns) - 1


# ------------------------------------------------------------ the REML core ---


def _g_matrix(theta: np.ndarray) -> np.ndarray:
    """G = LL' with L lower triangular. FDA's TYPE=FA0(2), exactly."""
    l11, l21, l22 = theta[0], theta[1], theta[2]
    lower = np.array([[l11, 0.0], [l21, l22]])
    return lower @ lower.T


def _residual_variances(theta: np.ndarray) -> tuple[float, float]:
    """(sigma^2_WT, sigma^2_WR), from log parameters so both stay positive."""
    return float(np.exp(theta[3])), float(np.exp(theta[4]))


@dataclass(frozen=True, slots=True)
class _SubjectBlock:
    x: np.ndarray
    z: np.ndarray
    y: np.ndarray
    is_test: np.ndarray


def _blocks(
    rows: tuple[AppendixCObservation, ...],
    x: np.ndarray,
    z: np.ndarray,
    y: np.ndarray,
) -> list[_SubjectBlock]:
    """Split by subject. V is block diagonal, so every quantity is a sum."""
    index: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        index.setdefault(r.subject_id, []).append(i)
    out = []
    for subject in index:
        idx = np.array(index[subject])
        out.append(
            _SubjectBlock(
                x=x[idx, :],
                z=z[idx, :],
                y=y[idx],
                is_test=z[idx, 0] > 0.5,
            )
        )
    return out


def _reml_pieces(
    theta: np.ndarray, blocks: list[_SubjectBlock], n_fixed: int
) -> tuple[float, np.ndarray, np.ndarray]:
    """Returns (-2 logREML, beta_hat, (X'V^-1X)^-1).

    The profiled REML objective, with beta concentrated out:

        -2 lR = sum log|V_i| + sum r_i' V_i^-1 r_i + log|sum X_i' V_i^-1 X_i|

    Each V_i is small - at most four rows - so it is inverted directly. There
    is no iteration here beyond the outer optimiser.
    """
    g = _g_matrix(theta)
    var_t, var_r = _residual_variances(theta)

    xtvx = np.zeros((n_fixed, n_fixed))
    xtvy = np.zeros(n_fixed)
    log_det_v = 0.0
    quad_pieces = []

    for b in blocks:
        r_diag = np.where(b.is_test, var_t, var_r)
        v = b.z @ g @ b.z.T + np.diag(r_diag)
        sign, logdet = np.linalg.slogdet(v)
        if sign <= 0:
            return math.inf, np.zeros(n_fixed), np.eye(n_fixed)
        log_det_v += logdet
        v_inv = np.linalg.inv(v)
        xtvx += b.x.T @ v_inv @ b.x
        xtvy += b.x.T @ v_inv @ b.y
        quad_pieces.append((b, v_inv))

    sign, log_det_xtvx = np.linalg.slogdet(xtvx)
    if sign <= 0:
        return math.inf, np.zeros(n_fixed), np.eye(n_fixed)

    xtvx_inv = np.linalg.inv(xtvx)
    beta = xtvx_inv @ xtvy

    quad = 0.0
    for b, v_inv in quad_pieces:
        resid = b.y - b.x @ beta
        quad += float(resid @ v_inv @ resid)

    return log_det_v + quad + log_det_xtvx, beta, xtvx_inv


def _dv_dtheta(theta: np.ndarray, block: _SubjectBlock) -> list[np.ndarray]:
    """dV_i/dtheta_k for each of the five parameters, in closed form.

    With G = LL' and L = [[l11, 0], [l21, l22]]:

        dG/dl11 = [[2 l11, l21], [l21,    0  ]]
        dG/dl21 = [[  0,   l11], [l11, 2 l21 ]]
        dG/dl22 = [[  0,    0 ], [ 0,  2 l22 ]]

    and, because the residual variances are carried as logs,

        dR/d(log s2_WT) = s2_WT on test rows, 0 elsewhere
        dR/d(log s2_WR) = s2_WR on reference rows, 0 elsewhere

    Exact derivatives rather than differences. They matter: the first attempt
    took the Hessian by second differences of the objective, which divides by
    h^2 and loses most of its significant figures, and the denominator df came
    out 0.17% from the oracle for that reason alone.
    """
    l11, l21, l22 = theta[0], theta[1], theta[2]
    var_t, var_r = _residual_variances(theta)
    z = block.z

    dg = [
        np.array([[2.0 * l11, l21], [l21, 0.0]]),
        np.array([[0.0, l11], [l11, 2.0 * l21]]),
        np.array([[0.0, 0.0], [0.0, 2.0 * l22]]),
    ]
    out = [z @ d @ z.T for d in dg]
    out.append(np.diag(np.where(block.is_test, var_t, 0.0)))
    out.append(np.diag(np.where(block.is_test, 0.0, var_r)))
    return out


def _reml_gradient(
    theta: np.ndarray, blocks: list[_SubjectBlock], n_fixed: int
) -> np.ndarray:
    """d(-2 logREML)/dtheta, in closed form.

        d(-2 lR)/dtheta_k = tr(P dV/dtheta_k) - y' P dV/dtheta_k P y

    with P = V^-1 - V^-1 X C X' V^-1 and C = (X'V^-1X)^-1. Because dV/dtheta is
    block diagonal, only P's diagonal blocks enter the trace, and P y has i-th
    block V_i^-1 (y_i - X_i beta). Both terms are therefore per-subject sums.
    """
    g = _g_matrix(theta)
    var_t, var_r = _residual_variances(theta)

    xtvx = np.zeros((n_fixed, n_fixed))
    xtvy = np.zeros(n_fixed)
    cached = []
    for b in blocks:
        r_diag = np.where(b.is_test, var_t, var_r)
        v = b.z @ g @ b.z.T + np.diag(r_diag)
        v_inv = np.linalg.inv(v)
        xtvx += b.x.T @ v_inv @ b.x
        xtvy += b.x.T @ v_inv @ b.y
        cached.append((b, v_inv))

    c = np.linalg.inv(xtvx)
    beta = c @ xtvy

    gradient = np.zeros(len(theta))
    for b, v_inv in cached:
        # P's diagonal block for this subject.
        p_ii = v_inv - v_inv @ b.x @ c @ b.x.T @ v_inv
        u = v_inv @ (b.y - b.x @ beta)
        for k, dv in enumerate(_dv_dtheta(theta, b)):
            gradient[k] += float(np.trace(p_ii @ dv)) - float(u @ dv @ u)
    return gradient


def _contrast_variance_gradient(
    theta: np.ndarray,
    blocks: list[_SubjectBlock],
    n_fixed: int,
    contrast: np.ndarray,
) -> tuple[float, np.ndarray]:
    """(L C L', d(L C L')/dtheta), in closed form.

        dC/dtheta_k = C (X' V^-1 (dV/dtheta_k) V^-1 X) C

    so the derivative of the contrast variance is
    L C X'V^-1 (dV/dtheta_k) V^-1 X C L'.
    """
    g = _g_matrix(theta)
    var_t, var_r = _residual_variances(theta)

    xtvx = np.zeros((n_fixed, n_fixed))
    cached = []
    for b in blocks:
        r_diag = np.where(b.is_test, var_t, var_r)
        v = b.z @ g @ b.z.T + np.diag(r_diag)
        v_inv = np.linalg.inv(v)
        xtvx += b.x.T @ v_inv @ b.x
        cached.append((b, v_inv))

    c = np.linalg.inv(xtvx)
    lc = contrast @ c  # row vector L C

    gradient = np.zeros(len(theta))
    for b, v_inv in cached:
        w = v_inv @ b.x @ lc  # V^-1 X C L'
        for k, dv in enumerate(_dv_dtheta(theta, b)):
            gradient[k] += float(w @ dv @ w)
    return float(contrast @ c @ contrast), gradient


def _starting_values(
    rows: tuple[AppendixCObservation, ...],
) -> np.ndarray:
    """Deterministic method-of-moments start. No randomness, no search.

    Within-subject variance per treatment from replicated measurements;
    between-subject variance per treatment from subject means; covariance from
    the subject means of the two treatments over subjects having both.
    """
    per_subject: dict[str, dict[Treatment, list[float]]] = {}
    for r in rows:
        per_subject.setdefault(r.subject_id, {}).setdefault(r.treatment, []).append(
            r.log_value
        )

    within: dict[Treatment, list[float]] = {Treatment.TEST: [], Treatment.REFERENCE: []}
    means: dict[Treatment, dict[str, float]] = {
        Treatment.TEST: {},
        Treatment.REFERENCE: {},
    }
    for subject, by_trt in per_subject.items():
        for treatment, values in by_trt.items():
            means[treatment][subject] = float(np.mean(values))
            if len(values) >= 2:
                within[treatment].append(float(np.var(values, ddof=1)))

    def _mean_or(values: list[float], fallback: float) -> float:
        return float(np.mean(values)) if values else fallback

    overall = float(np.var([r.log_value for r in rows], ddof=1))
    var_t = max(_mean_or(within[Treatment.TEST], overall / 2.0), 1e-8)
    var_r = max(_mean_or(within[Treatment.REFERENCE], overall / 2.0), 1e-8)

    shared = sorted(set(means[Treatment.TEST]) & set(means[Treatment.REFERENCE]))
    if len(shared) >= 3:
        mt = np.array([means[Treatment.TEST][s] for s in shared])
        mr = np.array([means[Treatment.REFERENCE][s] for s in shared])
        cov = np.cov(np.vstack([mt, mr]), ddof=1)
        between_t = max(float(cov[0, 0]) - var_t / 2.0, 1e-6)
        between_r = max(float(cov[1, 1]) - var_r / 2.0, 1e-6)
        between_tr = float(cov[0, 1])
    else:
        between_t = between_r = max(overall / 4.0, 1e-6)
        between_tr = 0.0

    # Cholesky of the moment estimate, floored so l22 starts strictly positive
    # and the optimiser can move to zero rather than starting on top of it.
    l11 = math.sqrt(between_t)
    l21 = between_tr / l11 if l11 > 0 else 0.0
    l22 = math.sqrt(max(between_r - l21 * l21, 0.25 * between_r))
    return np.array([l11, l21, l22, math.log(var_t), math.log(var_r)])


@dataclass(frozen=True, slots=True)
class ReplicateAbeFit:
    """A fitted Appendix C model, with everything the decision needs."""

    #: theta = (l11, l21, l22, log sigma^2_WT, log sigma^2_WR)
    theta: tuple[float, ...]
    reml2: float
    converged: bool
    optimiser: str
    n_iterations: int
    fallback_used: bool

    beta: tuple[float, ...]
    coefficient_names: tuple[str, ...]
    contrast_index: int

    estimate: float
    standard_error: float
    degrees_of_freedom: float

    between_subject_variance_test: float
    between_subject_variance_reference: float
    between_subject_covariance: float
    within_subject_variance_test: float
    within_subject_variance_reference: float

    n_observations: int
    n_subjects: int

    @property
    def subject_by_formulation_variance(self) -> float:
        """sigma^2_D = sigma^2_BT + sigma^2_BR - 2 sigma_BTBR.

        A FUNCTION of three of the five parameters, never a sixth parameter.
        """
        return (
            self.between_subject_variance_test
            + self.between_subject_variance_reference
            - 2.0 * self.between_subject_covariance
        )

    @property
    def subject_correlation(self) -> float:
        denominator = math.sqrt(
            self.between_subject_variance_test
            * self.between_subject_variance_reference
        )
        if denominator <= 0.0:
            return float("nan")
        return self.between_subject_covariance / denominator

    @property
    def on_correlation_boundary(self) -> bool:
        """|rho| within 1e-6 of 1. Expected on real data, not an error."""
        rho = self.subject_correlation
        return bool(np.isfinite(rho)) and abs(abs(rho) - 1.0) < 1e-6

    def cv_within_percent(self, treatment: Treatment) -> float:
        variance = (
            self.within_subject_variance_test
            if treatment is Treatment.TEST
            else self.within_subject_variance_reference
        )
        return 100.0 * math.sqrt(math.expm1(variance))


def fit_appendix_c(dataset: AppendixCDataset) -> ReplicateAbeFit:
    """Fit the Appendix C model by REML.

    OPTIMISATION, STATED SO IT CAN BE CHECKED

        objective      profiled -2 logREML, beta concentrated out
        parameters     (l11, l21, l22, log s2_WT, log s2_WR), unconstrained
        start          deterministic method of moments (`_starting_values`)
        optimiser      Nelder-Mead, then BFGS from its result
        convergence    xatol/fatol 1e-10 then gtol 1e-8
        bounds         none - the parameterisation makes them unnecessary

    TWO OPTIMISERS, AND WHY THAT IS NOT "TRY UNTIL IT AGREES"

    They run in a FIXED ORDER, ALWAYS, on every dataset. Nelder-Mead is
    derivative-free and copes with the flat ridge near `l22 = 0`, where the
    objective is even in `l22` and its gradient vanishes; BFGS then polishes.
    Neither is selected by looking at the answer, and the result does not
    depend on which one "worked". `fallback_used` records the case where BFGS
    fails to improve on Nelder-Mead, so a reader can see it happened.
    """
    if dataset.design not in SUPPORTED_DESIGNS:
        raise AppendixCNotSupported(
            f"Appendix C is implemented for {sorted(d.value for d in SUPPORTED_DESIGNS)} "
            f"only; this dataset is {dataset.design.value}."
        )

    rows = dataset.observations
    x, z, y, names, contrast_index = _design_matrices(rows)
    blocks = _blocks(rows, x, z, y)
    n_fixed = x.shape[1]

    def objective(theta: np.ndarray) -> float:
        value, _, _ = _reml_pieces(np.asarray(theta, dtype=float), blocks, n_fixed)
        return value

    start = _starting_values(rows)

    simplex = optimize.minimize(
        objective,
        start,
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-10, "maxiter": 20000, "maxfev": 20000},
    )
    polished = optimize.minimize(
        objective, simplex.x, method="BFGS", options={"gtol": 1e-8, "maxiter": 5000}
    )

    if polished.fun <= simplex.fun:
        theta = np.asarray(polished.x, dtype=float)
        reml2 = float(polished.fun)
        optimiser = "Nelder-Mead then BFGS"
        fallback = False
        converged = bool(polished.success or simplex.success)
        iterations = int(simplex.nit) + int(polished.nit)
    else:
        theta = np.asarray(simplex.x, dtype=float)
        reml2 = float(simplex.fun)
        optimiser = "Nelder-Mead (BFGS did not improve)"
        fallback = True
        converged = bool(simplex.success)
        iterations = int(simplex.nit)

    _, beta, xtvx_inv = _reml_pieces(theta, blocks, n_fixed)

    contrast = np.zeros(n_fixed)
    contrast[contrast_index] = 1.0
    variance = float(contrast @ xtvx_inv @ contrast)
    if variance <= 0.0:
        raise DataError(
            "The variance of the T-R contrast came out non-positive, which "
            "means the model is numerically singular for it. Refusing rather "
            "than reporting the square root of a negative number."
        )

    df = satterthwaite_df(theta, blocks, n_fixed, contrast)

    g = _g_matrix(theta)
    var_t, var_r = _residual_variances(theta)

    return ReplicateAbeFit(
        theta=tuple(float(v) for v in theta),
        reml2=reml2,
        converged=converged,
        optimiser=optimiser,
        n_iterations=iterations,
        fallback_used=fallback,
        beta=tuple(float(v) for v in beta),
        coefficient_names=tuple(names),
        contrast_index=contrast_index,
        estimate=float(beta[contrast_index]),
        standard_error=math.sqrt(variance),
        degrees_of_freedom=df,
        between_subject_variance_test=float(g[0, 0]),
        between_subject_variance_reference=float(g[1, 1]),
        between_subject_covariance=float(g[0, 1]),
        within_subject_variance_test=var_t,
        within_subject_variance_reference=var_r,
        n_observations=len(rows),
        n_subjects=len(dataset.subjects),
    )


# ---------------------------------------------------------- Satterthwaite ---


def satterthwaite_df(
    theta: np.ndarray,
    blocks: list[_SubjectBlock],
    n_fixed: int,
    contrast: np.ndarray,
) -> float:
    """Satterthwaite denominator df for `contrast' beta`.

    THE FORMULA, AND WHERE EACH PIECE COMES FROM

        df = 2 (L C L')^2 / (g' A g)

    with `C = (X'V^-1 X)^-1`, `g = d(L C L')/d theta`, and `A` the asymptotic
    covariance of theta-hat. SAS documents that as `2 H^-1` where `H` is the
    Hessian of the -2 log likelihood, so

        g' A g = 2 g' H^-1 g     and     df = (L C L')^2 / (g' H^-1 g)

    Both derivatives are taken numerically by central differences on the same
    objective the optimiser minimised, so the two are guaranteed consistent.

    INVARIANT TO THE PARAMETERISATION, WHICH IS WORTH KNOWING

    Under theta = h(phi): g_phi = (dh/dphi)' g_theta and
    A_phi = (dh/dphi)^-1 A_theta (dh/dphi)^-T, so `g' A g` is unchanged. The df
    is therefore the same whether the covariance is carried in FDA's FA0(2)
    coordinates or ReplicateBE.jl's CSH ones - which is why the two can be
    compared at all, and `test_appendix_c.py` asserts it rather than assuming.

    THE BOUNDARY

    On EMA Data set I the optimum sits at `l22 = 0`, i.e. correlation exactly
    1. Asymptotics for a covariance parameter on the boundary of the PSD cone
    are non-standard and the df inherits that. SAS reports one anyway, and so
    does ReplicateBE.jl; this reproduces theirs. It is recorded as a known
    limitation rather than smoothed over.
    """
    theta = np.asarray(theta, dtype=float)

    lcl, gradient = _contrast_variance_gradient(theta, blocks, n_fixed, contrast)

    # The Hessian by CENTRAL DIFFERENCES OF THE ANALYTIC GRADIENT, not by
    # second differences of the objective.
    #
    # The difference is not cosmetic. Second differences divide by h^2 and lose
    # roughly two thirds of the available significant figures; the first
    # version of this function did that and the denominator df came out 0.17%
    # from the oracle for no other reason. Differencing an exact gradient
    # divides by h once, on a quantity that carries full precision.
    steps = np.maximum(np.abs(theta) * 1e-5, 1e-7)
    hessian = np.zeros((len(theta), len(theta)))
    for i in range(len(theta)):
        step = np.zeros(len(theta))
        step[i] = steps[i]
        forward = _reml_gradient(theta + step, blocks, n_fixed)
        backward = _reml_gradient(theta - step, blocks, n_fixed)
        hessian[:, i] = (forward - backward) / (2.0 * steps[i])
    # Symmetrised: the two off-diagonal estimates differ only by rounding, and
    # averaging them is the standard way to use both.
    hessian = 0.5 * (hessian + hessian.T)

    # A pseudo-inverse rather than an inverse: at the boundary the Hessian can
    # be singular in the `l22` direction, and refusing to report a df there
    # would refuse exactly the dataset that validates this module. `pinv`
    # drops the null space, which is the same thing SAS's generalised inverse
    # does with a non-estimable direction.
    denominator = float(gradient @ np.linalg.pinv(hessian) @ gradient)
    if denominator <= 0.0:
        raise DataError(
            "The Satterthwaite denominator came out non-positive, so no "
            "degrees of freedom can be formed. This means the fitted "
            "covariance is degenerate for this contrast."
        )
    return float(lcl * lcl / denominator)


# --------------------------------------------------------------- decision ---


@dataclass(frozen=True, slots=True)
class ReplicateAbeResult:
    """The Appendix C decision for one endpoint, or an explicit refusal."""

    endpoint: str
    design: ReplicateDesign
    design_supported: bool

    estimate: float | None
    standard_error: float | None
    degrees_of_freedom: float | None
    ci_lower_log: float | None
    ci_upper_log: float | None
    geometric_mean_ratio_percent: float | None
    ci_lower_percent: float | None
    ci_upper_percent: float | None

    decided: bool
    passes: bool | None

    fit: ReplicateAbeFit | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    provenance_lines: tuple[str, ...] = ()
    validation_status: ValidationStatus = ValidationStatus.IMPLEMENTED_UNVALIDATED
    notes: tuple[str, ...] = field(default_factory=tuple)

    def provenance(self) -> list[str]:
        return list(self.provenance_lines)


def _refusal(
    dataset: AppendixCDataset, reason: str
) -> ReplicateAbeResult:
    diagnostic = Diagnostic(
        DiagnosticCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED,
        Severity.FATAL,
        None,
        reason,
        {
            "design": dataset.design.value,
            "supported_designs": sorted(d.value for d in SUPPORTED_DESIGNS),
        },
    )
    return ReplicateAbeResult(
        endpoint=dataset.endpoint,
        design=dataset.design,
        design_supported=False,
        estimate=None,
        standard_error=None,
        degrees_of_freedom=None,
        ci_lower_log=None,
        ci_upper_log=None,
        geometric_mean_ratio_percent=None,
        ci_lower_percent=None,
        ci_upper_percent=None,
        decided=False,
        passes=None,
        diagnostics=(*dataset.diagnostics, diagnostic),
        provenance_lines=(reason,),
        validation_status=ValidationStatus.NOT_IMPLEMENTED,
    )


PARTIAL_REPLICATE_REFUSAL = (
    "FDA Appendix C is implemented for the fully replicate design only. The "
    "partial replicate design is REFUSED because no trustworthy numerical "
    "oracle exists for it: PR #61 found that ReplicateBE.jl reproduces EMA's "
    "published SAS Method C output exactly on the fully replicate data set - "
    "estimate, 90% interval and both within-subject CVs - and differs by 2.94 "
    "denominator degrees of freedom on the partial replicate one, a design its "
    "own validation claim never covered. The arithmetic here would produce a "
    "number; there is nothing to check it against, and the correct partial "
    "replicate Satterthwaite df remains NOT DETERMINED. See "
    "validation/findings/VAL-FDA-APPENDIX-C-002.md."
)


def analyse_replicate_abe_full(
    observations: list[ReplicateObservation],
) -> ReplicateAbeResult:
    """Appendix C for one endpoint. Fits a fully replicate design, refuses others.

        validated replicate dataset (available case)
                -> is the design fully replicate?
              no /                        \\ yes
        REFUSE, decided = False      fit Appendix C by REML
                                     Satterthwaite df
                                     90% CI on the log scale
                                     contained in 80.00-125.00%?
    """
    dataset = AppendixCDataset.build(observations)
    if dataset.design not in SUPPORTED_DESIGNS:
        return _refusal(dataset, PARTIAL_REPLICATE_REFUSAL)

    fit = fit_appendix_c(dataset)
    half_width = float(stats.t.ppf(1.0 - ALPHA, fit.degrees_of_freedom)) * (
        fit.standard_error
    )
    lower_log = fit.estimate - half_width
    upper_log = fit.estimate + half_width
    lower_percent = 100.0 * math.exp(lower_log)
    upper_percent = 100.0 * math.exp(upper_log)

    # Inclusive at both ends: a confidence interval touching the limit is
    # contained by it.
    passes = (
        lower_percent >= LOWER_LIMIT_PERCENT
        and upper_percent <= UPPER_LIMIT_PERCENT
    )

    provenance = [
        f"FDA {APPENDIX_C_MODEL.citation.section} "
        f"({APPENDIX_C_MODEL.citation.document_version}) "
        f"[verified, via {VIA_PRIMARY_DOCUMENT}]",
        *APPENDIX_C_MODEL.explain(),
        f"fitted by REML, parameterised as G = LL' (FDA TYPE=FA0(2)); "
        f"optimiser {fit.optimiser}",
        f"denominator df {fit.degrees_of_freedom:.4f} (Satterthwaite)",
        f"acceptance range {LOWER_LIMIT_PERCENT:.2f}-{UPPER_LIMIT_PERCENT:.2f}%, "
        "inclusive",
    ]
    if fit.on_correlation_boundary:
        provenance.append(
            "the fitted subject-by-formulation correlation is on the boundary "
            "(|rho| = 1); asymptotics for a covariance parameter there are "
            "non-standard and the denominator df inherits that"
        )

    return ReplicateAbeResult(
        endpoint=dataset.endpoint,
        design=dataset.design,
        design_supported=True,
        estimate=fit.estimate,
        standard_error=fit.standard_error,
        degrees_of_freedom=fit.degrees_of_freedom,
        ci_lower_log=lower_log,
        ci_upper_log=upper_log,
        geometric_mean_ratio_percent=100.0 * math.exp(fit.estimate),
        ci_lower_percent=lower_percent,
        ci_upper_percent=upper_percent,
        decided=True,
        passes=passes,
        fit=fit,
        diagnostics=dataset.diagnostics,
        provenance_lines=tuple(provenance),
    )


__all__ = [
    "ALPHA",
    "LOWER_LIMIT_PERCENT",
    "SUPPORTED_DESIGNS",
    "UPPER_LIMIT_PERCENT",
    "AppendixCDataset",
    "AppendixCNotSupported",
    "AppendixCObservation",
    "ReplicateAbeFit",
    "ReplicateAbeResult",
    "analyse_replicate_abe_full",
    "fit_appendix_c",
    "satterthwaite_df",
]
