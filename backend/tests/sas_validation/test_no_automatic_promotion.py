"""An upload is evidence. It is never a validation status.

THE FAILURE THIS PREVENTS

    external_validation_received == true   MUST NOT IMPLY   VALIDATED

It is an easy mistake to make and an expensive one to discover. A pipeline that
promoted a method because SAS agreed would be promoting on: one dataset, one
SAS version, one operator's environment, and a comparison whose tolerances this
application chose. None of those is a regulatory qualification, and the promotion
would be invisible - a status field changing in a table nobody was watching.

So the guard is structural. Nothing in the SAS layer may write a validation
status, and the capability statuses are asserted to be exactly what they were
before this PR.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    manual_execution_integrity,
)

BACKEND = Path(__file__).resolve().parents[2]
SAS_PACKAGE = BACKEND / "app" / "sas_validation"


#: The regulatory status machinery. Importing any of these into the SAS layer
#: is the thing that must not happen.
REGULATORY_STATUS_SYMBOLS = frozenset(
    {"ValidationStatus", "CAPABILITY_VALIDATION", "VALIDATION", "Capability"}
)


def test_the_sas_layer_never_imports_the_regulatory_status_machinery():
    """Checked by import graph and assignment target, not by substring.

    The first version of this test searched for the strings "VALIDATED" and
    "validation_status" anywhere in the package, and failed on two innocent
    things: a docstring explaining that no run status means VALIDATED, and the
    provider method `get_validation_status`, which returns the status of a
    validation RUN and has nothing to do with a method's regulatory standing.

    Those two meanings of "validation status" genuinely coexist here, so a
    substring search cannot separate them. What can: whether the module
    IMPORTS the regulatory enum, and whether it ASSIGNS to an attribute of that
    name. Neither has an innocent reading.
    """
    offenders: list[str] = []

    for module in sorted(SAS_PACKAGE.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in REGULATORY_STATUS_SYMBOLS:
                        offenders.append(f"{module.name} imports {alias.name}")

            # `something.validation_status = ...` - the write that would
            # promote a method.
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "validation_status"
                ):
                    offenders.append(f"{module.name} assigns to .validation_status")

    assert not offenders, offenders


def test_the_sas_layer_never_names_the_capability_table():
    """`CAPABILITY_VALIDATION` has no second meaning, so a plain search works."""
    for module in sorted(SAS_PACKAGE.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        assert "CAPABILITY_VALIDATION" not in source, module.name


def test_the_run_statuses_contain_no_regulatory_verdict():
    """Every state names what happened to a file or a comparison.

    If a status called VALIDATED existed here, some code would eventually set
    it, and something downstream would eventually read it as the regulatory
    fact it is not.
    """
    from app.sas_validation.modes import SASValidationRunStatus

    values = {status.value for status in SASValidationRunStatus}
    assert "validated" not in values
    assert not any("valid" in value for value in values)

    # And the two terminal states are explicitly REVIEWED - a person, not a
    # comparison, is the last thing that happened.
    assert SASValidationRunStatus.REVIEWED_ACCEPTED.is_reviewed
    assert SASValidationRunStatus.REVIEWED_REJECTED.is_reviewed
    assert not SASValidationRunStatus.MATCH.is_reviewed


def test_a_matching_comparison_is_still_not_a_conclusion():
    """The strongest possible SAS result changes nothing on its own."""
    from app.sas_validation.compare import compare
    from app.sas_validation.ingest import ParsedSASResult
    from app.sas_validation.modes import SASValidationRunStatus
    from app.sas_validation.targets import get_target

    parsed = ParsedSASResult(
        estimate_log=0.0223913,
        standard_error=0.0303172,
        denominator_df=19.8906,
        ci_lower_log=-0.0299207,
        ci_upper_log=0.0747033,
        convergence_status="0",
        sas_version="9.4M8",
    )
    report = compare(
        target=get_target("FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II"),
        package_id="p" * 64,
        parsed=parsed,
        engine_result={
            "estimate_log": 0.0223913,
            "standard_error": 0.0303172,
            "denominator_df": 19.8906,
        },
        integrity=SOUND_MANUAL_INTEGRITY,
    )

    assert report.status is SASValidationRunStatus.MATCH

    # A perfect match, and the report still carries no field that could be
    # read as a regulatory conclusion.
    assert not hasattr(report, "validated")
    assert not hasattr(report, "validation_status")
    assert not hasattr(report, "oracle_closed")

    # And it says so, in the report a human reads.
    assert any("does not change" in note for note in report.notes)


def test_oracle_closure_is_a_reviewer_decision_with_a_neutral_default():
    from app.sas_validation.modes import OracleClosureDecision

    assert OracleClosureDecision.NOT_ASSESSED.value == "not_assessed"
    assert {d.value for d in OracleClosureDecision} == {
        "not_assessed",
        "oracle_closure_accepted",
        "oracle_closure_rejected",
    }


def test_the_statistical_capability_statuses_are_untouched_by_this_release():
    """PR #64 is product infrastructure. These must be exactly as they were.

    Asserted here rather than trusted, because this is the PR in which someone
    would be most tempted to move them - the whole point of the feature is to
    obtain the evidence that would eventually justify it.
    """
    from be_stats.provenance import ValidationStatus
    from be_stats.spec import CAPABILITY_VALIDATION, VALIDATION, Capability, Method

    assert (
        CAPABILITY_VALIDATION[Capability.FDA_REPLICATE_STANDARD_ABE_FULL]
        is ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    assert (
        CAPABILITY_VALIDATION[Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL]
        is ValidationStatus.NOT_IMPLEMENTED
    )
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED


def test_the_partial_oracle_finding_still_records_it_as_unready():
    """PR #63's verdict stands until a governed review changes it."""
    import json

    finding = json.loads(
        (
            BACKEND.parent
            / "be-stats/validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.json"
        ).read_text(encoding="utf-8")
    )
    assert finding["partial_oracle_ready"] is False
    assert finding["recommendation"] == "BLOCKED_WITH_PRECISE_REASONS"


def test_the_comparison_module_has_no_write_path_at_all():
    """It computes a report and returns it. It persists nothing.

    A comparison function that could also save its own conclusion is one
    refactor away from saving it somewhere that matters.
    """
    source = (SAS_PACKAGE / "compare.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("execute", "commit", "save", "update", "insert", "write_text"):
        assert forbidden not in called, f"compare.py calls {forbidden}()"

#: A manual upload whose provenance stamps matched. Program execution
#: integrity is UNVERIFIED_MANUAL_EXECUTION and cannot be anything else -
#: `manual_execution_integrity` does not take it as a parameter.
SOUND_MANUAL_INTEGRITY = manual_execution_integrity(
    package=PackageIntegrity.VERIFIED,
    dataset_provenance=DatasetProvenance.MATCH,
    case_stamp=DatasetProvenance.MATCH,
)
