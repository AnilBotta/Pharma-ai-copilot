"""Simulate studies, decide each with be-stats, report the proportions.

WHY THIS EXISTS

PowerTOST's FDA scaled functions - `power.RSABE`, `power.NTID` - report
EMPIRICAL POWER for a scenario. They do not analyse a dataset. `be-stats` does
only the opposite. So to compare the two at all, the Python side has to be made
to produce the same kind of quantity: simulate studies, decide each one, and
report the proportion that pass.

That is a weaker comparison than checking a criterion value against a criterion
value, and a stronger one than checking nothing. It exercises the whole
pipeline - dataset construction, sWR, sWT, the treatment contrast, the
criterion - so a disagreement is a disagreement about the procedure rather than
about plumbing.

WHERE THIS LIVES, AND WHY NOT IN THE PACKAGE

`be_stats` is a pure analysis package with one dependency. Simulation harnesses
for validating it against another tool are not part of it, and putting them
there would make validation scaffolding into something a caller could import
and a qualification exercise would have to cover. It lives beside the package,
not inside it.

THE MODEL BEING SIMULATED, STATED SO IT CAN BE DISAGREED WITH

    log Y_ijk = mu + subject_i + treatment_effect + e_ijk

with `subject_i ~ N(0, sigma_between^2)` common to both treatments, and
`e_ijk ~ N(0, sigma_wT^2)` or `N(0, sigma_wR^2)` by treatment.

Crucially there is NO subject-by-formulation interaction term. That is not an
oversight: `power.RSABE` and `power.NTID` take only CV (or CVwT and CVwR), so
they assume none either. Introducing one here would make the two sides model
different studies and the comparison meaningless. If a future comparison needs
that term, both sides have to gain it together.

Period effects are omitted for the same reason - neither side models them.
"""

from __future__ import annotations

import math
import random

from be_stats import (
    ReplicateDataset,
    ReplicateObservation,
    Treatment,
    assess_endpoint,
    assess_nti_endpoint,
    parse_sequence,
)
from be_stats.spec import FDA_HVD_CONSTANTS

#: Between-subject variability. It cancels in every within-subject contrast the
#: procedures use, so its value cannot affect any comparison - which is worth
#: asserting rather than assuming, and `test_external_harness.py` does.
BETWEEN_SUBJECT_SD = 0.40

#: Sequences by PowerTOST design code, so the case files can speak PowerTOST's
#: vocabulary and this module translates once.
DESIGNS: dict[str, tuple[str, ...]] = {
    "2x2x4": ("TRTR", "RTRT"),
    "2x3x3": ("TRR", "RTR", "RRT"),
}


def _simulate_study(
    *,
    labels: tuple[str, ...],
    n_by_sequence: list[int],
    sigma_wt: float,
    sigma_wr: float,
    theta0: float,
    endpoint: str,
    rng: random.Random,
) -> ReplicateDataset:
    observations = []
    for label, n in zip(labels, n_by_sequence):
        sequence = parse_sequence(label)
        for k in range(n):
            subject_effect = rng.gauss(0.0, BETWEEN_SUBJECT_SD)
            for period in range(1, sequence.periods + 1):
                treatment = sequence.expected_treatment(period)
                is_test = treatment is Treatment.TEST
                mean_log = subject_effect + (math.log(theta0) if is_test else 0.0)
                sigma = sigma_wt if is_test else sigma_wr
                observations.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(mean_log + rng.gauss(0.0, sigma)),
                    )
                )
    return ReplicateDataset.build(observations)


def _allocate(n: int, sequences: int) -> list[int]:
    """Subjects per sequence, as evenly as a total allows.

    PowerTOST throws a message for an indivisible total and allocates the
    remainder; this does the same thing so the two sides analyse the same
    study shape.
    """
    base, remainder = divmod(n, sequences)
    return [base + (1 if i < remainder else 0) for i in range(sequences)]


def simulate_scaled_power(
    *,
    method: str,
    design: str,
    cv_wr: float,
    cv_wt: float,
    theta0: float,
    n: int,
    nsims: int,
    seed: int,
) -> dict[str, float]:
    """Empirical power of the be-stats decision, by component.

    Returns proportions named to match PowerTOST's `details = TRUE` vector, so
    the case files compare like with like:

        p_be_sabec    the scaled criterion alone
        p_be_pe       the point-estimate constraint alone     [RSABE]
        p_be_sratio   the sigma_wT / sigma_wR criterion alone [NTI]

    THE OVERALL p(BE) IS NOT PRODUCED, FOR EITHER METHOD.

    For RSABE it is the MIXED procedure - conventional ABE below the switch,
    scaled above it - and be-stats does not implement the unscaled branch for a
    replicate design. For NTI it requires criterion (b), the unscaled
    80.00-125.00% test, which needs Appendix C and is likewise unimplemented.
    In both cases there is no Python value to compare, so none is invented.
    The case files record this under `not_cross_checkable`.

    `fraction_below_switch` is reported but never compared. It is a diagnostic:
    it says how much of the scenario the missing unscaled branch would have
    governed, which is how much of PowerTOST's overall p(BE) is out of reach.
    """
    if design not in DESIGNS:
        raise ValueError(
            f"design {design!r} is not one this harness translates; known: "
            f"{sorted(DESIGNS)}"
        )
    labels = DESIGNS[design]
    n_by_sequence = _allocate(n, len(labels))
    sigma_wt = math.sqrt(math.log1p(cv_wt**2))
    sigma_wr = math.sqrt(math.log1p(cv_wr**2))
    threshold = FDA_HVD_CONSTANTS["swr_switching_threshold"].value

    rng = random.Random(seed)
    counts = {"p_be_sabec": 0, "p_be_pe": 0, "p_be_sratio": 0}
    below_switch = 0
    evaluated = 0

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

        if method == "fda_hvd_rsabe":
            # THE COMPONENTS ARE COMPUTED FOR EVERY SIMULATED STUDY.
            #
            # PowerTOST reports p(BE-sABEc) and p(BE-pe) as the power of each
            # criterion ALONE, over all simulations - the scaled criterion is
            # computable whether or not the mixed procedure would have routed
            # that study to it. So the components are taken directly rather
            # than from `rsabe_result`, which exists only above the switch.
            #
            # The overall p(BE) is deliberately NOT produced here: it is the
            # mixed procedure, and be-stats does not implement the unscaled
            # branch, so there is nothing to compare it with.
            from be_stats.hvd import point_estimate_constraint, scaled_criterion
            from be_stats.reference_variance import estimate_reference_variance
            from be_stats.treatment_contrast import estimate_treatment_contrast

            variance = estimate_reference_variance(dataset)
            contrast = estimate_treatment_contrast(dataset)
            if not variance.estimable or not contrast.estimable:
                continue
            evaluated += 1
            if variance.swr is not None and variance.swr < threshold:
                below_switch += 1
            criterion = scaled_criterion(
                contrast=contrast, reference_variance=variance
            )
            counts["p_be_sabec"] += int(criterion.passes)
            counts["p_be_pe"] += int(point_estimate_constraint(contrast).passes)

        elif method == "fda_nti":
            result = assess_nti_endpoint(dataset)
            scaled = result.scaled_mean_criterion
            ratio = result.variability_ratio_criterion
            if scaled is None or ratio is None or ratio.passes is None:
                continue
            evaluated += 1
            counts["p_be_sabec"] += int(scaled.passes)
            counts["p_be_sratio"] += int(ratio.passes)

        else:
            raise ValueError(f"no simulation path for method {method!r}")

    if evaluated == 0:
        raise RuntimeError("no simulated study produced an estimable result")

    out = {
        "p_be_sabec": counts["p_be_sabec"] / evaluated,
        "nsims_evaluated": float(evaluated),
        "fraction_below_switch": below_switch / evaluated,
    }
    if method == "fda_hvd_rsabe":
        out["p_be_pe"] = counts["p_be_pe"] / evaluated
    else:
        out["p_be_sratio"] = counts["p_be_sratio"] / evaluated
    return out


def monte_carlo_tolerance(p: float, nsims_python: int, nsims_r: int) -> float:
    """The tolerance two Monte Carlo estimates of one probability deserve.

    Both sides estimate the same `p` by simulation, so the difference between
    them has standard deviation `sqrt(p(1-p)(1/n1 + 1/n2))`. Four of those is
    the tolerance - wide enough that an agreeing pair passes essentially
    always, narrow enough that a real procedural difference of more than about
    a percentage point fails.

    Computed from the replicate counts actually used. Not chosen by running the
    comparison and widening until it passed, which is the failure mode this
    whole directory exists to avoid.
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be a probability, got {p}")
    variance = p * (1.0 - p) * (1.0 / nsims_python + 1.0 / nsims_r)
    return 4.0 * math.sqrt(variance)
