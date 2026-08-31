"""The package is neutral, immutable, and fits the model it claims to.

Three properties, each of which would be easy to lose and hard to notice:

  NEUTRAL     no candidate answer travels inside it
  IMMUTABLE   its id is a hash of everything that could change the run
  FAITHFUL    the PROC MIXED block is the regulator's, verbatim
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from be_stats.replicate_abe import APPENDIX_C_MODEL

from app.sas_validation.package import (
    FORBIDDEN_EXPECTED_VALUES,
    build_package,
    write_dataset_csv,
)
from app.sas_validation.program import generate_program
from app.sas_validation.targets import EvidenceStatus, get_target

TARGET = get_target("FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II")
STAMP = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

OBSERVATIONS = [
    {"subject": "1", "sequence": "TRR", "period": 1, "treatment": "T", "value": 100.0},
    {"subject": "1", "sequence": "TRR", "period": 2, "treatment": "R", "value": 103.0},
    {"subject": "1", "sequence": "TRR", "period": 3, "treatment": "R", "value": 99.0},
    {"subject": "2", "sequence": "RTR", "period": 1, "treatment": "R", "value": 95.0},
    {"subject": "2", "sequence": "RTR", "period": 2, "treatment": "T", "value": 98.0},
    {"subject": "2", "sequence": "RTR", "period": 3, "treatment": "R", "value": 97.0},
]


def make(**overrides):
    kwargs = dict(
        target=TARGET,
        observations=OBSERVATIONS,
        be_stats_version="0.7.0",
        git_sha="abc1234",
        generated_at=STAMP,
    )
    kwargs.update(overrides)
    return build_package(**kwargs)


# ------------------------------------------------------------- faithful ---


def test_the_model_statements_are_the_regulators_verbatim():
    """Every line of FDA's block appears, in order, unaltered.

    The one exception is `PROC MIXED;`, which must name its input dataset to
    run at all - and the original is preserved beside it as a comment so the
    substitution is visible in the program a customer reads.
    """
    program = generate_program(
        case_id="X", dataset_filename="dataset.csv", dataset_sha256="0" * 64
    ).text

    position = -1
    for statement in APPENDIX_C_MODEL.sas:
        if statement.strip().upper().startswith("PROC MIXED"):
            assert f"/* specification: {statement} */" in program
            continue
        found = program.find(statement)
        assert found > position, f"{statement!r} missing or out of order"
        position = found


def test_the_program_carries_its_citation():
    program = generate_program(
        case_id="X", dataset_filename="dataset.csv", dataset_sha256="0" * 64
    )
    citation = APPENDIX_C_MODEL.citation
    assert citation.authority in program.text
    assert citation.section in program.text
    assert citation.document_version in program.text


def test_the_program_is_byte_identical_for_identical_inputs():
    """Its hash goes in the manifest and is re-derived on upload."""
    first = generate_program(
        case_id="X", dataset_filename="d.csv", dataset_sha256="a" * 64
    )
    second = generate_program(
        case_id="X", dataset_filename="d.csv", dataset_sha256="a" * 64
    )
    assert first.text == second.text


def test_the_program_never_filters_or_transforms_the_data():
    """The only transform is the log the model is defined on.

    A generator that could drop, winsorise or trim rows is a generator that
    could be asked to produce a preferred answer.
    """
    program = generate_program(
        case_id="X", dataset_filename="d.csv", dataset_sha256="a" * 64
    ).text
    for forbidden in ("where ", "if _n_ <", "delete;\n    end", "trim", "winsor"):
        assert forbidden.lower() not in program.lower().replace(
            "if value > 0 then y = log(value);", ""
        ), forbidden


# -------------------------------------------------------------- neutral ---


@pytest.mark.parametrize("forbidden", FORBIDDEN_EXPECTED_VALUES)
def test_no_candidate_answer_reaches_the_files_sas_reads(forbidden: str):
    """19.8906, 22.5403 and 19.603 must not be in the data, program or spec.

    The README prints them WITH their evidence status, because a human should
    see the context. SAS must not.
    """
    package = make()
    for file in package.files:
        if file.name in ("README.md", "manifest.json"):
            continue
        assert forbidden not in file.content, f"{forbidden} found in {file.name}"


def test_the_specification_ships_no_expected_answer():
    specification = json.loads(make().file("model_specification.json").content)
    assert specification["expected_answer"] is None
    assert "denominator_df" not in json.dumps(specification.get("expected_answer"))


def test_the_readme_labels_every_unconfirmed_reference():
    """A reviewer must not have to guess which numbers a regulator published."""
    readme = make().file("README.md").content
    assert "INDEPENDENT CANDIDATE" in readme
    assert "EXTERNAL IMPLEMENTATION" in readme
    assert "REGULATOR PUBLISHED" in readme

    for reference in TARGET.references:
        if reference.status is not EvidenceStatus.REGULATOR_PUBLISHED:
            assert "NOT REGULATOR-CONFIRMED" in reference.note


# ------------------------------------------------------------ immutable ---


def test_the_package_id_is_stable_for_identical_inputs():
    assert make().package_id == make().package_id


def test_row_order_does_not_change_the_package():
    """Same observations, different order, same evidence."""
    assert make().package_id == make(observations=list(reversed(OBSERVATIONS))).package_id


@pytest.mark.parametrize(
    "change",
    [
        {"be_stats_version": "0.7.1"},
        {"git_sha": "def5678"},
        {"observations": OBSERVATIONS[:-1]},
        {"generated_at": datetime(2026, 9, 1, tzinfo=UTC)},
    ],
)
def test_any_material_change_produces_a_new_package_id(change):
    """Never an edited package - a different one.

    Historical evidence must survive the thing that produced it, so there is no
    path that rewrites a package in place.
    """
    assert make().package_id != make(**change).package_id


def test_the_manifest_covers_everything_that_could_change_the_run():
    manifest = make().manifest
    for key in (
        "dataset_sha256",
        "program_sha256",
        "model_specification_sha256",
        "be_stats_version",
        "git_sha",
        "case_id",
    ):
        assert manifest[key], f"manifest is missing {key}"


def test_the_dataset_csv_is_deterministic():
    assert write_dataset_csv(OBSERVATIONS) == write_dataset_csv(
        list(reversed(OBSERVATIONS))
    )
    assert write_dataset_csv(OBSERVATIONS).endswith("\n")
    assert "\r" not in write_dataset_csv(OBSERVATIONS)


def test_the_dataset_round_trips_at_full_precision():
    """A package whose data lost digits would validate the wrong numbers."""
    observations = [
        {
            "subject": "1",
            "sequence": "TRR",
            "period": 1,
            "treatment": "T",
            "value": 1234.5678901234567,
        }
    ]
    assert "1234.5678901234567" in write_dataset_csv(observations)
