"""Uploading, parsing and comparing - including all the ways it should refuse.

The happy path is the least interesting part. What matters is that evidence for
a different question is rejected rather than parsed, that a partial result is
called incomplete rather than compared, and that a non-converged fit reaches a
human instead of a tolerance check.
"""

from __future__ import annotations

import math

import pytest

from app.sas_validation.compare import QuantityAgreement, compare, render_report
from app.sas_validation.ingest import (
    ResultParseError,
    ingest_upload,
    parse_result_csv,
)
from app.sas_validation.integrity import (
    DatasetProvenance,
    PackageIntegrity,
    manual_execution_integrity,
)
from app.sas_validation.modes import SASValidationRunStatus
from app.sas_validation.targets import get_target

TARGET = get_target("FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II")
DATASET_HASH = "a" * 64
PROGRAM_HASH = "b" * 64

#: Shaped exactly as `validate.sas` writes it.
GOOD_RESULT = """section,name,value
estimate,T vs. R,0.0223913|0.0303172|19.8906|-0.0299207|0.0747033
covparm,FA(1_1) ,0.2654
covparm,FA(2_1) ,0.1902
covparm,Residual TRT T,0.0089
covparm,Residual TRT R,0.0132
convergence,status,0|Convergence criteria met.
environment,sas_version,9.04.01M8P011823
environment,run_datetime,31AUG2026:12:00:00
"""


def upload(content=GOOD_RESULT, dataset=DATASET_HASH, program=PROGRAM_HASH):
    return ingest_upload(
        content=content,
        declared_dataset_sha256=dataset,
        declared_program_sha256=program,
        package_dataset_sha256=DATASET_HASH,
        package_program_sha256=PROGRAM_HASH,
    )


# ----------------------------------------------------------- refusals ---


def test_a_different_dataset_is_rejected_before_anything_is_parsed():
    """Correct numbers about the wrong data are not weak evidence - they are
    evidence about a different question."""
    outcome = upload(dataset="c" * 64)
    assert outcome.status is SASValidationRunStatus.HASH_MISMATCH
    assert outcome.parsed is None
    assert "different data" in outcome.detail


def test_a_modified_program_is_rejected():
    outcome = upload(program="c" * 64)
    assert outcome.status is SASValidationRunStatus.HASH_MISMATCH
    assert outcome.parsed is None
    assert "modified or different SAS program" in outcome.detail


def test_a_sas_log_is_refused_rather_than_scraped():
    """The supported path is the structured file, and only that.

    A parser that tried to read a log would fail by producing a number, and a
    plausible-looking wrong denominator df is the specific failure this
    programme of work exists to prevent.
    """
    log = "NOTE: PROCEDURE MIXED used (Total process time):\n      real time  0.03 seconds\n"
    outcome = upload(content=log)
    assert outcome.status is SASValidationRunStatus.INCOMPLETE
    assert "does not look like the result file" in outcome.detail


def test_a_partial_result_is_incomplete_not_compared():
    missing_df = GOOD_RESULT.replace("|19.8906|", "|.|")
    outcome = upload(content=missing_df)
    assert outcome.status is SASValidationRunStatus.INCOMPLETE
    assert "denominator df" in outcome.detail


def test_a_non_converged_fit_goes_to_a_human():
    """Numbers from a fit that did not converge must not meet a tolerance."""
    not_converged = GOOD_RESULT.replace(
        "0|Convergence criteria met.", "1|Did not converge."
    )
    outcome = upload(content=not_converged)
    assert outcome.status is SASValidationRunStatus.REVIEW_REQUIRED
    assert outcome.parsed is not None
    assert outcome.parsed.converged is False


def test_an_empty_file_is_an_error_not_an_empty_result():
    with pytest.raises(ResultParseError):
        parse_result_csv("")


def test_an_estimate_row_with_the_wrong_label_is_reported_not_used():
    """PROC MIXED labels the contrast from the regulator's ESTIMATE statement.

    A row labelled something else is a different contrast, and silently taking
    it would compare the wrong quantity.
    """
    wrong = GOOD_RESULT.replace("T vs. R", "R vs. T")
    parsed = parse_result_csv(wrong)
    assert parsed.estimate_log is None
    assert any("R vs. T" in problem for problem in parsed.problems)


# -------------------------------------------------------- the good path ---


def test_the_structured_result_parses_into_every_field():
    parsed = parse_result_csv(GOOD_RESULT)
    assert parsed.estimate_log == pytest.approx(0.0223913)
    assert parsed.standard_error == pytest.approx(0.0303172)
    assert parsed.denominator_df == pytest.approx(19.8906)
    assert parsed.converged is True
    assert parsed.sas_version == "9.04.01M8P011823"
    assert len(parsed.covariance_parameters) == 4
    assert parsed.is_complete

    # And the derived ratio scale, which is what a reviewer reads. Expected
    # values are 100*exp(x) of the log-scale fields above, not retyped from
    # anywhere - the first draft of this test carried a hand-computed 107.7554
    # for the upper limit and was wrong in the fourth decimal.
    assert parsed.estimate_ratio_percent == pytest.approx(
        100.0 * math.exp(0.0223913), abs=1e-6
    )
    assert parsed.ci_lower_percent == pytest.approx(
        100.0 * math.exp(-0.0299207), abs=1e-6
    )
    assert parsed.ci_upper_percent == pytest.approx(
        100.0 * math.exp(0.0747033), abs=1e-6
    )

    # Sanity, at the precision EMA printed: this fixture is the shape of the
    # published Data set II result.
    assert round(parsed.estimate_ratio_percent, 2) == 102.26
    assert round(parsed.ci_lower_percent, 2) == 97.05
    assert round(parsed.ci_upper_percent, 2) == 107.76


# ---------------------------------------------------------- comparison ---


def test_a_disagreement_on_df_alone_is_reported_as_a_mismatch():
    """The case this whole feature exists for.

    Estimate and SE agree between every implementation tried; the denominator
    df is the open question. A single overall boolean would let that hide
    behind two agreements.
    """
    parsed = parse_result_csv(GOOD_RESULT)
    report = compare(
        target=TARGET,
        package_id="p" * 64,
        parsed=parsed,
        engine_result={
            "estimate_log": 0.0223913,
            "standard_error": 0.0303172,
            "denominator_df": 22.5403,
        },
        integrity=SOUND_MANUAL_INTEGRITY,
    )
    assert report.status is SASValidationRunStatus.MISMATCH
    assert report.quantity("estimate_log").agreement is QuantityAgreement.AGREES
    assert report.quantity("standard_error").agreement is QuantityAgreement.AGREES
    assert report.quantity("denominator_df").agreement is QuantityAgreement.DIFFERS


def test_the_engine_declining_to_compute_still_produces_a_usable_report():
    """Today's actual situation for the partial replicate.

    The capability is NOT_IMPLEMENTED and refuses rather than producing an
    unvalidated number. The SAS output is still worth recording beside the
    published reference values - that is the evidence a reviewer needs.
    """
    report = compare(
        target=TARGET,
        package_id="p" * 64,
        parsed=parse_result_csv(GOOD_RESULT),
        engine_result=None,
        integrity=SOUND_MANUAL_INTEGRITY,
    )
    assert report.status is SASValidationRunStatus.REVIEW_REQUIRED
    assert all(
        q.agreement is QuantityAgreement.NOT_COMPARABLE for q in report.quantities
    )
    assert any("NOT_IMPLEMENTED" in note for note in report.notes)


def test_the_report_shows_every_reference_with_its_evidence_status():
    report = compare(
        target=TARGET,
        package_id="p" * 64,
        parsed=parse_result_csv(GOOD_RESULT),
        engine_result=None,
        integrity=SOUND_MANUAL_INTEGRITY,
    )
    rendered = render_report(report)
    assert "regulator_published" in rendered
    assert "independent_candidate" in rendered
    assert "external_implementation" in rendered
    assert "not targets to match" in rendered
    assert "does not change" in rendered


def test_every_tolerance_states_why_it_is_what_it_is():
    """A tolerance without a reason is a number someone will later widen."""
    from app.sas_validation.compare import TOLERANCES

    for quantity, (value, basis) in TOLERANCES.items():
        assert value > 0, quantity
        assert len(basis) > 80, f"{quantity} tolerance has no real justification"

#: A manual upload whose provenance stamps matched. Program execution
#: integrity is UNVERIFIED_MANUAL_EXECUTION and cannot be anything else -
#: `manual_execution_integrity` does not take it as a parameter.
SOUND_MANUAL_INTEGRITY = manual_execution_integrity(
    package=PackageIntegrity.VERIFIED,
    dataset_provenance=DatasetProvenance.MATCH,
    case_stamp=DatasetProvenance.MATCH,
)
