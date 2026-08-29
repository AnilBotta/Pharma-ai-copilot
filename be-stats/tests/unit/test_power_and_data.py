"""Power, sample size, and the input checks that run before either.

As in the crossover suite: invariances and internal consistencies, not
comparisons against remembered numbers. Agreement with an independent
implementation is a validation activity and lives in `validation/`.
"""

from __future__ import annotations

import pytest

from be_stats import (
    CrossoverObservation,
    CrossoverStudy,
    DataError,
    DrugClass,
    Endpoint,
    Jurisdiction,
    NotPowerable,
    ParallelStudy,
    Sequence,
    analyse_parallel,
    power_abe,
    resolve_be_spec,
    sample_size_abe,
)

FDA_SPEC = resolve_be_spec(jurisdiction=Jurisdiction.FDA)
EMA_SPEC = resolve_be_spec(jurisdiction=Jurisdiction.EMA)
EMA_NTI_AUC = resolve_be_spec(
    jurisdiction=Jurisdiction.EMA,
    drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
    endpoint=Endpoint.AUC,
)

# ----------------------------------------------------------------- power ---


def test_power_increases_with_sample_size():
    powers = [
        power_abe(cv_percent=25.0, n_total=n, spec=FDA_SPEC).power
        for n in (8, 16, 24, 32, 48)
    ]
    assert powers == sorted(powers)
    assert powers[0] < powers[-1]


def test_power_decreases_as_variability_rises():
    powers = [
        power_abe(cv_percent=cv, n_total=32, spec=FDA_SPEC).power
        for cv in (10.0, 20.0, 30.0, 40.0)
    ]
    assert powers == sorted(powers, reverse=True)


def test_power_is_a_probability():
    for n in (4, 6, 12, 60, 200):
        for cv in (5.0, 25.0, 60.0):
            assert 0.0 <= power_abe(cv_percent=cv, n_total=n, spec=FDA_SPEC).power <= 1.0


def test_power_is_highest_when_the_true_ratio_is_one():
    """Why the 0.95 default is deliberate rather than arbitrary."""
    powers = [
        power_abe(
            cv_percent=25.0, n_total=24, spec=FDA_SPEC, expected_ratio=r
        ).power
        for r in (1.00, 0.95, 0.90)
    ]
    assert powers[0] > powers[1] > powers[2]


# ----------------------------------------------------------- sample size ---


def test_mathematical_n_is_the_smallest_that_reaches_target():
    """Both halves matter: the answer must reach the target, and the step below
    it must not - otherwise every study costs more than it needs to."""
    target = 0.80
    r = sample_size_abe(cv_percent=25.0, spec=FDA_SPEC, target_power=target)
    assert r.achieved_power >= target
    assert r.mathematical_n % 2 == 0
    below = power_abe(
        cv_percent=25.0, n_total=r.mathematical_n - 2, spec=FDA_SPEC
    ).power
    assert below < target


def test_regulatory_floor_is_separate_from_the_arithmetic():
    """The correction from statistical review.

    At a low CV the arithmetic asks for fewer subjects than FDA will accept.
    Both numbers must survive into the result, and which one is binding must
    be visible - it is usually the one nobody planned for.
    """
    r = sample_size_abe(cv_percent=10.0, spec=FDA_SPEC)
    assert r.mathematical_n < 12
    assert r.regulatory_n == 12
    assert r.recommended_n == 12
    assert r.binding_constraint == "the regulatory minimum"
    # Running the floor buys power the arithmetic did not ask for.
    assert r.power_at_recommended > r.achieved_power


def test_power_calculation_is_binding_when_it_exceeds_the_floor():
    r = sample_size_abe(cv_percent=30.0, spec=FDA_SPEC)
    assert r.mathematical_n > 12
    assert r.recommended_n == r.mathematical_n
    assert r.binding_constraint == "the power calculation"
    assert r.power_at_recommended == pytest.approx(r.achieved_power)


def test_both_jurisdictions_floor_an_m13a_crossover_at_twelve():
    """Updated twice, and the second time is the interesting one.

    The first version asserted EMA had no minimum at all. The second asserted
    both regions floor a crossover at twelve, from different documents. This
    version adds the condition both of those left implicit: that floor is ICH
    M13A's, so it only reaches a study the caller has said M13A governs.

    Both regions cite their own publication of the same Q&A, which is why the
    registry keys on jurisdiction as well as framework and design.
    """
    from be_stats.minimums import Framework

    m13a = Framework.ICH_M13A
    fda = sample_size_abe(
        cv_percent=10.0, spec=FDA_SPEC, design="2x2", framework=m13a
    )
    ema = sample_size_abe(
        cv_percent=10.0, spec=EMA_SPEC, design="2x2", framework=m13a
    )

    assert fda.mathematical_n == ema.mathematical_n == 8
    assert fda.regulatory_n == ema.regulatory_n == 12
    assert fda.recommended_n == ema.recommended_n == 12

    assert "FDA" in str(fda.regulatory_rule.citation)
    assert "ICH" in str(ema.regulatory_rule.citation)


def test_recommended_n_is_even_even_when_the_floor_is_odd():
    """Both designs allocate equally to two groups, so an odd total cannot."""
    from be_stats.minimums import (
        DesignFamily,
        Framework,
        RegulatoryMinimum,
        _REGISTRY,
    )
    from be_stats.provenance import Citation, VerificationStatus

    key = ("FIXTURE", Framework.GENERAL, DesignFamily.CROSSOVER)
    _REGISTRY[key] = RegulatoryMinimum(
        jurisdiction="FIXTURE",
        design_family=DesignFamily.CROSSOVER,
        citation=Citation(authority="fixture", document="odd floor"),
        evaluable_total=13,
        verification=VerificationStatus.UNVERIFIED,
    )
    try:
        from dataclasses import replace

        odd = replace(FDA_SPEC, jurisdiction="FIXTURE")
        r = sample_size_abe(cv_percent=8.0, spec=odd, design="2x2")
        assert r.regulatory_n == 13
        assert r.recommended_n == 14
        assert r.recommended_n % 2 == 0
    finally:
        del _REGISTRY[key]


def test_parallel_needs_more_subjects_than_crossover():
    """A between-subject comparison throws away the pairing, so it must cost
    more. If this inverts, the standard errors have been swapped."""
    crossover = sample_size_abe(
        cv_percent=25.0, spec=FDA_SPEC, design="2x2"
    ).mathematical_n
    parallel = sample_size_abe(
        cv_percent=25.0, spec=FDA_SPEC, design="parallel"
    ).mathematical_n
    assert parallel > crossover


def test_narrower_limits_cost_subjects():
    """EMA's NTI narrowing has a price. Asserted as a direction only - the
    magnitude depends on the full scenario and is a validation matter."""
    standard = sample_size_abe(cv_percent=15.0, spec=EMA_SPEC).mathematical_n
    narrowed = sample_size_abe(cv_percent=15.0, spec=EMA_NTI_AUC).mathematical_n
    assert narrowed > standard


def test_higher_target_power_needs_more_subjects():
    at_80 = sample_size_abe(
        cv_percent=25.0, spec=FDA_SPEC, target_power=0.80
    ).mathematical_n
    at_90 = sample_size_abe(
        cv_percent=25.0, spec=FDA_SPEC, target_power=0.90
    ).mathematical_n
    assert at_90 > at_80


def test_ratio_on_the_boundary_is_not_powerable_at_any_size():
    """Detected up front, not discovered after ten thousand iterations.

    As n grows the interval shrinks toward the true ratio, so a ratio sitting
    on the limit converges onto the boundary rather than inside it. This is a
    statement about the assumed ratio, not the study size, and the message
    says so.
    """
    for ratio in (0.80, 1.25, 0.75, 1.30):
        with pytest.raises(NotPowerable, match="assumed ratio"):
            sample_size_abe(
                cv_percent=25.0, spec=FDA_SPEC, expected_ratio=ratio
            )


def test_a_very_large_cv_is_merely_expensive_not_infeasible():
    """The counterpart, so the distinction is recorded rather than rediscovered.

    An earlier test asserted a huge CV could not be powered. That premise was
    wrong: subjects buy their way out of variability.
    """
    r = sample_size_abe(cv_percent=100.0, spec=FDA_SPEC, target_power=0.80)
    assert r.achieved_power >= 0.80
    assert r.mathematical_n > 100


def test_method_is_named_on_every_result():
    """A sample size whose method cannot be traced cannot be defended."""
    assert "non-central t" in sample_size_abe(cv_percent=20.0, spec=FDA_SPEC).method
    assert "non-central t" in power_abe(
        cv_percent=20.0, n_total=24, spec=FDA_SPEC
    ).method


# ------------------------------------------------------------ input data ---


def test_non_positive_measurement_is_refused():
    with pytest.raises(DataError, match="logarithm"):
        CrossoverObservation("S1", Sequence.RT, 100.0, 0.0)
    with pytest.raises(DataError, match="logarithm"):
        CrossoverObservation("S1", Sequence.RT, -5.0, 100.0)


def test_a_single_sequence_is_refused():
    """With one sequence the treatment effect is completely confounded with
    the period effect. A number here would be worse than a failure."""
    obs = [CrossoverObservation(f"S{i}", Sequence.RT, 100.0, 105.0) for i in range(6)]
    with pytest.raises(DataError, match="confounded"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_duplicate_subject_is_refused():
    obs = [
        CrossoverObservation("S1", Sequence.RT, 100.0, 105.0),
        CrossoverObservation("S1", Sequence.TR, 100.0, 105.0),
        CrossoverObservation("S2", Sequence.TR, 100.0, 105.0),
    ]
    with pytest.raises(DataError, match="more than once"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_too_few_subjects_is_refused():
    obs = [
        CrossoverObservation("S1", Sequence.RT, 100.0, 105.0),
        CrossoverObservation("S2", Sequence.TR, 100.0, 105.0),
    ]
    with pytest.raises(DataError, match="too few"):
        CrossoverStudy(endpoint="AUC", observations=obs)


def test_parallel_group_needs_two_subjects():
    with pytest.raises(DataError, match="[Aa]t least 2"):
        ParallelStudy(endpoint="AUC", test=[100.0], reference=[100.0, 101.0])


# --------------------------------------------------------------- parallel ---


def test_parallel_analysis_reports_between_subject_cv():
    study = ParallelStudy(
        endpoint="AUC",
        test=[100.0, 110.0, 95.0, 105.0, 98.0, 102.0],
        reference=[99.0, 108.0, 97.0, 103.0, 101.0, 100.0],
    )
    result = analyse_parallel(study, FDA_SPEC)
    assert result.design == "parallel"
    assert result.cv_kind.startswith("between-subject")
    assert result.degrees_of_freedom == 10
    assert result.ci_lower < result.point_estimate < result.ci_upper


def test_parallel_refuses_a_method_that_has_no_fixed_interval():
    """A parallel study cannot be assessed under the highly-variable method.

    Not because the method is unimplemented - it is, from the highly-variable
    release - but because reference scaling needs replicate reference
    measurements, which a parallel design does not collect, and its acceptance
    region is therefore not a fixed interval.
    """
    fda_hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    study = ParallelStudy(
        endpoint="AUC", test=[100.0, 110.0, 95.0], reference=[99.0, 108.0, 97.0]
    )
    from be_stats.spec import NotApplicable

    with pytest.raises(NotApplicable, match="fixed acceptance interval"):
        analyse_parallel(study, fda_hvd)


def test_an_unimplemented_method_still_refuses_by_name(monkeypatch):
    """The `NotImplementedMethod` path, no longer kept alive by NTI.

    NTI used to be the package's one unimplemented method and was borrowed
    here to exercise the refusal. It is implemented as of the Appendix C
    release, and every other Method is too - so the mechanism is exercised by
    marking one unimplemented rather than by relying on a gap that has closed.
    """
    import be_stats.spec as spec_module
    from be_stats import NotImplementedMethod
    from be_stats.spec import Method

    # IMPLEMENTED is derived from VALIDATION at import time, so the SET is what
    # has to be patched - see the twin of this test in test_abe_crossover.py.
    monkeypatch.setattr(
        spec_module,
        "IMPLEMENTED",
        frozenset(m for m in Method if m is not Method.STANDARD_ABE),
    )
    spec = resolve_be_spec(jurisdiction=Jurisdiction.FDA)
    study = ParallelStudy(
        endpoint="AUC", test=[100.0, 110.0, 95.0], reference=[99.0, 108.0, 97.0]
    )
    with pytest.raises(NotImplementedMethod):
        analyse_parallel(study, spec)
