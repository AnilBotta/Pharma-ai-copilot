"""Which designs are accepted, which are refused, and what a refusal says.

These are routing and integrity tests, not arithmetic. The question is whether
a dataset reaches the estimator at all, and whether a study that should not
reach it is stopped with a reason someone can act on.

THE INVARIANCE TESTS ARE THE LOAD-BEARING ONES

A bioequivalence result that depends on how a CSV was sorted is a result nobody
can reproduce, and the failure is invisible: the number looks ordinary. Three
transformations must leave every quantity identical - shuffling rows, renaming
subjects, and reordering sequence groups. They are cheap to run and they are
the reason `reference_periods()` reads the sequence name instead of sorting
whatever arrived.
"""

from __future__ import annotations

import math
import random

import pytest

from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.reference_variance import (
    FullyReplicateReferenceVarianceEstimator,
    NotEstimable,
    PartialReplicateReferenceVarianceEstimator,
    estimate_reference_variance,
    estimator_for,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateObservation,
    ReplicateSequence,
    UnsupportedDesign,
    identify_design,
    parse_sequence,
    parse_treatment,
)
from be_stats.study import DataError, Treatment


def rows_for(label: str, subject: str, values: list[float]):
    """Well-formed rows: the treatment always comes from the sequence."""
    sequence = parse_sequence(label)
    assert len(values) == sequence.periods
    return [
        ReplicateObservation(
            subject_id=subject,
            sequence=sequence,
            period=period,
            treatment=sequence.expected_treatment(period),
            endpoint="AUC",
            value=value,
        )
        for period, value in enumerate(values, start=1)
    ]


def partial_study() -> list[ReplicateObservation]:
    """Four subjects per sequence, values varied enough to be non-degenerate."""
    observations: list[ReplicateObservation] = []
    for label in ("TRR", "RTR", "RRT"):
        for k in range(4):
            base = [100.0 + 3 * k, 108.0 - 2 * k, 96.0 + k]
            observations += rows_for(label, f"{label}-{k}", base)
    return observations


def fully_study() -> list[ReplicateObservation]:
    observations: list[ReplicateObservation] = []
    for label in ("TRTR", "RTRT"):
        for k in range(3):
            base = [100.0 + k, 105.0 - k, 98.0 + 2 * k, 103.0 + k]
            observations += rows_for(label, f"{label}-{k}", base)
    return observations


# ------------------------------------------------------------ valid designs ---


@pytest.mark.parametrize("label", ["TRR", "RTR", "RRT"])
def test_each_partial_replicate_sequence_is_recognised(label):
    dataset = ReplicateDataset.build(
        rows_for(label, "S1", [100.0, 110.0, 95.0])
        + rows_for(label, "S2", [101.0, 90.0, 105.0])
    )
    assert dataset.design is ReplicateDesign.PARTIAL_REPLICATE
    assert len(dataset.records) == 2


@pytest.mark.parametrize("label", ["TRTR", "RTRT"])
def test_each_fully_replicate_sequence_is_recognised(label):
    dataset = ReplicateDataset.build(
        rows_for(label, "S1", [100.0, 110.0, 95.0, 108.0])
        + rows_for(label, "S2", [101.0, 90.0, 105.0, 99.0])
    )
    assert dataset.design is ReplicateDesign.FULLY_REPLICATE
    assert len(dataset.records) == 2


def test_the_full_partial_study_estimates():
    result = estimate_reference_variance(ReplicateDataset.build(partial_study()))
    assert result.estimable
    assert result.n_subjects == 12
    assert result.n_sequences == 3
    assert result.degrees_of_freedom == 9
    assert result.swr > 0.0


# ---------------------------------------------------------- invalid designs ---


@pytest.mark.parametrize("label", ["TRT", "TRRR", "RRTR", "TT", "RR", "TRRT"])
def test_unsupported_sequences_are_refused_by_name(label):
    with pytest.raises(UnsupportedDesign) as exc:
        parse_sequence(label)
    assert exc.value.code is DiagnosticCode.UNKNOWN_SEQUENCE
    assert "TRR" in str(exc.value), "the refusal must name what IS supported"


def test_mixing_two_designs_in_one_file_is_refused():
    """Five sequences is not a five-sequence design; it is two studies."""
    with pytest.raises(UnsupportedDesign) as exc:
        identify_design({ReplicateSequence.TRR, ReplicateSequence.TRTR})
    assert exc.value.code is DiagnosticCode.UNSUPPORTED_REPLICATE_DESIGN


def test_an_unknown_treatment_is_refused_with_the_packages_own_error():
    with pytest.raises(DataError) as exc:
        parse_treatment("P")
    assert exc.value.code is DiagnosticCode.UNKNOWN_TREATMENT
    assert "test" in str(exc.value) and "reference" in str(exc.value)


def test_two_endpoints_in_one_dataset_are_refused():
    rows = rows_for("TRR", "S1", [100.0, 110.0, 95.0])
    rows += [
        ReplicateObservation("S2", ReplicateSequence.TRR, p, t, "Cmax", 100.0)
        for p, t in ((1, Treatment.TEST), (2, Treatment.REFERENCE), (3, Treatment.REFERENCE))
    ]
    with pytest.raises(DataError, match="endpoints"):
        ReplicateDataset.build(rows)


# ------------------------------------------------------- structural failures ---


def test_a_sequence_period_treatment_mismatch_excludes_the_subject():
    """TRR period 2 is R. A row saying T is a file that disagrees with itself."""
    good = rows_for("TRR", "GOOD", [100.0, 110.0, 95.0])
    bad = [
        ReplicateObservation("BAD", ReplicateSequence.TRR, 1, Treatment.TEST, "AUC", 100.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 2, Treatment.TEST, "AUC", 110.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 3, Treatment.REFERENCE, "AUC", 95.0),
    ]
    dataset = ReplicateDataset.build(good + bad + rows_for("RTR", "OK", [100.0, 105.0, 97.0]))

    assert "BAD" in dataset.subjects_excluded
    assert "GOOD" not in dataset.subjects_excluded
    mismatch = [
        d for d in dataset.diagnostics
        if d.code is DiagnosticCode.SEQUENCE_TREATMENT_MISMATCH
    ]
    assert len(mismatch) == 1
    assert mismatch[0].subject == "BAD"
    assert mismatch[0].severity is Severity.EXCLUSION
    assert mismatch[0].context["expected"] == "R"
    assert mismatch[0].context["observed"] == "T"


def test_a_mismatch_is_not_silently_repaired():
    """The subject is dropped, not re-labelled to match the sequence."""
    bad = [
        ReplicateObservation("BAD", ReplicateSequence.TRR, 1, Treatment.TEST, "AUC", 100.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 2, Treatment.TEST, "AUC", 110.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 3, Treatment.REFERENCE, "AUC", 95.0),
    ]
    dataset = ReplicateDataset.build(
        bad
        + rows_for("TRR", "OK1", [100.0, 110.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )
    assert [r.subject_id for r in dataset.records] == ["OK1", "OK2"]


def test_a_duplicate_period_excludes_rather_than_choosing_a_winner():
    duplicate = rows_for("TRR", "DUP", [100.0, 110.0, 95.0])
    duplicate.append(
        ReplicateObservation(
            "DUP", ReplicateSequence.TRR, 2, Treatment.REFERENCE, "AUC", 120.0
        )
    )
    dataset = ReplicateDataset.build(
        duplicate
        + rows_for("TRR", "OK1", [100.0, 110.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )

    assert "DUP" in dataset.subjects_excluded
    dup = [
        d for d in dataset.diagnostics
        if d.code is DiagnosticCode.DUPLICATE_SUBJECT_PERIOD
    ]
    assert len(dup) == 1
    assert dup[0].context["values"] == [110.0, 120.0]


def test_a_period_outside_the_design_excludes_the_subject():
    rows = rows_for("TRR", "BAD", [100.0, 110.0, 95.0])
    rows.append(
        ReplicateObservation(
            "BAD", ReplicateSequence.TRR, 4, Treatment.REFERENCE, "AUC", 99.0
        )
    )
    dataset = ReplicateDataset.build(
        rows
        + rows_for("TRR", "OK1", [100.0, 110.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )
    assert "BAD" in dataset.subjects_excluded
    assert any(
        d.code is DiagnosticCode.PERIOD_OUT_OF_RANGE for d in dataset.diagnostics
    )


def test_a_non_positive_value_excludes_the_subject():
    rows = [
        ReplicateObservation("BAD", ReplicateSequence.TRR, 1, Treatment.TEST, "AUC", 100.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 2, Treatment.REFERENCE, "AUC", 0.0),
        ReplicateObservation("BAD", ReplicateSequence.TRR, 3, Treatment.REFERENCE, "AUC", 95.0),
    ]
    dataset = ReplicateDataset.build(
        rows
        + rows_for("TRR", "OK1", [100.0, 110.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )
    assert "BAD" in dataset.subjects_excluded
    assert any(
        d.code is DiagnosticCode.NON_POSITIVE_PK_VALUE for d in dataset.diagnostics
    )


def test_a_missing_reference_replicate_excludes_and_says_which_period():
    rows = rows_for("TRR", "SHORT", [100.0, 110.0, 95.0])
    rows = [r for r in rows if r.period != 3]
    dataset = ReplicateDataset.build(
        rows
        + rows_for("TRR", "OK1", [100.0, 110.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )
    missing = [
        d for d in dataset.diagnostics
        if d.code is DiagnosticCode.MISSING_REFERENCE_REPLICATE
    ]
    assert len(missing) == 1
    assert missing[0].subject == "SHORT"
    assert missing[0].context["missing_periods"] == [3]


def test_a_missing_test_observation_is_advisory_not_an_exclusion():
    """sWR needs the references, not the test. Dropping the subject would
    discard evidence about reference variability for a contrast this release
    does not compute - it becomes an exclusion in #56."""
    rows = [r for r in rows_for("TRR", "NOTEST", [100.0, 110.0, 95.0]) if r.period != 1]
    dataset = ReplicateDataset.build(
        rows
        + rows_for("TRR", "OK1", [100.0, 112.0, 95.0])
        + rows_for("RTR", "OK2", [100.0, 105.0, 97.0])
    )
    assert "NOTEST" not in dataset.subjects_excluded
    advisory = [
        d for d in dataset.diagnostics
        if d.code is DiagnosticCode.MISSING_TEST_OBSERVATION
    ]
    assert advisory and advisory[0].severity is Severity.ADVISORY


def test_a_study_where_nobody_survives_raises_rather_than_estimating_nothing():
    rows = [
        ReplicateObservation("B1", ReplicateSequence.TRR, 1, Treatment.REFERENCE, "AUC", 100.0),
        ReplicateObservation("B1", ReplicateSequence.TRR, 2, Treatment.REFERENCE, "AUC", 110.0),
        ReplicateObservation("B1", ReplicateSequence.TRR, 3, Treatment.REFERENCE, "AUC", 95.0),
    ]
    with pytest.raises(DataError, match="No subject survived"):
        ReplicateDataset.build(rows)


def test_the_accounting_adds_up():
    """received = used + excluded, asserted rather than assumed."""
    short = [r for r in rows_for("TRR", "SHORT", [100.0, 110.0, 95.0]) if r.period != 3]
    result = estimate_reference_variance(
        ReplicateDataset.build(partial_study() + short)
    )
    assert result.subjects_received == 13
    assert result.subjects_used == 12
    assert result.subjects_excluded == 1
    assert result.subjects_used + result.subjects_excluded == result.subjects_received
    assert result.exclusion_reasons == {
        DiagnosticCode.MISSING_REFERENCE_REPLICATE: 1
    }


# --------------------------------------------------- the estimator boundary ---


def test_the_fully_replicate_estimator_declines_rather_than_substituting():
    dataset = ReplicateDataset.build(fully_study())
    assert dataset.design is ReplicateDesign.FULLY_REPLICATE
    assert len(dataset.records) == 6, "the data are structurally valid"

    with pytest.raises(NotEstimable) as exc:
        estimate_reference_variance(dataset)
    assert exc.value.code is DiagnosticCode.ESTIMATOR_NOT_IMPLEMENTED
    assert "mixed model" in str(exc.value)


def test_the_estimators_refuse_each_others_designs():
    partial = ReplicateDataset.build(partial_study())
    full = ReplicateDataset.build(fully_study())

    with pytest.raises(ValueError, match="not interchangeable"):
        PartialReplicateReferenceVarianceEstimator().estimate(full)
    with pytest.raises(ValueError):
        FullyReplicateReferenceVarianceEstimator().estimate(partial)


def test_dispatch_is_by_design_with_no_default():
    assert isinstance(
        estimator_for(ReplicateDesign.PARTIAL_REPLICATE),
        PartialReplicateReferenceVarianceEstimator,
    )
    assert isinstance(
        estimator_for(ReplicateDesign.FULLY_REPLICATE),
        FullyReplicateReferenceVarianceEstimator,
    )


# --------------------------------------------------------------- invariance ---


def _quantities(observations):
    result = estimate_reference_variance(ReplicateDataset.build(observations))
    return (
        result.variance_wr,
        result.swr,
        result.cv_wr,
        result.degrees_of_freedom,
        result.n_subjects,
        result.n_sequences,
    )


def test_shuffling_rows_does_not_change_the_result():
    """The property that makes a result reproducible from a re-exported file."""
    observations = partial_study()
    baseline = _quantities(observations)

    rng = random.Random(20260826)
    for _ in range(25):
        shuffled = observations[:]
        rng.shuffle(shuffled)
        assert _quantities(shuffled) == baseline


def test_renaming_subjects_does_not_change_the_result():
    observations = partial_study()
    baseline = _quantities(observations)

    renamed = [
        ReplicateObservation(
            subject_id=f"ANON-{abs(hash(o.subject_id)) % 100000}",
            sequence=o.sequence,
            period=o.period,
            treatment=o.treatment,
            endpoint=o.endpoint,
            value=o.value,
        )
        for o in observations
    ]
    assert _quantities(renamed) == baseline


def test_reordering_sequence_groups_does_not_change_the_result():
    observations = partial_study()
    baseline = _quantities(observations)

    order = {"RRT": 0, "TRR": 1, "RTR": 2}
    regrouped = sorted(observations, key=lambda o: (order[o.sequence.value], o.subject_id, o.period))
    assert _quantities(regrouped) == baseline


def test_reversing_period_order_within_a_subject_does_not_change_the_result():
    """R1 must come from the period number, not from row position."""
    observations = partial_study()
    baseline = _quantities(observations)
    assert _quantities(list(reversed(observations))) == baseline


def test_scaling_every_value_by_a_constant_leaves_the_variance_alone():
    """A log-scale within-subject variance is invariant to units.

    Reporting AUC in ng·h/mL or µg·h/mL changes every number and must not
    change sWR - the constant cancels in Rij1 - Rij2.
    """
    observations = partial_study()
    baseline = _quantities(observations)

    rescaled = [
        ReplicateObservation(
            o.subject_id, o.sequence, o.period, o.treatment, o.endpoint, o.value * 1000.0
        )
        for o in observations
    ]
    scaled = _quantities(rescaled)
    assert scaled[0] == pytest.approx(baseline[0], rel=1e-12)
    assert scaled[3:] == baseline[3:]


def test_the_summary_ends_where_this_module_ends():
    result = estimate_reference_variance(ReplicateDataset.build(partial_study()))
    text = result.summary()
    assert "NOT COMPUTED IN THIS MODULE" in text
    assert "0.294" in text, "the reader is told where the decision lives"
    assert math.isfinite(result.swr)
