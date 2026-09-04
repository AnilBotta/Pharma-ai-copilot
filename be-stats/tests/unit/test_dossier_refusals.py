"""A refusal must be a code, an explanation, and a way out.

Any of the three missing turns a refusal into a dead end, and a dead end is
what makes somebody reach for the number anyway.
"""

from __future__ import annotations

from be_stats.diagnostics import DiagnosticCode
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.refusals import (
    DIAGNOSTIC_FOR,
    REFUSALS,
    RefusalCode,
    refusal,
)


def test_every_refusal_code_has_a_reason():
    """Total over the enum, so a new code cannot ship without one."""
    for code in RefusalCode:
        assert code in REFUSALS, f"{code} has no RefusalReason."


def test_every_refusal_says_what_would_lift_it():
    for code, reason in REFUSALS.items():
        assert reason.summary.strip(), code
        assert reason.lifted_by.strip(), (
            f"{code} does not say what would lift it, which makes it a dead "
            "end rather than an answer."
        )


def test_each_reason_carries_its_own_code():
    for code, reason in REFUSALS.items():
        assert reason.code is code


def test_the_codes_the_release_brief_names_are_present():
    """Named individually so a rename is a visible failure."""
    for name in (
        "APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED",
        "FDA_HVD_DESIGN_REQUIRED",
        "FDA_NTI_FULL_REPLICATE_REQUIRED",
        "EMA_ABEL_CMAX_ONLY",
    ):
        assert hasattr(RefusalCode, name), f"RefusalCode.{name} is missing."


def test_the_partial_replicate_refusal_names_the_evidentiary_reason():
    """Not "unsupported design" - the design is fine, the oracle is missing.

    A refusal that blames the study for an evidentiary gap sends the submitter
    to redesign a trial that was correct.
    """
    reason = refusal(RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED)
    assert "oracle" in reason.summary.lower()
    assert "SAS" in reason.lifted_by
    assert "APPENDIX-C-PARTIAL-ORACLE" in reason.lifted_by


def test_every_diagnostic_correspondence_names_a_real_diagnostic():
    for code, diagnostic in DIAGNOSTIC_FOR.items():
        assert code in REFUSALS
        assert diagnostic in DiagnosticCode


def test_the_known_naming_discrepancy_is_recorded_rather_than_hidden():
    """The diagnostic says NOT_VALIDATED; the canonical status is NOT_IMPLEMENTED.

    Asserted on the VALUES rather than by searching source text for the words -
    a text search would match the paragraph explaining the discrepancy and pass
    whether or not the discrepancy still existed.
    """
    from be_stats.dossier.findings import FINDINGS
    from be_stats.provenance import ValidationStatus

    refusal_name = RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED.value
    diagnostic_name = DIAGNOSTIC_FOR[
        RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED
    ].value
    assert refusal_name != diagnostic_name

    status = CAPABILITY_MATRIX[
        "FDA_REPLICATE_STANDARD_ABE_PARTIAL"
    ].validation_status
    assert status is ValidationStatus.NOT_IMPLEMENTED
    assert refusal_name.endswith("NOT_IMPLEMENTED")
    assert diagnostic_name.endswith("NOT_VALIDATED")

    assert "DOSSIER-001" in FINDINGS, (
        "The discrepancy above must be recorded in the findings register "
        "rather than left to whoever notices it next."
    )


def test_every_capability_refusal_condition_is_a_declared_code():
    for record in CAPABILITY_MATRIX.values():
        for code in record.refusal_conditions:
            assert code in REFUSALS, f"{record.capability_id} cites {code}"


def test_explain_renders_code_and_way_out_together():
    line = refusal(RefusalCode.EMA_ABEL_CMAX_ONLY).explain()
    assert "EMA_ABEL_CMAX_ONLY" in line
    assert "Lifted by" in line
