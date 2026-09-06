"""The operator must not be able to read the answer before producing it.

WHAT THIS FILE EXISTS BECAUSE OF

`_assert_neutral` skipped `README.md`. The README rendered every reference
value the target carried, so the operator package shipped the be-stats
candidate 19.8906, ReplicateBE's 22.5403, and a paragraph on which was better
supported - beneath a heading reading "It contains NO expected answer".

Nothing failed, because the one check that could have caught it was told not
to look at that file. An exemption keyed by filename cannot tell the reviewer
who should see a value from the operator who must not, and the two were handed
the same README.

So the audience decides, and these tests hold the line in both directions: the
operator package carries nothing, and the two audiences differ ONLY in the
README.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.sas_validation.package import (
    FORBIDDEN_EXPECTED_VALUES,
    FORBIDDEN_OPERATOR_PHRASES,
    PackageAudience,
    build_package,
)
from app.sas_validation.targets import APPENDIX_C_PARTIAL_EMA_DATASET_II

STAMP = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

OBSERVATIONS = [
    {"subject": "1", "sequence": "TRR", "period": 1, "treatment": "T", "value": 100.0},
    {"subject": "1", "sequence": "TRR", "period": 2, "treatment": "R", "value": 103.0},
    {"subject": "1", "sequence": "TRR", "period": 3, "treatment": "R", "value": 99.0},
    {"subject": "2", "sequence": "RTR", "period": 1, "treatment": "R", "value": 95.0},
    {"subject": "2", "sequence": "RTR", "period": 2, "treatment": "T", "value": 98.0},
    {"subject": "2", "sequence": "RTR", "period": 3, "treatment": "R", "value": 97.0},
]

OPERATOR_FACING = ("dataset.csv", "validate.sas", "model_specification.json",
                   "README.md", "manifest.json")


def build(audience: PackageAudience):
    return build_package(
        target=APPENDIX_C_PARTIAL_EMA_DATASET_II,
        observations=OBSERVATIONS,
        be_stats_version="0.7.0",
        git_sha="test1234",
        generated_at=STAMP,
        audience=audience,
    )


@pytest.fixture(scope="module")
def blinded():
    return build(PackageAudience.OPERATOR_BLINDED)


@pytest.fixture(scope="module")
def internal():
    return build(PackageAudience.INTERNAL_QA)


# ------------------------------------------------------------- A, B, C ---


@pytest.mark.parametrize("forbidden", FORBIDDEN_EXPECTED_VALUES)
def test_no_candidate_value_appears_in_any_operator_file(blinded, forbidden):
    """EVERY file, README and manifest included. No exemption list."""
    for file in blinded.files:
        assert forbidden not in file.content, (
            f"{file.name} ships {forbidden!r} to the SAS operator."
        )


@pytest.mark.parametrize("phrase", FORBIDDEN_OPERATOR_PHRASES)
def test_no_expectation_vocabulary_appears_in_any_operator_file(blinded, phrase):
    """A candidate leaks as a name as easily as it leaks as a number.

    "ReplicateBE says 22.5403" and "ReplicateBE disagrees with us" tell an
    operator the same thing about where to look, and only one contains a
    figure. The next candidate will have a value nobody has hard-coded.
    """
    for file in blinded.files:
        assert phrase not in file.content.lower(), (
            f"{file.name} contains {phrase!r}."
        )


def test_the_operator_readme_names_no_other_engine_and_no_target(blinded):
    readme = blinded.file("README.md").content
    lowered = readme.lower()

    for word in ("be-stats", "julia", "candidate", "we expect", "should match"):
        assert word not in lowered, f"operator README mentions {word!r}"

    # And it says what it is withholding, rather than being quietly silent.
    assert "deliberately not in this package" in lowered
    assert "independently" in lowered


def test_the_operator_readme_carries_the_instructions_an_operator_needs(blinded):
    """Blinding is not the same as being unhelpful."""
    readme = blinded.file("README.md").content
    lowered = readme.lower()

    for needed in (
        "sas/stat",
        "proc mixed",
        "%let packagedir",
        "complete sas log",
        "sas version",
        "date and time",
        "attestation",
    ):
        assert needed in lowered, f"operator README omits {needed!r}"


# ------------------------------------------------------------------ D ---


def test_the_internal_package_may_still_carry_the_candidates(internal):
    """The internal audience exists so the blind does not cost the reviewer.

    If this failed, the blinding would have been implemented by deleting the
    information rather than by scoping who receives it.
    """
    readme = internal.file("README.md").content
    assert "19.8906" in readme
    assert "22.5403" in readme
    assert "INTERNAL QA COPY" in readme


def test_the_internal_package_still_keeps_candidates_out_of_what_sas_reads(internal):
    """The dataset, the program and the specification are never exempt."""
    for name in ("dataset.csv", "validate.sas", "model_specification.json"):
        content = internal.file(name).content
        for forbidden in FORBIDDEN_EXPECTED_VALUES:
            assert forbidden not in content, f"{name} ships {forbidden!r}"


# --------------------------------------------------------------- E, F, G ---


def test_the_two_audiences_ship_identical_statistics(blinded, internal):
    """THE PROPERTY THAT MAKES THE AUDIENCE SAFE.

    If a profile could change the dataset or the model, the blinded run and
    the internal expectation would be answers to different questions - and the
    comparison downstream would be meaningless. Asserted on the BYTES, not on
    a claim that presentation is all that differs.
    """
    for name in ("dataset.csv", "validate.sas", "model_specification.json"):
        assert blinded.file(name).content == internal.file(name).content, name
        assert blinded.file(name).sha256 == internal.file(name).sha256, name


def test_only_the_readme_differs_between_audiences(blinded, internal):
    differing = {
        f.name
        for f in blinded.files
        if f.content != internal.file(f.name).content
    }
    # manifest.json differs too, and must: it records the audience and the
    # README hash, which is what makes the two packages distinguishable.
    assert differing == {"README.md", "manifest.json"}, differing


# ------------------------------------------------------------- H, I, J ---


def test_the_audience_changes_the_package_identity(blinded, internal):
    """Two packages differing only in what a human reads are still two.

    A reviewer holding a package id must be able to tell which one was handed
    out; an id that collapsed the two would make the blind unauditable.
    """
    assert blinded.package_id != internal.package_id
    assert blinded.manifest["audience"] == "operator_blinded"
    assert internal.manifest["audience"] == "internal_qa"
    assert blinded.manifest["readme_sha256"] != internal.manifest["readme_sha256"]


def test_the_manifest_pins_every_byte_handed_over(blinded):
    manifest = json.loads(blinded.file("manifest.json").content)

    for key in (
        "schema",
        "case_id",
        "audience",
        "generated_at",
        "be_stats_version",
        "git_sha",
        "dataset_sha256",
        "program_sha256",
        "model_specification_sha256",
        "readme_sha256",
        "files",
    ):
        assert key in manifest, key

    listed = {f["name"]: f["sha256"] for f in manifest["files"]}
    for file in blinded.files:
        if file.name == "manifest.json":
            continue  # cannot describe itself
        assert listed[file.name] == file.sha256, file.name


def test_changing_any_packaged_file_changes_the_package_id():
    """Immutability, demonstrated rather than asserted.

    A different dataset is a different package. So is a different engine
    version, a different commit, and a different audience.
    """
    base = build(PackageAudience.OPERATOR_BLINDED)

    altered_data = build_package(
        target=APPENDIX_C_PARTIAL_EMA_DATASET_II,
        observations=[*OBSERVATIONS[:-1], {**OBSERVATIONS[-1], "value": 97.5}],
        be_stats_version="0.7.0",
        git_sha="test1234",
        generated_at=STAMP,
        audience=PackageAudience.OPERATOR_BLINDED,
    )
    assert altered_data.package_id != base.package_id

    altered_version = build_package(
        target=APPENDIX_C_PARTIAL_EMA_DATASET_II,
        observations=OBSERVATIONS,
        be_stats_version="0.7.1",
        git_sha="test1234",
        generated_at=STAMP,
        audience=PackageAudience.OPERATOR_BLINDED,
    )
    assert altered_version.package_id != base.package_id

    altered_sha = build_package(
        target=APPENDIX_C_PARTIAL_EMA_DATASET_II,
        observations=OBSERVATIONS,
        be_stats_version="0.7.0",
        git_sha="deadbee",
        generated_at=STAMP,
        audience=PackageAudience.OPERATOR_BLINDED,
    )
    assert altered_sha.package_id != base.package_id


def test_the_same_inputs_reproduce_the_same_package(blinded):
    """The other half of immutability: identity is not a random id."""
    again = build(PackageAudience.OPERATOR_BLINDED)
    assert again.package_id == blinded.package_id
    for file in blinded.files:
        assert again.file(file.name).sha256 == file.sha256, file.name


# ------------------------------------------------- the default is the blind ---


def test_an_unspecified_audience_is_blinded():
    """Fail safe, because the failure mode is silent.

    A caller who has not thought about audience must not be able to hand an
    operator a leading question by omission - which is exactly how the leak
    reached a generated package in the first place.
    """
    default = build_package(
        target=APPENDIX_C_PARTIAL_EMA_DATASET_II,
        observations=OBSERVATIONS,
        be_stats_version="0.7.0",
        git_sha="test1234",
        generated_at=STAMP,
    )
    assert default.manifest["audience"] == "operator_blinded"
    assert default.package_id == build(PackageAudience.OPERATOR_BLINDED).package_id


# ------------------------------------------------------- the check bites ---


@pytest.mark.parametrize(
    "injected",
    ["19.8906", "22.5403", "ReplicateBE", "expected_ci", "candidate_df"],
)
def test_the_neutrality_check_rejects_an_injected_leak(monkeypatch, injected):
    """Mutation, run rather than described.

    The tests above pass on a clean package, which is also what they would do
    if `_assert_neutral` had stopped looking. Each forbidden thing is injected
    into the operator README through the target's own title, and the build
    must refuse.
    """
    import dataclasses

    from app.sas_validation import package as pkg

    poisoned = dataclasses.replace(
        APPENDIX_C_PARTIAL_EMA_DATASET_II,
        title=f"{APPENDIX_C_PARTIAL_EMA_DATASET_II.title} ({injected})",
    )
    with pytest.raises(ValueError, match="contains"):
        pkg.build_package(
            target=poisoned,
            observations=OBSERVATIONS,
            be_stats_version="0.7.0",
            git_sha="test1234",
            generated_at=STAMP,
            audience=PackageAudience.OPERATOR_BLINDED,
        )
