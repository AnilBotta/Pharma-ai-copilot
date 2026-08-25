"""Golden cases: this engine against independently published results.

A FAILURE HERE IS GRAVER THAN A UNIT FAILURE

A unit test failing means the code stopped doing what we said. One of these
failing means what we said may not match the outside world - which is the only
kind of error that reaches a submission. They are a separate suite so the
distinction survives into CI output.

CASES ARE DATA, NOT CODE

Each case is a JSON file carrying the whole scenario: design, CV, assumed
ratio, alpha, limits, target power, the expected answer, the tolerance, and the
source with its tier. JSON rather than Python so the same file can drive the R
cross-check without being transcribed - transcription is where golden values go
wrong.

WHAT IS AND IS NOT HERE YET

Tier 3 only. The two PowerTOST cases below are an *implementation* oracle: they
show be-stats agrees with an independently written implementation. They are not
regulatory validation, which needs a tier-1 regulator worked example, and the
FDA guidance body has not been obtainable. `test_tier_1_coverage_is_absent`
asserts that gap out loud so it cannot be forgotten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from be_stats import (
    Citation,
    Endpoint,
    Jurisdiction,
    RegulatoryValue,
    VerificationStatus,
    power_abe,
    sample_size_abe,
)
from be_stats.spec import (
    AcceptanceInterval,
    BeSpec,
    DrugClass,
    Method,
)

CASE_DIR = Path(__file__).resolve().parents[2] / "validation" / "phase1" / "cases"


def load_cases() -> list[dict]:
    files = sorted(CASE_DIR.glob("*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


CASES = load_cases()


def spec_from_case(case: dict) -> BeSpec:
    """Build a spec matching the case's stated limits exactly.

    Deliberately does not go through `resolve_be_spec`: a golden case fixes its
    own acceptance limits, and routing them through the jurisdiction rules
    would test the router rather than the arithmetic. Routing has its own suite.
    """
    citation = Citation(
        authority=case["source"].get("package", "reference"),
        document=case["source"].get("citation", ""),
    )
    return BeSpec(
        method=Method.STANDARD_ABE,
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.STANDARD,
        endpoint=Endpoint.AUC,
        alpha=case["inputs"]["alpha"],
        acceptance=AcceptanceInterval(
            lower=RegulatoryValue(
                case["inputs"]["lower_limit"] * 100.0,
                citation,
                VerificationStatus.VERIFIED,
            ),
            upper=RegulatoryValue(
                case["inputs"]["upper_limit"] * 100.0,
                citation,
                VerificationStatus.VERIFIED,
            ),
            basis=case["case_id"],
        ),
    )


def test_cases_are_present():
    assert CASES, f"no golden cases found in {CASE_DIR}"


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case_has_a_complete_scenario(case: dict):
    """A bare expected number is not a golden value.

    Every field below is needed to reproduce the answer. A case missing one of
    them cannot be checked by anyone else, which defeats the purpose.
    """
    for field in ("case_id", "design", "method", "inputs", "expected", "tolerance", "source"):
        assert field in case, f"{case.get('case_id', '?')} is missing {field}"
    for field in ("cv", "true_ratio", "alpha", "target_power", "lower_limit", "upper_limit"):
        assert field in case["inputs"], f"{case['case_id']} inputs missing {field}"
    assert "tier" in case["source"], f"{case['case_id']} source has no tier"
    assert case["source"]["tier"] in (1, 2, 3, 4)


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_sample_size_matches_the_published_value(case: dict):
    """The decisive assertion. Sample size must agree exactly."""
    spec = spec_from_case(case)
    result = sample_size_abe(
        cv_percent=case["inputs"]["cv"] * 100.0,
        spec=spec,
        design=case["design"] if case["design"] != "2x2" else "2x2",
        target_power=case["inputs"]["target_power"],
        expected_ratio=case["inputs"]["true_ratio"],
    )
    expected_n = case["expected"]["mathematical_n"]
    assert abs(result.mathematical_n - expected_n) <= case["tolerance"]["n"], (
        f"{case['case_id']}: expected n={expected_n} from "
        f"{case['source'].get('package')}, got {result.mathematical_n}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_achieved_power_matches_within_the_stated_tolerance(case: dict):
    """Power may differ slightly: exact Owen's Q against the non-central t.

    The tolerance is recorded in the case file and was set from the measured
    difference, not chosen before looking.
    """
    spec = spec_from_case(case)
    achieved = power_abe(
        cv_percent=case["inputs"]["cv"] * 100.0,
        n_total=case["expected"]["mathematical_n"],
        spec=spec,
        design="2x2",
        expected_ratio=case["inputs"]["true_ratio"],
    ).power
    expected = case["expected"]["achieved_power"]
    assert abs(achieved - expected) <= case["tolerance"]["power"], (
        f"{case['case_id']}: power {achieved:.8f} vs published {expected:.8f}"
    )


def test_tier_1_coverage_is_absent_and_says_so():
    """The gap, asserted rather than left to be noticed.

    Everything here is tier 3 - an independent implementation. No
    regulator-published worked example has been reproduced, so no Phase 1
    method may be marked VALIDATED. When a tier-1 case is added this test
    should be replaced by one asserting its presence, and the validation
    statuses raised in the same commit.
    """
    tiers = {c["source"]["tier"] for c in CASES}
    assert 1 not in tiers, (
        "A tier-1 case now exists. Update the validation statuses in spec.py "
        "and replace this test with one asserting tier-1 coverage."
    )


def test_no_phase_1_method_claims_to_be_validated():
    """Follows directly from the test above, and guards the claim itself."""
    from be_stats import VALIDATION, ValidationStatus

    for method, status in VALIDATION.items():
        assert status is not ValidationStatus.VALIDATED, (
            f"{method} claims VALIDATED, but no tier-1 regulator worked "
            "example has been reproduced."
        )
