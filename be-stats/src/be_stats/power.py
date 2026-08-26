"""Power and sample size for average bioequivalence.

THE METHOD IS NAMED, NOT IMPLIED

Power for TOST has no elementary closed form. Three approaches are in common
use, and they do not agree to the last subject: the exact method via Owen's Q,
the non-central t approximation, and a shifted-normal approximation.

This module implements the **non-central t approximation** and says so on every
result. Two tools disagreeing by one subject are usually two different methods
rather than one bug, and a sample size that cannot be traced to a named method
cannot be defended. Exact Owen's Q is a deliberate follow-up.

A MATHEMATICAL ANSWER IS NOT A REGULATORY ONE

At a 10% coefficient of variation the arithmetic asks for eight subjects. FDA
will not accept a PK bioequivalence study with fewer than twelve evaluable
subjects, or fewer than twenty-four for a highly variable drug product. Those
are different kinds of statement and the engine keeps them apart:

    mathematical_n   what the power calculation requires
    regulatory_n     what the regulator requires regardless
    recommended_n    max of the two

Collapsing them would hide which constraint is binding, and it is usually the
one nobody planned for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

from be_stats.conversions import cv_percent_to_log_variance
from be_stats.minimums import (
    Framework,
    RegulatoryMinimum,
    design_family_for,
    lookup,
)
from be_stats.spec import BeSpec, DrugClass

METHOD = "non-central t approximation"

_MAX_N = 10_000


class NotPowerable(Exception):
    """No sample size can reach the target, and more subjects will not help.

    Raised for an assumed true ratio at or beyond an acceptance limit. As n
    grows the interval shrinks toward the true ratio, so a ratio sitting on the
    boundary cannot be brought inside it; power approaches alpha rather than
    one. Iterating to a cap and reporting "maximum iterations reached" would
    describe the search instead of the problem.
    """


@dataclass(frozen=True, slots=True)
class PowerResult:
    power: float
    method: str = METHOD


@dataclass(frozen=True, slots=True)
class SampleSizeResult:
    """What the arithmetic asks for, what the regulator asks for, and the answer."""

    #: The smallest even total reaching the target power.
    mathematical_n: int
    #: The regulator's floor, independent of power. `None` where this package
    #: has not confirmed one for this jurisdiction AND design.
    regulatory_n: int | None
    #: The rule that produced it, or None. Carried whole rather than as a
    #: string so a report can show the citation.
    regulatory_rule: RegulatoryMinimum | None
    #: What to actually run.
    recommended_n: int

    achieved_power: float
    #: Power at `recommended_n`, which exceeds `achieved_power` whenever the
    #: regulatory floor is the binding constraint.
    power_at_recommended: float

    target_power: float
    design: str
    binding_constraint: str
    regulatory_basis: str
    method: str = METHOD

    @property
    def n_per_group(self) -> int:
        """Per sequence for a crossover, per group for a parallel design."""
        return self.recommended_n // 2

    def summary(self) -> str:
        return (
            f"{self.recommended_n} subjects ({self.binding_constraint} is "
            f"binding): power {self.power_at_recommended:.3f} at the assumed "
            f"ratio, target {self.target_power:.0%}. Arithmetic alone asks for "
            f"{self.mathematical_n}"
            + (
                f"; {self.regulatory_basis}."
                if self.regulatory_n is not None
                else "; no regulatory floor applied."
            )
        )


def _standard_error(design: str, cv_percent: float, n_total: int) -> float:
    sigma = math.sqrt(cv_percent_to_log_variance(cv_percent))
    if design == "2x2":
        return sigma * math.sqrt(2.0 / n_total)
    if design == "parallel":
        return sigma * math.sqrt(4.0 / n_total)
    raise ValueError(f"Unknown design: {design!r}. Expected '2x2' or 'parallel'.")


def _degrees_of_freedom(design: str, n_total: int) -> int:
    if design in ("2x2", "parallel"):
        return n_total - 2
    raise ValueError(f"Unknown design: {design!r}.")


def power_abe(
    *,
    cv_percent: float,
    n_total: int,
    spec: BeSpec,
    design: str = "2x2",
    expected_ratio: float = 0.95,
) -> PowerResult:
    """Power of the TOST procedure at a given sample size.

    `expected_ratio` defaults to 0.95 rather than 1.0 deliberately: planning at
    exact equality assumes the formulations are identical, which is the one
    assumption a bioequivalence study exists to question, and it produces
    sample sizes that are too small whenever it is untrue.
    """
    acceptance = spec.require_interval()
    if expected_ratio <= 0.0:
        raise ValueError("expected_ratio must be positive.")
    if cv_percent <= 0.0:
        raise ValueError("cv_percent must be positive.")

    theta_lower = math.log(acceptance.lower_value / 100.0)
    theta_upper = math.log(acceptance.upper_value / 100.0)
    theta = math.log(expected_ratio)

    df = _degrees_of_freedom(design, n_total)
    if df < 1:
        return PowerResult(power=0.0)

    se = _standard_error(design, cv_percent, n_total)
    t_crit = stats.t.ppf(1.0 - spec.alpha, df)

    power = float(
        stats.nct.cdf(-t_crit, df, (theta - theta_upper) / se)
        - stats.nct.cdf(t_crit, df, (theta - theta_lower) / se)
    )
    return PowerResult(power=max(0.0, min(1.0, power)))


def sample_size_abe(
    *,
    cv_percent: float,
    spec: BeSpec,
    design: str = "2x2",
    target_power: float = 0.80,
    expected_ratio: float = 0.95,
    framework: Framework | None = None,
) -> SampleSizeResult:
    """The sample size to run: the larger of the arithmetic and the regulation.

    `framework` names the body of guidance the study is run under. Left unset,
    only the region's general guidance is consulted - ICH M13A's rules are
    scoped to immediate-release solid oral dosage forms, which this package
    cannot infer, so a caller running one must say so to be held to them.
    """
    acceptance = spec.require_interval()
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must be between 0 and 1.")

    ratio_percent = expected_ratio * 100.0
    if ratio_percent <= acceptance.lower_value or ratio_percent >= acceptance.upper_value:
        raise NotPowerable(
            f"The assumed true ratio {ratio_percent:.2f}% is at or beyond the "
            f"acceptance interval {acceptance.lower_value:.2f}-"
            f"{acceptance.upper_value:.2f}%. "
            "No sample size reaches the target: as subjects are added the "
            "confidence interval shrinks toward the true ratio, so it converges "
            "onto the boundary rather than inside it. This is a statement about "
            "the assumed ratio, not about the study size."
        )

    n = 4
    mathematical_n: int | None = None
    achieved = 0.0
    while n <= _MAX_N:
        achieved = power_abe(
            cv_percent=cv_percent,
            n_total=n,
            spec=spec,
            design=design,
            expected_ratio=expected_ratio,
        ).power
        if achieved >= target_power:
            mathematical_n = n
            break
        n += 2

    if mathematical_n is None:
        raise NotPowerable(
            f"No sample size up to {_MAX_N} reaches {target_power:.0%} power at "
            f"CV {cv_percent}% with an assumed ratio of {expected_ratio}."
        )

    # The floor is a property of the DESIGN and of the FRAMEWORK, not only of
    # the jurisdiction: ICH M13A gives 12 evaluable subjects for a crossover but
    # 12 PER GROUP for a parallel design, which is 24 - and only for
    # immediate-release solid oral dosage forms. A jurisdiction-only lookup
    # would apply the wrong one to half of all studies, and a
    # jurisdiction-and-design lookup would apply M13A to products it never
    # covered.
    rule = lookup(
        str(spec.jurisdiction),
        design_family_for(design),
        framework=framework,
        is_highly_variable=spec.drug_class is DrugClass.HIGHLY_VARIABLE,
    )
    regulatory_n = rule.required_total() if rule is not None else None
    if regulatory_n is not None and regulatory_n > mathematical_n:
        recommended = regulatory_n if regulatory_n % 2 == 0 else regulatory_n + 1
        binding = "the regulatory minimum"
    else:
        recommended = mathematical_n
        binding = "the power calculation"

    power_at_recommended = power_abe(
        cv_percent=cv_percent,
        n_total=recommended,
        spec=spec,
        design=design,
        expected_ratio=expected_ratio,
    ).power

    return SampleSizeResult(
        mathematical_n=mathematical_n,
        regulatory_n=regulatory_n,
        regulatory_rule=rule,
        recommended_n=recommended,
        achieved_power=achieved,
        power_at_recommended=power_at_recommended,
        target_power=target_power,
        design=design,
        binding_constraint=binding,
        regulatory_basis=rule.explain() if rule is not None else
        "no confirmed regulatory minimum for this jurisdiction, framework and "
        "design",
    )
