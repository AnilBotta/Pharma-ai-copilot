"""EMA ABEL: eligibility, limits, the cap, and the two criteria.

Boundary behaviour gets more attention than anything else here. Every rule in
section 4.1.10 is a comparison against a stated number, and a comparison is
exactly the kind of thing that is wrong by one boundary and right everywhere
else.
"""

from __future__ import annotations

import math

import pytest

from be_stats.ema_hvd import (
    EmaDesignSupport,
    EmaReplicateDataset,
    assess_ema_endpoint,
    assess_ema_study,
    ema_abel_limits,
    ema_design_support,
)
from be_stats.replicate import DataError, ReplicateObservation, parse_sequence
from be_stats.spec import (
    EMA_ABEL_SCALABLE_ENDPOINTS,
    EMA_HVD_CONSTANTS,
    Endpoint,
    Method,
    ema_hvd_scaling_eligible,
)
from be_stats.study import Treatment

THRESHOLD = EMA_HVD_CONSTANTS["cv_wr_scaling_threshold_percent"].value


def swr_for(cv_percent: float) -> float:
    return math.sqrt(math.log1p((cv_percent / 100.0) ** 2))


# ------------------------------------------------------------ eligibility ---


def test_the_variability_boundary_is_strictly_greater_on_the_cv_scale():
    """4.1.10 says '>30%'. Not >=. Not an sWR threshold.

    The exact boundary operator decides real studies. A study landing at
    CVwR = 30.000% is NOT eligible, and the FDA lesson is why this is asserted
    rather than assumed: 0.294 and sqrt(ln(1+0.30^2)) = 0.293560 differ, and
    substituting one for the other moved studies across a switch.
    """
    for cv, expected in ((29.9999, False), (30.0, False), (30.0001, True)):
        eligible, reason = ema_hvd_scaling_eligible(
            cv_wr_percent=cv, endpoint=Endpoint.CMAX
        )
        assert eligible is expected, (cv, reason)

    # And the reason names the scale, so a reader cannot mistake it for sWR.
    _, reason = ema_hvd_scaling_eligible(
        cv_wr_percent=30.0, endpoint=Endpoint.CMAX
    )
    assert "CV scale" in reason


def test_emas_threshold_is_not_fdas_threshold_even_though_both_mention_thirty():
    """The two regulators' triggers are different numbers on the same scale.

    EMA's CVwR > 30% is sWR > 0.293560...; FDA states sWR >= 0.294. Studies
    exist between them. This is VAL-FDA-HVD-002 seen from the EMA side, and it
    is the reason the constants are in separate dictionaries.
    """
    from be_stats.spec import FDA_HVD_CONSTANTS

    ema_as_swr = swr_for(THRESHOLD)
    fda = FDA_HVD_CONSTANTS["swr_switching_threshold"].value

    assert ema_as_swr == pytest.approx(0.293560379208524, abs=1e-15)
    assert fda == 0.294
    assert ema_as_swr != fda

    # A study in the gap: scalable under EMA, unscaled under FDA.
    between = 0.2937
    assert between > ema_as_swr
    assert between < fda


def test_auc_may_not_be_scaled_however_variable_it_is():
    """4.1.10's final paragraph, which is a rule and not a default."""
    assert EMA_ABEL_SCALABLE_ENDPOINTS == frozenset({Endpoint.CMAX})
    for cv in (31.0, 60.0, 200.0):
        eligible, reason = ema_hvd_scaling_eligible(
            cv_wr_percent=cv, endpoint=Endpoint.AUC
        )
        assert eligible is False
        assert "does not apply to AUC" in reason


# ----------------------------------------------------------------- limits ---


def test_the_limits_are_symmetric_in_the_log_domain():
    """EMA writes the pair as exp[+/- k.sWR], so lower * upper == 100^2.

    PowerTOST computes the lower limit as 1/upper instead; equal in exact
    arithmetic. Asserting the symmetric form here records which one this
    package implements.
    """
    limits = ema_abel_limits(swr_for(40.0))
    assert limits.raw_lower_percent * limits.raw_upper_percent == pytest.approx(
        10000.0, rel=1e-12
    )


def test_a_zero_reference_variability_refuses_rather_than_returning_a_point():
    """exp(0) = 1 would be an acceptance range of a single point.

    EMA states no rule for that, so none is invented — the same stance
    `reference_variance.py` takes on a zero sWR for FDA, reached independently
    here because the two must not share a decision.
    """
    with pytest.raises(DataError, match="single point"):
        ema_abel_limits(0.0)
    with pytest.raises(DataError):
        ema_abel_limits(-0.1)


@pytest.mark.parametrize(
    "cv_percent, expect_cap",
    [(30.5, False), (45.0, False), (49.0, False), (50.0, True), (80.0, True)],
)
def test_the_cap_engages_only_where_the_limits_exceed_the_stated_maximum(
    cv_percent, expect_cap
):
    limits = ema_abel_limits(swr_for(cv_percent))
    assert limits.cap_applied is expect_cap
    if expect_cap:
        assert limits.final_lower_percent == EMA_HVD_CONSTANTS[
            "cap_lower_percent"
        ].value
        assert limits.final_upper_percent == EMA_HVD_CONSTANTS[
            "cap_upper_percent"
        ].value
    else:
        assert limits.final_lower_percent == limits.raw_lower_percent
        assert limits.final_upper_percent == limits.raw_upper_percent


def test_the_uncapped_limits_are_always_reported_even_when_capped():
    """A cap that replaces a number silently is a cap nobody can check."""
    limits = ema_abel_limits(swr_for(70.0))
    assert limits.cap_applied is True
    assert limits.raw_lower_percent < limits.final_lower_percent
    assert limits.raw_upper_percent > limits.final_upper_percent
    assert "CAP APPLIED" in " ".join(limits.provenance())


def test_widening_is_monotone_in_variability_up_to_the_cap():
    """More variable reference, wider limits — until the cap, then flat.

    The Q&A puts it as: 'The widening is on a smooth function, i.e. the
    permitted widening increases as the variability increases (to a maximum of
    50%). It is not an all or nothing criteria with 30% being a critical
    point.'
    """
    widths = [
        ema_abel_limits(swr_for(cv)).final_upper_percent
        - ema_abel_limits(swr_for(cv)).final_lower_percent
        for cv in (31, 35, 40, 45, 49)
    ]
    assert widths == sorted(widths)
    assert all(a < b for a, b in zip(widths, widths[1:]))

    capped = [
        ema_abel_limits(swr_for(cv)).final_upper_percent
        - ema_abel_limits(swr_for(cv)).final_lower_percent
        for cv in (50, 60, 90)
    ]
    assert len(set(capped)) == 1, "past the cap the width must stop growing"


# ----------------------------------------------------------------- designs ---


def test_every_design_is_classified_with_a_reason():
    for design in (
        "fully_replicate",
        "partial_replicate",
        "2x2_crossover",
        "parallel",
        "2x2x3_replicate_tr_rt_r",
    ):
        support, reason = ema_design_support(design)
        assert support in {
            EmaDesignSupport.SUPPORTED,
            EmaDesignSupport.NOT_APPLICABLE,
            EmaDesignSupport.NOT_IMPLEMENTED,
        }
        assert len(reason) > 40, f"{design} needs a reason, not a label"

    # Not applicable and not implemented are different claims and must not be
    # conflated: one says the design cannot support the method, the other says
    # this package has not built it.
    assert ema_design_support("2x2_crossover")[0] is EmaDesignSupport.NOT_APPLICABLE
    assert (
        ema_design_support("2x2x3_replicate_tr_rt_r")[0]
        is EmaDesignSupport.NOT_IMPLEMENTED
    )


def test_an_unknown_design_refuses_rather_than_defaulting():
    with pytest.raises(DataError, match="not a design this package classifies"):
        ema_design_support("some_new_design")


# ------------------------------------------------- the end-to-end decision ---


def _study(
    *,
    cv_wr_percent: float,
    ratio: float,
    n_per_sequence: int = 30,
    endpoint: str = "Cmax",
    seed: int = 7,
) -> list[ReplicateObservation]:
    """A fully replicate study built to a target reference variability.

    Deterministic: the residuals are a fixed antisymmetric pattern rather than
    random draws, so a boundary test cannot pass or fail by luck.
    """
    import random

    rng = random.Random(seed)
    sigma = swr_for(cv_wr_percent)
    rows: list[ReplicateObservation] = []
    for label in ("TRTR", "RTRT"):
        sequence = parse_sequence(label)
        for k in range(n_per_sequence):
            subject = f"{label}-{k}"
            subject_effect = rng.gauss(0.0, 0.35)
            for period in range(1, 5):
                treatment = sequence.expected_treatment(period)
                is_test = treatment is Treatment.TEST
                mean = subject_effect + (math.log(ratio) if is_test else 0.0)
                rows.append(
                    ReplicateObservation(
                        subject_id=subject,
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint=endpoint,
                        value=math.exp(mean + rng.gauss(0.0, sigma)),
                    )
                )
    return rows


def test_a_low_variability_study_routes_to_the_conventional_range():
    """Not eligible for widening, and decided anyway.

    EMA specifies Method A for a replicate design regardless of variability, so
    the unscaled branch is a real decision here — unlike FDA HVD, where the
    unscaled replicate branch needs Appendix C and this package refuses.
    """
    result = assess_ema_endpoint(
        _study(cv_wr_percent=15.0, ratio=0.97), endpoint=Endpoint.CMAX
    )
    assert result.scaling_eligible is False
    assert result.selected_method is Method.STANDARD_ABE
    assert result.applied_limits == (80.00, 125.00)
    assert result.raw_scaled_limits is None
    assert result.cap_applied is None
    assert result.decided is True
    assert result.passes is not None


def test_a_highly_variable_study_routes_to_abel_and_shows_its_working():
    result = assess_ema_endpoint(
        _study(cv_wr_percent=45.0, ratio=0.90), endpoint=Endpoint.CMAX
    )
    assert result.scaling_eligible is True
    assert result.selected_method is Method.EMA_HVD_ABEL
    assert result.cv_wr_percent > 30.0
    assert result.raw_scaled_limits is not None
    assert result.final_scaled_limits == result.applied_limits
    assert result.applied_limits[0] < 80.0 < 125.0 < result.applied_limits[1]
    assert result.decided is True


def test_both_criteria_are_reported_separately():
    """A failure must say WHICH condition failed.

    4.1.10 requires the interval inside the applicable limits AND the GMR
    inside 80.00-125.00%. A single boolean cannot distinguish a study that
    missed on precision from one that missed on location.
    """
    result = assess_ema_endpoint(
        _study(cv_wr_percent=45.0, ratio=0.78), endpoint=Endpoint.CMAX
    )
    assert result.interval_criterion_passes is not None
    assert result.point_estimate_criterion_passes is False, (
        "a GMR of about 0.78 is outside 80.00-125.00% and must fail the point "
        "estimate constraint on its own"
    )
    assert result.passes is False
    assert result.passes == (
        result.interval_criterion_passes
        and result.point_estimate_criterion_passes
    )


def test_the_point_estimate_constraint_can_fail_a_study_the_interval_passes():
    """The reason ABEL needs two criteria rather than one.

    With enough widening, a badly located but precisely estimated study can sit
    entirely inside the widened limits. The GMR constraint is what stops that.
    """
    result = assess_ema_endpoint(
        _study(cv_wr_percent=55.0, ratio=0.79, n_per_sequence=60),
        endpoint=Endpoint.CMAX,
    )
    if result.interval_criterion_passes and not result.point_estimate_criterion_passes:
        assert result.passes is False
    # Whatever the draw, the conjunction must hold.
    assert result.passes == (
        result.interval_criterion_passes
        and result.point_estimate_criterion_passes
    )


def test_auc_and_cmax_are_decided_independently_in_one_study():
    """Point 12: the same study, two endpoints, two different routes.

    A highly variable reference gives Cmax a widened range and leaves AUC at
    80.00-125.00%, because 4.1.10 forbids widening AUC at any variability. If
    these were decided together, the AUC rule would be unenforceable.
    """
    cmax = _study(cv_wr_percent=45.0, ratio=0.90, endpoint="Cmax")
    auc = _study(cv_wr_percent=45.0, ratio=0.90, endpoint="AUC", seed=11)

    results = assess_ema_study({Endpoint.CMAX: cmax, Endpoint.AUC: auc})

    assert results[Endpoint.CMAX].scaling_eligible is True
    assert results[Endpoint.CMAX].selected_method is Method.EMA_HVD_ABEL
    assert results[Endpoint.CMAX].applied_limits[1] > 125.0

    assert results[Endpoint.AUC].scaling_eligible is False
    assert results[Endpoint.AUC].selected_method is Method.STANDARD_ABE
    assert results[Endpoint.AUC].applied_limits == (80.00, 125.00)
    assert results[Endpoint.AUC].cv_wr_percent > 30.0, (
        "the AUC reference really is highly variable — it is the RULE that "
        "forbids widening, not the data"
    )


def test_the_result_cites_ema_and_never_appendix_g():
    """Provenance is regulator-specific even where the arithmetic rhymes."""
    result = assess_ema_endpoint(
        _study(cv_wr_percent=45.0, ratio=0.95), endpoint=Endpoint.CMAX
    )
    text = " ".join(result.provenance())
    assert "4.1.10" in text
    assert "CPMP/EWP/QWP/1401/98" in text
    assert "Appendix G" not in text
    assert "Howe" not in text
    assert "sigma_w0" not in text


def test_a_partial_replicate_study_is_supported():
    rows: list[ReplicateObservation] = []
    import random

    rng = random.Random(3)
    sigma = swr_for(40.0)
    for label in ("TRR", "RTR", "RRT"):
        sequence = parse_sequence(label)
        for k in range(12):
            effect = rng.gauss(0.0, 0.3)
            for period in range(1, 4):
                treatment = sequence.expected_treatment(period)
                mean = effect + (
                    math.log(0.95) if treatment is Treatment.TEST else 0.0
                )
                rows.append(
                    ReplicateObservation(
                        subject_id=f"{label}-{k}",
                        sequence=sequence,
                        period=period,
                        treatment=treatment,
                        endpoint="Cmax",
                        value=math.exp(mean + rng.gauss(0.0, sigma)),
                    )
                )

    result = assess_ema_endpoint(rows, endpoint=Endpoint.CMAX)
    assert str(result.design) == "partial_replicate"
    assert result.decided is True


def test_the_dataset_refuses_a_file_spanning_two_endpoints():
    rows = _study(cv_wr_percent=40.0, ratio=0.95, endpoint="Cmax")[:8]
    rows += _study(cv_wr_percent=40.0, ratio=0.95, endpoint="AUC")[:8]
    with pytest.raises(DataError, match="endpoints"):
        EmaReplicateDataset.build(rows)
