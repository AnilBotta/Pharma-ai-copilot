"""The capability matrix must be complete, and must not restate a status.

The second is the harder property to hold and the more valuable to test. A
matrix that stores its own copy of a validation status looks correct on the day
it is written and disagrees with `spec` the first time somebody promotes
something.
"""

from __future__ import annotations

import pytest

from be_stats.dossier.capabilities import (
    CAPABILITY_MATRIX,
    by_validation_status,
    capabilities_for,
    capability,
    decision_capabilities,
)
from be_stats.dossier.statuses import ImplementationStatus
from be_stats.provenance import ValidationStatus
from be_stats.spec import CAPABILITY_VALIDATION, VALIDATION, Capability, Method


def test_every_production_capability_appears_in_the_matrix():
    """Total coverage over both spec enums, in both directions.

    A method added to the engine without a row here is a capability reaching
    production with no documented status, limitation set or refusal condition -
    which is the failure the whole dossier exists to prevent.
    """
    keys = {record.source_key for record in CAPABILITY_MATRIX.values()}

    missing_methods = set(Method) - keys
    assert not missing_methods, f"Methods with no matrix row: {missing_methods}"

    missing_capabilities = set(Capability) - keys
    assert not missing_capabilities, (
        f"Capabilities with no matrix row: {missing_capabilities}"
    )

    stray = keys - set(Method) - set(Capability)
    assert not stray, f"Matrix rows keyed on something spec does not know: {stray}"


def test_each_source_key_appears_exactly_once():
    keys = [record.source_key for record in CAPABILITY_MATRIX.values()]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, (
        f"Two rows claim the same status source: {duplicates}. One of them "
        "would silently shadow the other in any report grouped by status."
    )


def test_the_matrix_size_is_the_sum_of_the_two_spec_tables():
    assert len(CAPABILITY_MATRIX) == len(VALIDATION) + len(CAPABILITY_VALIDATION)


def test_capability_ids_are_upper_snake_case():
    for capability_id in CAPABILITY_MATRIX:
        assert capability_id == capability_id.upper(), capability_id
        assert " " not in capability_id, capability_id


def test_no_unknown_validation_status_exists():
    """Every status is a member of the declared ladder.

    Stated as a frozen expectation over the ENUM rather than over the matrix,
    so that adding a sixth status to `ValidationStatus` fails here and forces
    somebody to decide how the product should display it - rather than having
    it default into whichever bucket the mapping happened to reach first.
    """
    assert set(ValidationStatus) == {
        ValidationStatus.NOT_IMPLEMENTED,
        ValidationStatus.EXPERIMENTAL,
        ValidationStatus.IMPLEMENTED,
        ValidationStatus.IMPLEMENTED_UNVALIDATED,
        ValidationStatus.VALIDATED,
    }
    for record in CAPABILITY_MATRIX.values():
        assert record.validation_status in ValidationStatus


def test_the_matrix_does_not_restate_statuses(monkeypatch):
    """Mutate `spec` and the matrix must follow.

    This is the test that proves there is no second copy. If a row ever grows
    its own `validation_status` field, this fails - which is the only way to
    catch a duplication that looks perfectly correct on the day it lands.
    """
    record = CAPABILITY_MATRIX["FDA_HVD_RSABE"]
    assert record.validation_status is ValidationStatus.IMPLEMENTED_UNVALIDATED

    patched = dict(VALIDATION)
    patched[Method.FDA_HVD_RSABE] = ValidationStatus.EXPERIMENTAL
    monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)

    assert record.validation_status is ValidationStatus.EXPERIMENTAL
    assert record.implementation_status is ImplementationStatus.IMPLEMENTED


def test_the_matrix_does_not_restate_capability_statuses(monkeypatch):
    record = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    assert record.validation_status is ValidationStatus.NOT_IMPLEMENTED

    patched = dict(CAPABILITY_VALIDATION)
    patched[Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL] = (
        ValidationStatus.IMPLEMENTED
    )
    monkeypatch.setattr("be_stats.dossier.capabilities.CAPABILITY_VALIDATION", patched)

    assert record.validation_status is ValidationStatus.IMPLEMENTED


def test_a_record_carries_no_validation_status_field():
    """The structural half of the test above.

    Reads the dataclass's own field names rather than a source file, so it
    cannot be satisfied by a comment and cannot be fooled by the word
    appearing in a docstring - which is a mistake this repository has made
    more than once with blunt text searches.
    """
    from dataclasses import fields

    from be_stats.dossier.capabilities import CapabilityRecord

    names = {f.name for f in fields(CapabilityRecord)}
    assert "validation_status" not in names, (
        "A stored validation_status is a second copy of a regulatory claim."
    )
    assert "implementation_status" not in names


def test_nothing_not_implemented_claims_to_decide():
    for record in CAPABILITY_MATRIX.values():
        if record.implementation_status is ImplementationStatus.NOT_IMPLEMENTED:
            assert not record.decision_supported, (
                f"{record.capability_id} does not run and is advertised as "
                "producing a verdict."
            )


def test_nothing_not_implemented_is_left_without_a_refusal():
    for record in CAPABILITY_MATRIX.values():
        if record.implementation_status is ImplementationStatus.NOT_IMPLEMENTED:
            assert record.refusal_conditions, (
                f"{record.capability_id} cannot run and has no refusal code, "
                "so a caller gets silence instead of a reason."
            )


def test_every_row_has_a_regulatory_source_with_a_version():
    """An unpinned citation is a promise somebody will remember to check.

    FDA's 2001 and 2026 guidances share a title and disagree, so the version is
    load-bearing rather than decorative.
    """
    for record in CAPABILITY_MATRIX.values():
        assert record.regulatory_source.document, record.capability_id
        assert record.regulatory_source.document_version, (
            f"{record.capability_id} cites {record.regulatory_source.document!r} "
            "with no version."
        )


def test_every_row_records_at_least_one_limitation():
    """Including the validated ones. Especially the validated ones.

    A row with no limitations reads as "nothing to know here", and there is
    always something to know - what data it needs, what design, what the
    evidence does and does not cover.
    """
    for record in CAPABILITY_MATRIX.values():
        assert record.known_limitations, (
            f"{record.capability_id} records no limitations at all."
        )


def test_partial_appendix_c_remains_not_implemented():
    """A pinned expectation, not an incidental one.

    The brief for this release is explicit that partial-replicate Appendix C
    stays where it is until real SAS evidence has been collected and accepted.
    This test is how that survives the next refactor.
    """
    record = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    assert record.validation_status is ValidationStatus.NOT_IMPLEMENTED
    assert record.implementation_status is ImplementationStatus.NOT_IMPLEMENTED
    assert not record.decision_supported


def test_full_and_partial_appendix_c_are_separate_rows():
    """One status cannot describe two situations that differ.

    A single FDA_REPLICATE_STANDARD_ABE row would have to say one thing about
    a design that is supported and one that is not, and whichever it said would
    be wrong about the other.
    """
    full = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_FULL"]
    partial = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    assert full.validation_status is not partial.validation_status
    assert full.design_requirement != partial.design_requirement


def test_no_fda_capability_claims_validated():
    """FDA has published no worked example, so nothing FDA can clear the bar.

    Mirrors the guard in the spec suite from the other side. It caught a real
    promotion attempt once: Appendix C reproduces EMA's published SAS output
    exactly, and that is EMA's authority for FDA's model.
    """
    from be_stats.spec import Jurisdiction

    for record in capabilities_for(Jurisdiction.FDA):
        assert record.validation_status is not ValidationStatus.VALIDATED, (
            f"{record.capability_id} claims VALIDATED. FDA publishes no worked "
            "numerical example of any of these procedures, so the tier-1B bar "
            "cannot currently be met for an FDA capability."
        )


def test_lookup_helpers_agree_with_the_matrix():
    assert capability("EMA_HVD_ABEL").capability_id == "EMA_HVD_ABEL"
    with pytest.raises(KeyError):
        capability("NO_SUCH_CAPABILITY")

    decides = {r.capability_id for r in decision_capabilities()}
    assert "FDA_HVD_RSABE" in decides
    assert "FDA_HVD_REFERENCE_VARIANCE" not in decides

    grouped = by_validation_status()
    assert sum(len(v) for v in grouped.values()) == len(CAPABILITY_MATRIX)
    assert "FDA_REPLICATE_STANDARD_ABE_PARTIAL" in grouped[
        ValidationStatus.NOT_IMPLEMENTED
    ]
