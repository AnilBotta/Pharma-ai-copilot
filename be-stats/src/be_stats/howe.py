"""Howe's Approximation I, shared by two regulatory procedures that use it.

WHY THIS IS SHARED, AND THE EVIDENCE FOR SHARING IT

FDA's highly-variable and narrow-therapeutic-index procedures both form a 95%
upper confidence bound for `(mu_T - mu_R)^2 - theta*sigma_WR^2`, and the
guidance gives each its own SAS. Sharing an implementation on the strength of
"they look similar" would be exactly the substitution this package refuses
elsewhere, so the two were compared line by line first. They are identical:

    Appendix F (NTI)                        Appendix G (HVD, fully replicate)
    ------------------------------------    ---------------------------------
    x=estimate**2-stderr**2                 x=estimate**2-stderr**2
    boundx=(max((abs(lower)),              boundx=(max((abs(lower)),
            (abs(upper))))**2                      (abs(upper))))**2
    theta=((log(1.11111))/0.1)**2           theta=((log(1.25))/0.25)**2
    y=-theta*s2wr                           y=-theta*s2wr
    boundy=y*dfd/cinv(0.95,dfd)             boundy=y*dfd/cinv(0.95,dfd)
    sWR=sqrt(s2wr)                          sWR=sqrt(s2wr)
    critbound=(x+y)+sqrt(((boundx-x)**2)    critbound=(x+y)+sqrt(((boundx-x)**2)
              +((boundy-y)**2))                       +((boundy-y)**2))

Every line matches but `theta`, which each procedure supplies from its own
constants. So this module takes `theta` as an argument and knows nothing about
which drug class it is serving.

WHAT IT DELIBERATELY DOES NOT DO

It does not choose theta, it does not know sigma_w0, and it does not decide
anything. The two wrappers - `hvd.scaled_criterion` and
`nti.scaled_mean_criterion` - each supply their own verified constants and each
cite their own appendix. There is no `mode="nti"` flag, because a flag is how
two procedures come to share a bug.

THE CHI-SQUARE DIRECTION

`cinv(0.95, dfd)` is SAS's INVERSE CDF - the 95th percentile - which is
`scipy.stats.chi2.ppf(0.95, df)`, not `chi2.isf(0.95, df)`. The mistake keeps
the sign and the ordering and is worth roughly a factor of three at 20 degrees
of freedom. `bound_y` must come out CLOSER TO ZERO than `y`, which makes it a
lower bound on the reference variance: less scaling, a harder criterion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

#: Appendix F step 2 and Appendix G step 2 both ask for a 95% upper bound.
UPPER_BOUND_CONFIDENCE = 0.95


@dataclass(frozen=True, slots=True)
class HoweUpperBound:
    """The four intermediates and the bound, kept separate on purpose.

    Each of `x`, `bound_x`, `y` and `bound_y` has a plausible-looking wrong
    version that raises nothing and moves the answer only for studies near the
    boundary - which are the studies that matter. A result carrying only the
    final number would force a reviewer to re-derive the chain to locate a
    disagreement.
    """

    x: float
    bound_x: float
    y: float
    bound_y: float
    theta: float
    reference_variance: float
    reference_variance_df: int
    upper_confidence_bound: float

    def explain(self, *, theta_basis: str = "") -> list[str]:
        basis = f" ({theta_basis})" if theta_basis else ""
        return [
            f"x = estimate^2 - SE^2 = {self.x:.8f}",
            f"bound_x = max(|CI|)^2 = {self.bound_x:.8f}",
            f"theta{basis} = {self.theta:.8f}",
            f"y = -theta * sWR^2 = {self.y:.8f}",
            f"bound_y = y * {self.reference_variance_df} / "
            f"chisq_0.95({self.reference_variance_df}) = {self.bound_y:.8f}",
            f"critbound = (x+y) + sqrt((bound_x-x)^2 + (bound_y-y)^2) = "
            f"{self.upper_confidence_bound:.8f}",
        ]


def howe_upper_bound(
    *,
    estimate: float,
    standard_error: float,
    ci_lower: float,
    ci_upper: float,
    reference_variance: float,
    reference_variance_df: int,
    theta: float,
) -> HoweUpperBound:
    """The 95% upper bound for `(mu_T - mu_R)^2 - theta*sigma_WR^2`.

    `estimate`, `standard_error`, `ci_lower` and `ci_upper` come from the
    treatment-contrast model, on the LOG scale, at alpha = 0.1.
    `reference_variance` and its degrees of freedom come from the reference
    variance model - a DIFFERENT model, fitted on a possibly different subject
    set, which is why the two arrive as separate arguments rather than as one
    bundle.
    """
    if reference_variance < 0.0:
        raise ValueError(
            f"A variance cannot be negative, got {reference_variance}."
        )
    if reference_variance_df < 1:
        raise ValueError(
            f"{reference_variance_df} degrees of freedom cannot support a "
            "chi-square bound."
        )

    x = estimate**2 - standard_error**2
    bound_x = max(abs(ci_lower), abs(ci_upper)) ** 2
    y = -theta * reference_variance
    bound_y = (
        y
        * reference_variance_df
        / stats.chi2.ppf(UPPER_BOUND_CONFIDENCE, reference_variance_df)
    )
    critbound = (x + y) + math.sqrt((bound_x - x) ** 2 + (bound_y - y) ** 2)

    return HoweUpperBound(
        x=x,
        bound_x=bound_x,
        y=y,
        bound_y=bound_y,
        theta=theta,
        reference_variance=reference_variance,
        reference_variance_df=reference_variance_df,
        upper_confidence_bound=critbound,
    )
