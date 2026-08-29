"""Least squares for a fixed-effects crossover model.

WHY THIS IS HERE AND WHAT IT IS NOT

EMA specifies its bioequivalence analysis as an ANOVA with every term fixed —
`proc glm; model logDATA = sequence subject(sequence) period formulation` — and
this module is the arithmetic that fits it. It is ordinary least squares on a
design matrix and nothing more: no random effects, no variance components, no
REML, no iteration, no convergence to fail.

That last point is the reason EMA's model can be implemented faithfully where
FDA's Appendix C cannot. Appendix C asks for `PROC MIXED` with
`RANDOM TRT/TYPE=FA0(2)` and `REPEATED/GRP=TRT`: five covariance parameters
fitted by restricted maximum likelihood. `be_stats.replicate_abe` records that
model and refuses to approximate it. Method A is a different kind of object —
a closed-form projection — and reproducing it exactly needs only a matrix
decomposition.

THIS MODULE IS REGULATOR-NEUTRAL, DELIBERATELY

It knows about design matrices and contrasts. It does not know what a
bioequivalence limit is, which endpoint may be scaled, or what any regulator
requires. Those live in the regulator-specific modules, because two regulators
that happen to share a matrix decomposition do not thereby share a method. This
is the "very low-level mathematical helper" exception to keeping FDA and EMA
apart, and it is meant to stay low-level.

RANK DEFICIENCY IS EXPECTED, NOT AN ERROR

`sequence` is aliased with `subject(sequence)`: every subject belongs to
exactly one sequence, so the subject indicators already span the sequence
space. SAS absorbs the redundancy and reports the estimable contrast anyway.
Here the design is built full-rank from the start by reference-cell coding,
which fits the same model and makes the aliasing a fact about the construction
rather than something to detect at run time. The rank is still measured and
reported, because degrees of freedom must come from what was actually fitted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True, slots=True)
class LeastSquaresFit:
    """A fitted linear model, with everything a contrast needs."""

    #: Estimated coefficients, in the column order the design was built in.
    coefficients: tuple[float, ...]
    #: Residual mean square. For a reference-only fit this IS the within
    #: -subject variance of the reference product.
    mean_square_error: float
    #: n_observations - rank. Not n - n_columns: a rank-deficient column
    #: contributes no fitted parameter and must not cost a degree of freedom.
    degrees_of_freedom: int
    rank: int
    n_observations: int
    #: Pseudo-inverse of X'X, for the variance of a contrast.
    _xtx_inverse: tuple[tuple[float, ...], ...]

    @property
    def residual_standard_deviation(self) -> float:
        return math.sqrt(self.mean_square_error)

    def contrast(self, weights: list[float]) -> tuple[float, float]:
        """Estimate and standard error of `weights' @ coefficients`.

        Var(c'b) = sigma^2 * c' (X'X)^- c, with the same generalized inverse
        used to fit.
        """
        if len(weights) != len(self.coefficients):
            raise ValueError(
                f"contrast has {len(weights)} weights but the model has "
                f"{len(self.coefficients)} coefficients"
            )
        c = np.asarray(weights, dtype=float)
        xtx_inv = np.asarray(self._xtx_inverse, dtype=float)
        estimate = float(c @ np.asarray(self.coefficients, dtype=float))
        variance = self.mean_square_error * float(c @ xtx_inv @ c)
        if variance < 0.0:
            # Only reachable through floating-point noise on a near-singular
            # design; a negative variance is not a small number, it is a
            # broken one.
            raise ValueError(
                "the variance of this contrast came out negative, which means "
                "the design matrix is numerically singular for it. Refusing "
                "rather than reporting sqrt of a negative number."
            )
        return estimate, math.sqrt(variance)

    def confidence_interval(
        self, weights: list[float], *, alpha: float
    ) -> tuple[float, float, float, float]:
        """Two-sided (1 - 2*alpha) interval for a contrast.

        `alpha` is the ONE-SIDED level, matching how bioequivalence states it:
        alpha = 0.05 gives the 90% interval that both EMA and FDA ask for.
        Returns (estimate, standard error, lower, upper).
        """
        estimate, se = self.contrast(weights)
        if self.degrees_of_freedom < 1:
            raise ValueError(
                f"{self.degrees_of_freedom} residual degrees of freedom cannot "
                "support a confidence interval"
            )
        half_width = float(stats.t.ppf(1.0 - alpha, self.degrees_of_freedom)) * se
        return estimate, se, estimate - half_width, estimate + half_width


def fit_least_squares(
    design: list[list[float]], response: list[float]
) -> LeastSquaresFit:
    """Fit `response ~ design` by least squares.

    `numpy.linalg.lstsq` gives the minimum-norm solution and the rank, which is
    what a possibly rank-deficient ANOVA design needs. The residual sum of
    squares is recomputed from the fitted values rather than taken from lstsq's
    third return value, which is empty exactly when the design is rank
    deficient — that is, precisely when it would be needed.
    """
    x = np.asarray(design, dtype=float)
    y = np.asarray(response, dtype=float)
    if x.ndim != 2:
        raise ValueError(f"design must be 2-dimensional, got shape {x.shape}")
    if x.shape[0] != y.shape[0]:
        raise ValueError(
            f"{x.shape[0]} design rows against {y.shape[0]} responses"
        )

    coefficients, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    residuals = y - x @ coefficients
    df = int(x.shape[0] - rank)
    if df < 1:
        raise ValueError(
            f"{x.shape[0]} observations and rank {rank} leave {df} residual "
            "degrees of freedom, so no variance can be estimated. The model "
            "has as many parameters as data."
        )
    mse = float(residuals @ residuals) / df

    return LeastSquaresFit(
        coefficients=tuple(float(v) for v in coefficients),
        mean_square_error=mse,
        degrees_of_freedom=df,
        rank=int(rank),
        n_observations=int(x.shape[0]),
        _xtx_inverse=tuple(
            tuple(float(v) for v in row) for row in np.linalg.pinv(x.T @ x)
        ),
    )
