"""The arithmetic of within-reference variability, checked by hand.

WHAT A TEST HERE IS ALLOWED TO USE AS AN EXPECTED VALUE

Not the engine. Every expected number below is either a closed-form identity
restated independently, or an arithmetic chain written out longhand. The
fixture at the bottom is the important one: six subjects, three sequences, and
a variance derived through a different algebraic route than the estimator uses.

That is a MATHEMATICAL fixture, not regulatory validation. It shows the code
computes the formula in the module docstring. It says nothing about whether
that formula is what FDA expects, which needs a regulator-published worked
dataset - see validation/README.md, tier 1B.
"""

from __future__ import annotations

import math

import pytest

from be_stats.diagnostics import DiagnosticCode, Severity
from be_stats.reference_variance import (
    PartialReplicateReferenceVarianceEstimator,
    estimate_reference_variance,
    sequence_mean_differences,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateObservation,
    ReplicateSequence,
    parse_sequence,
    reference_differences,
    treatment_contrasts,
)
from be_stats.study import Treatment

PARTIAL = ("TRR", "RTR", "RRT")


def build(
    rows: list[tuple[str, str, float, float, float]],
    endpoint: str = "AUC",
) -> ReplicateDataset:
    """(subject, sequence, period-1 value, period-2 value, period-3 value).

    The treatment for each period comes from the sequence, never from the
    caller - which is the property under test everywhere else in this file.
    """
    observations = []
    for subject, label, *values in rows:
        sequence = parse_sequence(label)
        for period, value in enumerate(values, start=1):
            observations.append(
                ReplicateObservation(
                    subject_id=subject,
                    sequence=sequence,
                    period=period,
                    treatment=sequence.expected_treatment(period),
                    endpoint=endpoint,
                    value=float(value),
                )
            )
    return ReplicateDataset.build(observations)


# ------------------------------------------------------ log transformation ---


def test_the_engine_logs_the_value_and_the_caller_does_not():
    obs = ReplicateObservation(
        "S1", ReplicateSequence.TRR, 1, Treatment.TEST, "AUC", 100.0
    )
    assert obs.value == 100.0
    assert obs.log_value == pytest.approx(math.log(100.0), rel=1e-15)


def test_a_prelogged_value_would_be_indistinguishable_and_that_is_the_point():
    """Documents why `value` is raw-only rather than a flag-switched field.

    ln(100) is 4.6, a perfectly plausible Cmax. Nothing downstream could detect
    the mistake, so the field admits one interpretation and the transformation
    happens in exactly one place.
    """
    raw = ReplicateObservation(
        "S1", ReplicateSequence.TRR, 1, Treatment.TEST, "AUC", 4.60517
    )
    assert raw.log_value == pytest.approx(math.log(4.60517), rel=1e-12)
    assert raw.log_value != pytest.approx(4.60517, rel=1e-3)


# ------------------------------------------------- reference-pair construction ---


@pytest.mark.parametrize(
    "label,expected_reference_periods,expected_test_periods",
    [
        ("TRR", (2, 3), (1,)),
        ("RTR", (1, 3), (2,)),
        ("RRT", (1, 2), (3,)),
        ("TRTR", (2, 4), (1, 3)),
        ("RTRT", (1, 3), (2, 4)),
    ],
)
def test_reference_periods_come_from_the_sequence_name(
    label, expected_reference_periods, expected_test_periods
):
    sequence = parse_sequence(label)
    assert sequence.reference_periods() == expected_reference_periods
    assert sequence.test_periods() == expected_test_periods


def test_r1_is_the_earlier_period_not_the_earlier_row():
    """The property that makes a variance independent of file sorting.

    RTR carries reference in periods 1 and 3. Feeding period 3 first must not
    make it R1.
    """
    sequence = parse_sequence("RTR")
    forward = [
        ReplicateObservation("S", sequence, p, sequence.expected_treatment(p), "AUC", v)
        for p, v in ((1, 100.0), (2, 90.0), (3, 120.0))
    ]
    reversed_rows = list(reversed(forward))

    a = ReplicateDataset.build(forward).records[0]
    b = ReplicateDataset.build(reversed_rows).records[0]

    assert a.log_reference == b.log_reference
    assert a.log_reference[0] == pytest.approx(math.log(100.0))
    assert a.log_reference[1] == pytest.approx(math.log(120.0))


# --------------------------------------------------------------- Dij, Iij ---


def test_dij_is_r1_minus_r2_on_the_log_scale():
    dataset = build([("S1", "TRR", 105.0, 110.0, 100.0)])
    record = dataset.records[0]
    assert record.reference_difference() == pytest.approx(
        math.log(110.0) - math.log(100.0), rel=1e-15
    )
    # Equivalently the log of the ratio, which is how a reviewer reads it.
    assert record.reference_difference() == pytest.approx(math.log(1.10), rel=1e-12)


def test_iij_is_the_test_minus_the_mean_of_the_two_references():
    dataset = build([("S1", "RRT", 100.0, 121.0, 105.0)])
    record = dataset.records[0]
    expected = math.log(105.0) - (math.log(100.0) + math.log(121.0)) / 2.0
    assert record.treatment_contrast() == pytest.approx(expected, rel=1e-15)


def test_iij_is_exposed_but_nothing_in_this_release_consumes_it():
    """It is built for PR #56 and checkable now, which is the whole reason to
    expose an intermediate rather than discover it later."""
    dataset = build(
        [("A", "TRR", 105.0, 110.0, 100.0), ("B", "RTR", 100.0, 105.0, 110.0)]
    )
    contrasts = treatment_contrasts(dataset)
    assert set(contrasts) == {ReplicateSequence.TRR, ReplicateSequence.RTR}
    assert all(len(v) == 1 for v in contrasts.values())


def test_differences_are_grouped_by_sequence_because_the_mean_is_per_sequence():
    dataset = build(
        [
            ("A", "TRR", 105.0, 110.0, 100.0),
            ("B", "TRR", 105.0, 130.0, 100.0),
            ("C", "RRT", 100.0, 95.0, 105.0),
        ]
    )
    grouped = reference_differences(dataset)
    assert len(grouped[ReplicateSequence.TRR]) == 2
    assert len(grouped[ReplicateSequence.RRT]) == 1
    assert ReplicateSequence.RTR not in grouped


# ---------------------------------------------- the hand-calculated fixture ---
#
# Six subjects, two per sequence, every reference pair expressed as a ratio so
# the arithmetic can be followed without a machine.
#
#   sequence  subject   R1/R2      Dij = ln(R1/R2)
#   TRR       A1        1.10       ln 1.10
#   TRR       A2        1.30       ln 1.30
#   RTR       B1        0.90       ln 0.90
#   RTR       B2        1.20       ln 1.20
#   RRT       C1        1.05       ln 1.05
#   RRT       C2        0.95       ln 0.95
#
#   n = 6 contributing subjects, m = 3 contributing sequences, df = n - m = 3
#
# For a sequence with exactly two observations the deviation sum simplifies:
#
#   (d1 - dbar)^2 + (d2 - dbar)^2  =  (d1 - d2)^2 / 2
#
# which is a DIFFERENT route to the answer than the estimator's (it never forms
# the mean), so agreement is evidence rather than a tautology.
#
#   SS      = [ (ln1.10 - ln1.30)^2 + (ln0.90 - ln1.20)^2
#               + (ln1.05 - ln0.95)^2 ] / 2
#   sWR^2   = SS / (2 * df) = SS / 6

HAND_ROWS = [
    #  subject  sequence  p1     p2     p3
    ("A1", "TRR", 105.0, 110.0, 100.0),   # R1=110, R2=100 -> 1.10
    ("A2", "TRR", 105.0, 130.0, 100.0),   # R1=130, R2=100 -> 1.30
    ("B1", "RTR", 90.0, 105.0, 100.0),    # R1=90,  R2=100 -> 0.90
    ("B2", "RTR", 120.0, 105.0, 100.0),   # R1=120, R2=100 -> 1.20
    ("C1", "RRT", 105.0, 100.0, 105.0),   # R1=105, R2=100 -> 1.05
    ("C2", "RRT", 95.0, 100.0, 105.0),    # R1=95,  R2=100 -> 0.95
]


def _hand_calculated_variance() -> float:
    """Written out longhand, with no call into the estimator."""
    pairs = [(1.10, 1.30), (0.90, 1.20), (1.05, 0.95)]
    ss = sum((math.log(a) - math.log(b)) ** 2 / 2.0 for a, b in pairs)
    n, m = 6, 3
    return ss / (2.0 * (n - m))


def test_the_hand_calculated_fixture_reproduces_every_intermediate():
    dataset = build(HAND_ROWS)

    grouped = reference_differences(dataset)
    assert grouped[ReplicateSequence.TRR] == pytest.approx(
        [math.log(1.10), math.log(1.30)], rel=1e-12
    )
    assert grouped[ReplicateSequence.RTR] == pytest.approx(
        [math.log(0.90), math.log(1.20)], rel=1e-12
    )
    assert grouped[ReplicateSequence.RRT] == pytest.approx(
        [math.log(1.05), math.log(0.95)], rel=1e-12
    )

    means = sequence_mean_differences(dataset)
    assert means[ReplicateSequence.TRR] == pytest.approx(
        (math.log(1.10) + math.log(1.30)) / 2.0, rel=1e-12
    )


def test_the_hand_calculated_fixture_reproduces_the_variance():
    result = estimate_reference_variance(build(HAND_ROWS))

    assert result.estimable
    assert result.n_subjects == 6
    assert result.regulatory_m == 3
    assert result.degrees_of_freedom == 3

    expected_variance = _hand_calculated_variance()
    assert result.variance_wr == pytest.approx(expected_variance, rel=1e-12)
    assert result.swr == pytest.approx(math.sqrt(expected_variance), rel=1e-12)
    assert result.cv_wr == pytest.approx(
        math.sqrt(math.exp(expected_variance) - 1.0), rel=1e-12
    )


def test_the_fixture_is_labelled_a_mathematical_check_not_a_regulatory_one():
    """Guards the claim, not the number.

    The estimator must not advertise itself as validated on the strength of a
    fixture this file wrote.
    """
    from be_stats.provenance import ValidationStatus

    result = estimate_reference_variance(build(HAND_ROWS))
    assert result.validation_status is ValidationStatus.IMPLEMENTED_UNVALIDATED


# ----------------------------------------------------- degrees of freedom ---


def test_degrees_of_freedom_are_n_minus_m_not_twice_that():
    """The most common way to get this formula wrong by a factor of two.

    The 2 in `2(n - m)` converts the variance of a difference into a variance;
    it is not a degrees-of-freedom term.
    """
    result = estimate_reference_variance(build(HAND_ROWS))
    assert result.degrees_of_freedom == 6 - 3
    assert result.degrees_of_freedom != 2 * (6 - 3)


def test_m_is_the_designs_constant_and_is_never_reduced_to_fit():
    """A missing required sequence refuses. It does not become a smaller design.

    An earlier version set `m = len(grouped)` and reported an sWR here, on the
    reasoning that an empty sequence absorbs no degree of freedom. Appendix G
    names `m` as a property of the design - 3 for TRR/RTR/RRT - so a study with
    no RRT subject is not that design, and analysing it as a two-sequence
    design would report an sWR for a study that was not run.
    """
    rows = [
        ("A1", "TRR", 105.0, 110.0, 100.0),
        ("A2", "TRR", 105.0, 130.0, 100.0),
        ("B1", "RTR", 90.0, 105.0, 100.0),
        ("B2", "RTR", 120.0, 105.0, 100.0),
    ]
    result = estimate_reference_variance(build(rows))

    assert not result.estimable
    assert result.variance_wr is None and result.swr is None
    assert result.regulatory_m == 3, "the design's m, not the survivors'"
    assert result.contributing_sequences == 2
    assert result.n_subjects == 4

    fatal = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS
    ]
    assert len(fatal) == 1
    assert fatal[0].severity is Severity.FATAL
    assert fatal[0].context["missing_sequences"] == ["RRT"]
    assert fatal[0].context["regulatory_m"] == 3


def test_a_fully_replicate_design_missing_a_sequence_also_refuses():
    """The same rule with m = 2: one sequence missing leaves no design at all."""
    rows = []
    for k, values in enumerate([[100.0, 110.0, 95.0, 108.0], [101.0, 90.0, 105.0, 99.0]]):
        sequence = parse_sequence("TRTR")
        for period, value in enumerate(values, start=1):
            rows.append(
                ReplicateObservation(
                    f"S{k}", sequence, period,
                    sequence.expected_treatment(period), "AUC", value,
                )
            )
    result = estimate_reference_variance(ReplicateDataset.build(rows))

    assert not result.estimable
    assert result.regulatory_m == 2
    assert result.contributing_sequences == 1
    fatal = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS
    ]
    assert fatal and fatal[0].context["missing_sequences"] == ["RTRT"]


def test_a_sequence_emptied_by_exclusions_is_the_same_refusal():
    """The path that actually happens: subjects drop out, a sequence empties.

    Nothing distinguishes "RRT was never recruited" from "every RRT subject was
    excluded" at the point the estimator runs, and neither is the design.
    """
    rows = [
        ("A1", "TRR", 105.0, 110.0, 100.0),
        ("A2", "TRR", 105.0, 130.0, 100.0),
        ("B1", "RTR", 90.0, 105.0, 100.0),
        ("B2", "RTR", 120.0, 105.0, 100.0),
        # The only RRT subject has a non-positive value and is excluded.
        ("C1", "RRT", 105.0, -1.0, 105.0),
    ]
    result = estimate_reference_variance(build(rows))

    assert not result.estimable
    codes = {d.code for d in result.diagnostics}
    assert DiagnosticCode.NON_POSITIVE_PK_VALUE in codes
    assert DiagnosticCode.REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS in codes


def test_one_subject_per_sequence_leaves_no_degrees_of_freedom():
    rows = [
        ("A1", "TRR", 105.0, 110.0, 100.0),
        ("B1", "RTR", 90.0, 105.0, 100.0),
        ("C1", "RRT", 105.0, 100.0, 105.0),
    ]
    result = estimate_reference_variance(build(rows))

    assert not result.estimable
    assert result.swr is None
    assert result.degrees_of_freedom == 0
    assert any(
        d.code is DiagnosticCode.INSUFFICIENT_REFERENCE_DF
        for d in result.diagnostics
    )


# -------------------------------------------- zero variance is an estimate ---
#
# An earlier version returned non-estimable for sWR^2 = 0, so that nobody could
# read a zero as a perfectly reproducible product. That was a rejection rule
# invented inside a measurement: Appendix G defines a quantity, and for data
# where every subject's two reference observations agree, the quantity is zero.
#
# The estimate is reported, flagged hard, and the judgement left to the places
# entitled to make it.

ZERO_VARIANCE_ROWS = [
    # Structurally impeccable: three sequences, six subjects, no duplicates, no
    # missing periods, every value positive. Each subject's two reference
    # observations simply agree exactly.
    ("A1", "TRR", 105.0, 100.0, 100.0),
    ("A2", "TRR", 106.0, 100.0, 100.0),
    ("B1", "RTR", 100.0, 105.0, 100.0),
    ("B2", "RTR", 100.0, 107.0, 100.0),
    ("C1", "RRT", 100.0, 100.0, 105.0),
    ("C2", "RRT", 100.0, 100.0, 108.0),
]


def test_zero_variance_is_reported_as_the_estimate_it_is():
    result = estimate_reference_variance(build(ZERO_VARIANCE_ROWS))

    assert result.estimable, "the quantity exists; it is zero"
    assert result.variance_wr == 0.0
    assert result.swr == 0.0
    assert result.cv_wr == 0.0
    assert result.degrees_of_freedom == 3


def test_zero_variance_carries_a_data_quality_diagnostic():
    """The number is reported AND the reader is told to look at the dataset."""
    result = estimate_reference_variance(build(ZERO_VARIANCE_ROWS))

    zero = [
        d for d in result.diagnostics
        if d.code is DiagnosticCode.ZERO_REFERENCE_VARIANCE
    ]
    assert len(zero) == 1
    assert zero[0].severity is Severity.DATA_QUALITY
    assert "duplicated rows" in zero[0].detail
    # Not fatal: nothing was refused and nothing was excluded.
    assert not any(d.severity is Severity.FATAL for d in result.diagnostics)


def test_zero_variance_is_not_the_same_condition_as_malformed_data():
    """The distinction the correction turns on.

    Structurally valid references that happen to agree give an estimate plus a
    data-quality flag. Duplicated subject-period rows are a data-integrity
    problem, refused on their own evidence at dataset validation, and they
    never reach the estimator at all.
    """
    from be_stats.replicate import ReplicateDataset, ReplicateObservation

    valid = estimate_reference_variance(build(ZERO_VARIANCE_ROWS))
    assert valid.estimable
    assert valid.subjects_excluded == 0

    rows = []
    for subject, label, *values in ZERO_VARIANCE_ROWS:
        sequence = parse_sequence(label)
        for period, value in enumerate(values, start=1):
            rows.append(
                ReplicateObservation(
                    subject, sequence, period,
                    sequence.expected_treatment(period), "AUC", float(value),
                )
            )
    # One subject gets a second row for period 2 - malformed, not degenerate.
    rows.append(
        ReplicateObservation(
            "A1", parse_sequence("TRR"), 2,
            Treatment.REFERENCE, "AUC", 100.0,
        )
    )
    malformed = estimate_reference_variance(ReplicateDataset.build(rows))

    assert malformed.subjects_excluded == 1
    codes = {d.code for d in malformed.diagnostics}
    assert DiagnosticCode.DUPLICATE_SUBJECT_PERIOD in codes
    # The two conditions are reported by different codes, which is the point:
    # a report can act on one without acting on the other.
    assert DiagnosticCode.DUPLICATE_SUBJECT_PERIOD not in {
        d.code for d in valid.diagnostics
    }


def test_a_constant_nonzero_difference_also_gives_zero_variance():
    """Deviations drive the estimate, not the differences themselves.

    Every subject having the same non-zero D means zero within-sequence spread.
    Same arithmetic result, same treatment: reported and flagged.
    """
    rows = [
        ("A1", "TRR", 105.0, 110.0, 100.0),
        ("A2", "TRR", 106.0, 110.0, 100.0),
        ("B1", "RTR", 110.0, 105.0, 100.0),
        ("B2", "RTR", 110.0, 107.0, 100.0),
        ("C1", "RRT", 110.0, 100.0, 105.0),
        ("C2", "RRT", 110.0, 100.0, 108.0),
    ]
    result = estimate_reference_variance(build(rows))

    assert result.estimable
    assert result.variance_wr == 0.0
    assert any(
        d.code is DiagnosticCode.ZERO_REFERENCE_VARIANCE for d in result.diagnostics
    )


def test_the_estimator_does_not_decide_what_zero_means():
    """The separation the correction restores.

    sWR = 0 is below FDA's 0.294, so the method selection in a later release
    routes it to ordinary average BE - whose own analysis already refuses a
    degenerate within-subject variance on its own grounds. Two independent
    checks, each on its own evidence, rather than this estimator guessing.
    """
    from be_stats.spec import Method, fda_hvd_method_for

    result = estimate_reference_variance(build(ZERO_VARIANCE_ROWS))
    # Stated here only to show where the decision goes; the estimator itself
    # cannot import this function - test_no_be_decision_in_this_release.py.
    assert fda_hvd_method_for(result.swr) is Method.STANDARD_ABE


def test_near_zero_variance_estimates_without_the_flag():
    """The flag is for EXACT zero, which is what indicates duplicated data.

    A tiny but non-zero variance is an ordinary, if implausible, estimate and
    carries no data-quality diagnostic. No tolerance is applied in either
    direction - there is no number here to justify.
    """
    rows = [
        ("A1", "TRR", 105.0, 100.000001, 100.0),
        ("A2", "TRR", 105.0, 100.000002, 100.0),
        ("B1", "RTR", 100.000001, 105.0, 100.0),
        ("B2", "RTR", 100.000003, 105.0, 100.0),
        ("C1", "RRT", 100.000002, 100.0, 105.0),
        ("C2", "RRT", 100.000004, 100.0, 105.0),
    ]
    result = estimate_reference_variance(build(rows))

    assert result.estimable
    assert result.variance_wr > 0.0
    assert result.swr < 1e-6
    assert not any(
        d.code is DiagnosticCode.ZERO_REFERENCE_VARIANCE
        for d in result.diagnostics
    )


def test_the_estimator_cannot_produce_a_negative_variance():
    """Stated as a property rather than tested by contrivance.

    The numerator is a sum of squares and the denominator is positive whenever
    df >= 1, so no input reaches a negative estimate. There is therefore no
    clamping rule and no numerical tolerance in this estimator - if one ever
    appears, it is covering a defect rather than rounding.
    """
    estimator = PartialReplicateReferenceVarianceEstimator()
    for rows in (
        HAND_ROWS,
        [
            ("A1", "TRR", 1e-6, 1e-6, 5e-7),
            ("A2", "TRR", 1e9, 1e9, 3e8),
            ("B1", "RTR", 1e-3, 1.0, 7e-4),
            ("B2", "RTR", 5e5, 1.0, 1e5),
        ],
    ):
        result = estimator.estimate(build(rows))
        if result.estimable:
            assert result.variance_wr > 0.0


# ---------------------------------------------------- CVwR conversion ---


def test_cv_wr_uses_the_single_canonical_conversion():
    from be_stats.conversions import log_sd_to_cv

    result = estimate_reference_variance(build(HAND_ROWS))
    assert result.cv_wr == pytest.approx(log_sd_to_cv(result.swr), rel=1e-15)
    assert result.cv_wr_percent == pytest.approx(100.0 * result.cv_wr, rel=1e-15)


def test_cv_wr_and_swr_are_not_the_same_number():
    """The Phase-1 confusion, restated where it would next appear.

    A CVwR of 30% is not an sWR of 0.30, and the gap is what the FDA switching
    rule is applied to.
    """
    result = estimate_reference_variance(build(HAND_ROWS))
    assert result.cv_wr != pytest.approx(result.swr, rel=1e-9)
    assert result.cv_wr > result.swr, "expm1 exceeds its argument"
