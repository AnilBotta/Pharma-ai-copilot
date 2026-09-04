"""EMA ABEL against the regulator's own published numbers — tier 1B.

WHY THIS FILE IS THE MOST IMPORTANT ONE FOR THIS METHOD

Every other check in the package is either a unit test (does the code do what
the docstring says) or tier 3 (does an independent implementation agree). This
one is different: EMA published two replicate-design data sets WITH their
results, and a table of widened limits. Reproducing those is evidence that the
number this package computes is the number the regulator computed — the tier-1B
evidence a VALIDATED promotion requires, and the kind FDA HVD still lacks.

Required is not sufficient. Neither tier alone establishes VALIDATED status or
submission suitability: the release gate also requires a pinned regulatory
source, no disqualifying finding or blocker, and an explicitly reviewed
transition. Reproducing EMA's numbers is what makes a promotion possible, not
what performs one.

Sources, both read at the cited version:

    EMA, Guideline on the Investigation of Bioequivalence,
    CPMP/EWP/QWP/1401/98 Rev. 1, section 4.1.10 — the limits table.

    EMA/618604/2008 Rev. 13, Questions & Answers ... Pharmacokinetics Working
    Party — Method A, the reference-only CVwR model, Data set I and Data set II
    with published results, and the raw data in the annex.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from be_stats.ema_hvd import (
    EmaReplicateDataset,
    ema_abel_limits,
    estimate_reference_variability,
    estimate_treatment_effect,
)
from be_stats.replicate import (
    ReplicateObservation,
    parse_sequence,
    parse_treatment,
)
from be_stats.spec import EMA_HVD_CONSTANTS, ema_abel_cap_computed

CASES = Path(__file__).resolve().parents[2] / "validation" / "ema" / "cases"
DATASETS = json.loads(
    (CASES / "ema_pkwp_qa_datasets.json").read_text(encoding="utf-8")
)

#: Sequence coding differs between the two annexed data sets and both are
#: transcribed exactly as printed. Data set I uses letters, where A is the TEST
#: and B the reference — so ABAB is TRTR, which is worth stating because the
#: opposite reading is the obvious guess and would invert the result.
SEQUENCE_CODES = {
    "ABAB": "TRTR",
    "BABA": "RTRT",
    "1": "TRR",
    "2": "RTR",
    "3": "RRT",
}

#: What EMA printed. Point estimates and intervals are Method A, "guideline
#: recommended"; the CV is the Model A/B column of the section 3.4 table.
PUBLISHED = {
    "data_set_i": {
        "point_estimate": 115.66,
        "ci": (107.11, 124.89),
        "cv_wr_percent": 47.0,
        "n_subjects": 77,
        "n_observations": 298,
        "incomplete_subjects": 8,
        "design": "fully_replicate",
    },
    "data_set_ii": {
        "point_estimate": 102.26,
        "ci": (97.32, 107.46),
        "cv_wr_percent": 11.2,
        "n_subjects": 24,
        "n_observations": 72,
        "incomplete_subjects": 0,
        "design": "partial_replicate",
    },
}

#: Section 4.1.10's own table: CV%, lower, upper.
LIMITS_TABLE = (
    (30, 80.00, 125.00),
    (35, 77.23, 129.48),
    (40, 74.62, 134.02),
    (45, 72.15, 138.59),
    (50, 69.84, 143.19),
)


def observations(name: str) -> list[ReplicateObservation]:
    return [
        ReplicateObservation(
            subject_id=str(row["subject"]),
            sequence=parse_sequence(SEQUENCE_CODES[row["sequence"]]),
            period=row["period"],
            treatment=parse_treatment(row["formulation"]),
            endpoint="Cmax",
            value=row["value"],
        )
        for row in DATASETS[name]
    ]


# ------------------------------------------------------ the transcription ---


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_the_transcribed_annex_matches_its_own_printed_logarithms(name):
    """Each annex row carries both the value and the log EMA printed.

    They are redundant, which is the point: if the transcription had dropped a
    digit, the two would disagree. 5e-7 is the rounding the document applied to
    the log column.
    """
    for row in DATASETS[name]:
        assert math.log(row["value"]) == pytest.approx(
            row["log_value"], abs=5e-7
        ), row


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_the_dataset_has_the_shape_ema_describes(name):
    published = PUBLISHED[name]
    dataset = EmaReplicateDataset.build(observations(name))

    assert str(dataset.design) == published["design"]
    assert len(dataset.observations) == published["n_observations"]
    assert len(dataset.subjects) == published["n_subjects"]
    # Nothing may be silently dropped: EMA's result includes every subject.
    assert len(dataset.subjects_received) == published["n_subjects"]

    incomplete = sum(
        1
        for d in dataset.diagnostics
        if d.code.value == "MISSING_PERIOD"
    )
    assert incomplete == published["incomplete_subjects"]


# --------------------------------------------------------------- tier 1B ---


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_method_a_reproduces_emas_published_point_estimate_and_interval(name):
    """The tier-1B claim, for the treatment comparison.

    Tolerance is 0.005 percentage points, which is half of the last digit EMA
    printed. It is a rounding bound, not a fitted one: EMA published two
    decimals, so agreement to two decimals is the strongest statement the
    published figures can support.
    """
    published = PUBLISHED[name]
    effect = estimate_treatment_effect(
        EmaReplicateDataset.build(observations(name))
    )

    assert effect.geometric_mean_ratio_percent == pytest.approx(
        published["point_estimate"], abs=0.005
    )
    assert effect.ci_lower_percent == pytest.approx(published["ci"][0], abs=0.005)
    assert effect.ci_upper_percent == pytest.approx(published["ci"][1], abs=0.005)


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_the_reference_only_model_reproduces_emas_published_cvwr(name):
    """EMA's preferred CVwR estimator, against the Model A/B column.

    Published to one decimal, so the tolerance is 0.05 percentage points.
    """
    published = PUBLISHED[name]
    variability = estimate_reference_variability(
        EmaReplicateDataset.build(observations(name))
    )
    assert variability.cv_wr_percent == pytest.approx(
        published["cv_wr_percent"], abs=0.05
    )
    assert variability.swr > 0.0
    assert variability.degrees_of_freedom > 0


def test_the_unbalanced_dataset_keeps_its_incomplete_subjects():
    """The difference between EMA's inclusion rule and FDA's, made concrete.

    `ReplicateDataset` drops a subject missing a reference replicate, which is
    right for FDA's sWR and wrong here. Data set I has eight incomplete
    subjects and EMA's published result can only be reproduced by keeping them,
    so this is not a preference — it is what makes the number correct.
    """
    from be_stats.replicate import ReplicateDataset

    rows = observations("data_set_i")
    ema = EmaReplicateDataset.build(rows)
    fda = ReplicateDataset.build(rows)

    assert len(ema.subjects) == 77
    assert len(fda.records) < 77, (
        "if FDA's builder stopped excluding, this test no longer proves "
        "anything and the two rules would have silently merged"
    )
    assert len(fda.subjects_excluded) > 0


def test_the_guideline_limits_table_reproduces_row_for_row():
    """Section 4.1.10's own worked table — the second piece of tier 1B.

    Compared against the RAW limits, because the table is a table of the
    formula. The final row is where the cap begins to bind; that is asserted
    separately in `test_the_cap_binds_at_the_stated_pair`.
    """
    for cv_percent, published_lower, published_upper in LIMITS_TABLE:
        swr = math.sqrt(math.log1p((cv_percent / 100.0) ** 2))
        limits = ema_abel_limits(swr)
        assert limits.raw_lower_percent == pytest.approx(
            published_lower, abs=0.005
        ), cv_percent
        assert limits.raw_upper_percent == pytest.approx(
            published_upper, abs=0.005
        ), cv_percent


def test_at_thirty_percent_the_widened_limits_are_the_conventional_ones():
    """Which is why a strict `>30%` leaves no gap.

    At exactly CVwR = 30% the formula gives 80.0030 - 124.9953, i.e. the
    conventional range to the precision EMA prints. So a study at the boundary
    is not disadvantaged by being excluded from widening — there is nothing to
    widen. The rule's strictness and its continuity are the same fact.
    """
    limits = ema_abel_limits(math.sqrt(math.log1p(0.30**2)))
    assert limits.raw_lower_percent == pytest.approx(80.00, abs=0.005)
    assert limits.raw_upper_percent == pytest.approx(125.00, abs=0.005)


def test_the_stated_cap_and_the_computed_cap_agree_to_published_precision():
    """VAL-EMA-ABEL-002, asserted rather than assumed.

    EMA states 69.84 - 143.19; the formula at CVwR = 50% gives
    69.83678 - 143.19102. The stated pair is what `ema_abel_limits` applies.
    This test is the evidence that the two are the same number printed to
    different precision, which is what makes applying the stated one safe.
    """
    computed_lower, computed_upper = ema_abel_cap_computed()
    stated_lower = EMA_HVD_CONSTANTS["cap_lower_percent"].value
    stated_upper = EMA_HVD_CONSTANTS["cap_upper_percent"].value

    assert round(computed_lower, 2) == stated_lower
    assert round(computed_upper, 2) == stated_upper

    # And the divergence is the size the finding records.
    assert stated_lower - computed_lower == pytest.approx(0.00322, abs=1e-5)
    assert computed_upper - stated_upper == pytest.approx(0.00102, abs=1e-5)
