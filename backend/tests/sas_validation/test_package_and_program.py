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
from app.sas_validation.program import (
    DATASET_COLUMNS,
    DERIVED_ANALYSIS_VARIABLE,
    SYNTAX_NORMALIZATIONS,
    UnknownSyntaxNormalization,
    generate_program,
    leading_keyword,
)
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


def test_the_model_semantics_are_preserved_statement_for_statement():
    """The executable program fits the regulator's model, statement for statement.

    NOT a verbatim check any more, and the change is the point. FDA's listing
    prints `CLASSES`; PROC MIXED's documented statement is `CLASS`. A test
    demanding the source text appear verbatim as executable SAS would enforce a
    program that does not run, and the earlier version of this file did exactly
    that - which is how the burden ended up on the customer.

    So each source statement must correspond to exactly one executable
    statement with the SAME operative content: same variables, same options,
    same contrast. Only the leading keyword may differ, and only by an
    allow-listed normalization.
    """
    program = generate_program(
        case_id="X", dataset_filename="dataset.csv", dataset_sha256="0" * 64
    )

    source = [s for s in APPENDIX_C_MODEL.sas if not s.upper().startswith("PROC MIXED")]
    assert len(program.executable_statements) == len(source)

    for original, executable in zip(
        source, program.executable_statements, strict=True
    ):
        original_keyword = leading_keyword(original)
        executable_keyword = leading_keyword(executable)

        # Everything after the keyword is untouched.
        assert original[len(original_keyword) :] == executable[len(executable_keyword) :]

        if original_keyword != executable_keyword:
            applied = {n.identifier for n in program.normalizations_applied}
            match = [
                n
                for n in SYNTAX_NORMALIZATIONS
                if n.source_keyword == original_keyword
                and n.executable_keyword == executable_keyword
            ]
            assert match, f"{original_keyword} -> {executable_keyword} is not allow-listed"
            assert match[0].identifier in applied
            assert match[0].changes_statistical_model is False


def test_classes_to_class_is_the_only_normalization_today():
    """One entry, and a test that notices if a second appears.

    A new normalization is a decision about what may be changed in a
    regulator's model statement. It should require editing this test.
    """
    assert len(SYNTAX_NORMALIZATIONS) == 1
    only = SYNTAX_NORMALIZATIONS[0]
    assert only.identifier == "classes-to-class"
    assert (only.source_keyword, only.executable_keyword) == ("CLASSES", "CLASS")
    assert only.changes_statistical_model is False


def test_the_executable_program_uses_class_and_not_classes():
    """The customer receives runnable SAS, not a document to fix."""
    program = generate_program(
        case_id="X", dataset_filename="dataset.csv", dataset_sha256="0" * 64
    )
    class_statements = [
        s for s in program.executable_statements if leading_keyword(s) == "CLASS"
    ]
    assert class_statements == ["CLASS SEQ SUBJ PER TRT;"]
    assert not any(
        leading_keyword(s) == "CLASSES" for s in program.executable_statements
    )


def test_the_regulatory_source_is_still_preserved_in_provenance():
    """Normalizing for execution must not lose what the regulator wrote."""
    program = generate_program(
        case_id="X", dataset_filename="dataset.csv", dataset_sha256="0" * 64
    )
    assert program.source_statements == tuple(APPENDIX_C_MODEL.sas)
    assert "CLASSES SEQ SUBJ PER TRT;" in program.source_statements
    # And it appears in the program the customer reads, as a source comment.
    assert "/* source: CLASSES SEQ SUBJ PER TRT; */" in program.text


def test_an_unknown_transformation_fails_generation(monkeypatch):
    """A statement needing a change that is not allow-listed must refuse.

    The alternative - emitting it unchanged and hoping - produces a package
    that fails in the customer's session; a general rewriter could change the
    model without anyone noticing. Neither is acceptable, so generation stops.
    """
    import be_stats.replicate_abe as replicate_abe

    from app.sas_validation import program as program_module

    doctored = replicate_abe.APPENDIX_C_MODEL.__class__(
        **{
            **{
                f.name: getattr(replicate_abe.APPENDIX_C_MODEL, f.name)
                for f in replicate_abe.APPENDIX_C_MODEL.__dataclass_fields__.values()
            },
            "sas": ("PROC MIXED;", "PROCEDURE SEQ SUBJ;"),
        }
    )
    monkeypatch.setattr(program_module, "APPENDIX_C_MODEL", doctored)

    with pytest.raises(UnknownSyntaxNormalization, match="PROCEDURE"):
        generate_program(
            case_id="X", dataset_filename="d.csv", dataset_sha256="0" * 64
        )


def test_the_normalization_is_inside_the_program_hash():
    """It is part of the text, so it is part of the hash, so it is evidence."""
    program = generate_program(
        case_id="X", dataset_filename="d.csv", dataset_sha256="0" * 64
    )
    assert "classes-to-class" in program.text
    assert "CLASS SEQ SUBJ PER TRT;" in program.text


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


def test_the_program_can_never_silently_drop_an_observation():
    """No `delete`, anywhere, for any reason.

    The first version contained `if VALUE > 0 then Y = log(VALUE); else
    delete;`, which silently removed non-positive rows. The manifest would then
    count N observations, the CSV would contain N, and SAS would fit fewer -
    with nothing recording the difference. Hashing a dataset does not help if
    the program changes the analysis set after reading it.

    Validity is now established before a package can exist, so the program has
    nothing to drop and no statement that could.
    """
    program = generate_program(
        case_id="X", dataset_filename="d.csv", dataset_sha256="a" * 64
    ).text.lower()

    assert "delete" not in program
    for forbidden in ("where ", "if _n_ <", "trim", "winsor"):
        assert forbidden not in program, forbidden

    # And the defensive check stops rather than continuing on bad data.
    assert "abort cancel" in program
    assert "refusing to continue" in program


# --------------------------------------------------------------- schema ---


def test_the_declared_columns_are_the_actual_csv_header():
    """The manifest's schema must be the file's schema.

    The first version declared (SUBJ, SEQ, PER, TRT, Y) and wrote
    SUBJ,SEQ,PER,TRT,VALUE - so the package advertised a column it did not
    contain, and that false schema went into the hash and the provenance.
    """
    csv_text = make().file("dataset.csv").content
    header = tuple(csv_text.splitlines()[0].split(","))

    assert header == DATASET_COLUMNS

    specification = json.loads(make().file("model_specification.json").content)
    assert tuple(specification["dataset_columns"]) == header


def test_the_derived_analysis_variable_is_not_claimed_to_be_in_the_file():
    """Y is computed inside SAS from VALUE, and the spec says exactly that."""
    specification = json.loads(make().file("model_specification.json").content)

    assert DERIVED_ANALYSIS_VARIABLE not in specification["dataset_columns"]
    assert specification["raw_analysis_input"] == "VALUE"
    assert specification["derived_analysis_variable"] == "Y"
    assert specification["derived_analysis_definition"] == "Y = log(VALUE)"

    header = make().file("dataset.csv").content.splitlines()[0]
    assert "Y" not in header.split(",")


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
