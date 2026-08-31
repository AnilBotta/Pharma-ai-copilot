"""An observation is analysed or the package refuses. It is never dropped.

WHAT WENT WRONG THE FIRST TIME

The generated SAS contained:

    if VALUE > 0 then Y = log(VALUE);
    else delete;

The manifest would claim N observations, dataset.csv would contain N, the hash
would cover all N - and SAS would fit fewer, with nothing anywhere recording
the difference. Hashing the data does not help if the program changes the
analysis set after reading it.

Validity is now established before a package can exist. Every value must be
present, numeric, finite and strictly positive, because the model is fitted on
log(VALUE) and those are the conditions under which that is defined. Anything
else refuses generation and names the rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.sas_validation.dataset import InvalidObservations, validate_observations
from app.sas_validation.package import build_package, write_dataset_csv
from app.sas_validation.targets import get_target

TARGET = get_target("FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II")
STAMP = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

VALID = [
    {"subject": "1", "sequence": "TRR", "period": 1, "treatment": "T", "value": 100.0},
    {"subject": "1", "sequence": "TRR", "period": 2, "treatment": "R", "value": 103.0},
    {"subject": "1", "sequence": "TRR", "period": 3, "treatment": "R", "value": 99.0},
    {"subject": "2", "sequence": "RTR", "period": 1, "treatment": "R", "value": 95.0},
    {"subject": "2", "sequence": "RTR", "period": 2, "treatment": "T", "value": 98.0},
    {"subject": "2", "sequence": "RTR", "period": 3, "treatment": "R", "value": 97.0},
]


def with_value(value: object) -> list[dict]:
    rows = [dict(row) for row in VALID]
    rows[2]["value"] = value
    return rows


def build(rows: list[dict]):
    return build_package(
        target=TARGET,
        observations=rows,
        be_stats_version="0.7.0",
        git_sha="abc1234",
        generated_at=STAMP,
    )


# ------------------------------------------------------------- refusals ---


@pytest.mark.parametrize(
    "bad_value,expected",
    [
        (0.0, "not strictly positive"),
        (-1.0, "not strictly positive"),
        (-0.0001, "not strictly positive"),
        (float("nan"), "NaN"),
        (float("inf"), "infinite"),
        (float("-inf"), "infinite"),
        (None, "value is missing"),
        ("not a number", "not numeric"),
        (True, "boolean"),
    ],
)
def test_an_unanalysable_value_refuses_package_generation(bad_value, expected):
    with pytest.raises(InvalidObservations) as error:
        build(with_value(bad_value))
    assert expected in str(error.value)


def test_a_missing_value_key_refuses_too():
    """Absent is different from None, and both must refuse."""
    rows = [dict(row) for row in VALID]
    del rows[1]["value"]
    with pytest.raises(InvalidObservations, match="value is missing"):
        build(rows)


@pytest.mark.parametrize("field", ["subject", "sequence", "period", "treatment"])
def test_a_missing_structural_field_refuses(field: str):
    """A row with no subject cannot be grouped, so the design is unreconstructable."""
    rows = [dict(row) for row in VALID]
    rows[0][field] = ""
    with pytest.raises(InvalidObservations, match=f"{field} is missing"):
        build(rows)


def test_the_error_names_every_failing_row_not_just_the_first():
    """A customer fixing a dataset should not discover the problems one
    package at a time."""
    rows = [dict(row) for row in VALID]
    rows[0]["value"] = 0.0
    rows[3]["value"] = -2.0
    rows[5]["value"] = float("nan")

    with pytest.raises(InvalidObservations) as error:
        build(rows)

    assert len(error.value.problems) == 3
    message = str(error.value)
    assert "subject 1" in message and "subject 2" in message
    assert "No observation was dropped" in message


def test_the_error_identifies_the_row_the_way_a_reader_would():
    rows = with_value(0.0)
    with pytest.raises(InvalidObservations) as error:
        build(rows)

    problem = error.value.problems[0]
    assert problem.subject == "1"
    assert problem.sequence == "TRR"
    assert problem.period == "3"
    assert problem.treatment == "R"
    assert "not strictly positive" in problem.reason
    assert problem.offending_value == "0.0"


def test_no_package_is_produced_when_generation_refuses():
    """Not "a package minus the bad row" - no package at all."""
    with pytest.raises(InvalidObservations):
        build(with_value(0.0))


# --------------------------------------------------- nothing is ever lost ---


def test_every_supplied_observation_reaches_the_csv():
    """The count in the file equals the count supplied. Every time."""
    package = build(VALID)
    lines = package.file("dataset.csv").content.strip().splitlines()
    assert len(lines) - 1 == len(VALID)
    assert package.manifest["n_observations"] == len(VALID)


@pytest.mark.parametrize("size", [1, 3, 6, 30])
def test_the_row_count_is_preserved_at_any_size(size: int):
    rows = [
        {
            "subject": str(i // 3 + 1),
            "sequence": "TRR",
            "period": i % 3 + 1,
            "treatment": "T" if i % 3 == 0 else "R",
            "value": 90.0 + i,
        }
        for i in range(size)
    ]
    csv_text = write_dataset_csv(rows)
    assert len(csv_text.strip().splitlines()) - 1 == size


def test_a_very_small_positive_value_is_accepted():
    """Strictly positive is the rule, not "comfortably large".

    log is defined there, so refusing it would be this module inventing a
    limit the model does not have.
    """
    rows = with_value(1e-12)
    validate_observations(rows)
    assert build(rows).manifest["n_observations"] == len(rows)
