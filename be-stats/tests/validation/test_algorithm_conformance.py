"""Tier 1A: does the engine follow the regulator's ALGORITHM?

TWO KINDS OF TIER-1 EVIDENCE, AND THEY ARRIVE SEPARATELY

Statistical review split tier 1 in two, because this package can hold one half
without the other and the difference matters:

    1A  algorithm conformance   the decision rule, thresholds and branch
                                structure are the regulator's
    1B  numerical conformance   a regulator-published worked dataset runs
                                through this engine to the published answer

1A is attestable from the guidance text alone. 1B needs the dataset. Claiming
"tier 1" without saying which would let an attested rule pass for a reproduced
result, and only the second licenses a filing.

This module covers 1A. `test_golden_cases.py` covers tiers 2-4 and records that
1B is still empty.

WHY THESE CASES ARE JSON AND NOT ASSERTIONS

Same reason as the numeric cases: a reviewer must be able to read the rule and
its citation without reading Python, and the file must be usable by whatever
independent implementation checks it next.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from be_stats.spec import Method, fda_hvd_method_for

CASE_DIR = Path(__file__).resolve().parents[2] / "validation" / "phase1" / "algorithm"

#: Which engine entry point answers each case. Explicit rather than resolved by
#: name from the file, so a case file cannot nominate the function that checks
#: it - that would let a case grade its own homework.
_RUNNERS = {
    "FDA-HVD-SWITCH-001": fda_hvd_method_for,
}


def load_cases() -> list[dict]:
    return [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(CASE_DIR.glob("*.json"))
    ]


CASES = load_cases()
IDS = [c["case_id"] for c in CASES]


def test_algorithm_cases_are_present():
    assert CASES, f"no algorithm-conformance cases found in {CASE_DIR}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_states_its_rule_and_its_source(case: dict):
    """A threshold without a section reference is a remembered number."""
    for field in ("case_id", "case_type", "rule", "expected", "source"):
        assert field in case, f"{case.get('case_id', '?')} is missing {field}"

    source = case["source"]
    for field in ("tier", "subtier", "authority", "document", "section"):
        assert source.get(field), f"{case['case_id']} source is missing {field}"
    assert source["tier"] == 1
    assert source["subtier"] == "1A"

    # How it was checked is part of the record, not only whether. Every case
    # here was attested at review rather than transcribed from the PDF by this
    # tooling, and the file must say so.
    assert source.get("verified_by"), f"{case['case_id']} does not say how it was checked"
    assert source.get("limitation"), (
        f"{case['case_id']} must state what its evidence does NOT cover"
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_runner_exists_for_the_case(case: dict):
    assert case["case_id"] in _RUNNERS, (
        f"{case['case_id']} has no registered engine entry point; a case "
        "nobody runs is documentation, not validation"
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_engine_reproduces_every_expected_branch(case: dict):
    run = _RUNNERS[case["case_id"]]
    for row in case["expected"]:
        got = run(row["swr"])
        assert got == Method(row["method"]), (
            f"{case['case_id']} at sWR={row['swr']}: expected "
            f"{row['method']}, got {got}. Case note: {row['why']}"
        )


#: A case file names an exception by string. Resolved through this mapping
#: rather than by `eval`, so a JSON file can never name arbitrary code.
_EXCEPTIONS = {"ValueError": ValueError, "TypeError": TypeError}


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_engine_refuses_what_the_case_says_it_must(case: dict):
    run = _RUNNERS[case["case_id"]]
    for row in case.get("refuses", []):
        expected = _EXCEPTIONS.get(row["raises"])
        assert expected is not None, (
            f"{case['case_id']} names {row['raises']}, which is outside the "
            "permitted vocabulary"
        )
        with pytest.raises(expected):
            run(row["swr"])


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_case_keeps_the_two_adjacent_numbers_apart(case: dict):
    """The correction this case exists to lock down.

    A case whose threshold silently became 0.293560 would still pass every
    branch above, because the branch values would have moved with it. So the
    file's stated threshold is checked against the engine's constant directly.
    """
    if case["case_id"] != "FDA-HVD-SWITCH-001":
        return
    from be_stats.spec import FDA_HVD_CONSTANTS

    assert case["rule"]["threshold"] == (
        FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    )
    assert case["separate_and_not_this_rule"]["classification_cv"] == (
        FDA_HVD_CONSTANTS["classification_cv"].value
    )
    assert case["rule"]["threshold"] != (
        case["separate_and_not_this_rule"]["classification_cv"]
    )


def test_tier_1a_does_not_promote_a_method_to_validated():
    """1A is not 1B, and neither on its own is a submission.

    Attesting that the engine implements FDA's decision rule says nothing about
    whether its arithmetic reproduces a regulator-published result, and the
    method this case describes is not implemented at all yet.
    """
    from be_stats import VALIDATION, ValidationStatus
    from be_stats.spec import Method as M

    assert VALIDATION[M.FDA_HVD_RSABE] is ValidationStatus.NOT_IMPLEMENTED
    for status in VALIDATION.values():
        assert status is not ValidationStatus.VALIDATED
