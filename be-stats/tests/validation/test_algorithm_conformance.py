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
#:
#: Cases whose subject is structural rather than a single function map to None
#: and are checked by a dedicated test below.
_RUNNERS = {
    "FDA-HVD-SWITCH-001": fda_hvd_method_for,
    "FDA-HVD-SWR-FORMULA-001": None,
}


def load_cases() -> list[dict]:
    return [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(CASE_DIR.glob("*.json"))
    ]


CASES = load_cases()
IDS = [c["case_id"] for c in CASES]


def _case(case_id: str) -> dict:
    for case in CASES:
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"case {case_id} is missing from {CASE_DIR}")


def test_algorithm_cases_are_present():
    assert CASES, f"no algorithm-conformance cases found in {CASE_DIR}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_states_its_rule_and_its_source(case: dict):
    """A threshold without a section reference is a remembered number."""
    for field in ("case_id", "case_type", "rule", "source"):
        assert field in case, f"{case.get('case_id', '?')} is missing {field}"

    # A case driven by a single engine function must list the branches it
    # expects. A structural case states its expectations under the aspect they
    # belong to, and its own test names them - but it may not have none.
    if _RUNNERS.get(case["case_id"]) is not None:
        assert "expected" in case, f"{case['case_id']} is missing expected"
    else:
        nested = [v for v in case.values() if isinstance(v, dict) and "expected" in v]
        assert nested, (
            f"{case['case_id']} is a structural case and states no expectations "
            "anywhere; a case that asserts nothing is documentation"
        )

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
    if run is None:
        pytest.skip("structural case; checked by its own test below")
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
    if run is None:
        pytest.skip("structural case")
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


def test_the_engine_assigns_r1_and_r2_exactly_as_the_sas_conditions_do():
    """The most directly checkable thing in Appendix G.

    FDA does not describe R1 and R2 in prose - it gives them as SAS conditions
    on sequence and period, for both designs. The engine derives them from the
    sequence name in ascending period order. Those two must agree for all five
    supported sequences, and this is the test that says so.

    Getting it wrong would not raise anything. It would flip the sign of some
    subjects' Dij, which changes nothing on average and everything in the
    deviations, producing a plausible sWR that is simply not the regulator's.
    """
    case = _case("FDA-HVD-SWR-FORMULA-001")
    from be_stats.replicate import parse_sequence

    for row in case["r1_r2_assignment"]["expected"]:
        sequence = parse_sequence(row["sequence"])
        assert sequence.reference_periods() == (
            row["r1_period"],
            row["r2_period"],
        ), row["sequence"]
        assert list(sequence.test_periods()) == row["test_periods"], row["sequence"]


def test_the_engine_uses_the_sequence_count_the_guidance_gives():
    """`m = 3` for the partial replicate, `m = 2` for the fully replicate.

    One formula, two designs. The preceding release had the fully replicate
    estimator decline; this asserts the corrected reading.
    """
    case = _case("FDA-HVD-SWR-FORMULA-001")
    from be_stats.replicate import ReplicateDesign

    assert case["rule"]["one_formula_for_both_designs"] is True
    expected = case["rule"]["m_by_design"]
    assert (
        ReplicateDesign.PARTIAL_REPLICATE.regulatory_sequence_count
        == expected["partial_replicate"]
    )
    assert (
        ReplicateDesign.FULLY_REPLICATE.regulatory_sequence_count
        == expected["fully_replicate"]
    )


def test_m_comes_from_the_design_and_not_from_the_surviving_data():
    """The correction, asserted at the conformance layer.

    Appendix G states `m` per design. An estimator that recomputed it from the
    sequences still holding subjects would silently analyse a depleted
    three-sequence study as a two-sequence one.
    """
    from be_stats.reference_variance import estimator_for
    from be_stats.replicate import ReplicateDesign

    for design in ReplicateDesign:
        estimator = estimator_for(design)
        assert (
            estimator.design.regulatory_sequence_count
            == design.regulatory_sequence_count
        )
    assert ReplicateDesign.PARTIAL_REPLICATE.regulatory_sequence_count == 3
    assert ReplicateDesign.FULLY_REPLICATE.regulatory_sequence_count == 2


def test_both_designs_have_a_working_estimator_now():
    from be_stats.reference_variance import estimator_for
    from be_stats.provenance import ValidationStatus
    from be_stats.replicate import ReplicateDesign

    for design in ReplicateDesign:
        estimator = estimator_for(design)
        assert estimator.design is design
        assert (
            estimator.validation_status
            is ValidationStatus.IMPLEMENTED_UNVALIDATED
        )


def test_the_guidance_contains_no_worked_dataset_and_the_case_says_so():
    """Why tier 1B is still open, recorded where it will be looked for.

    Obtaining the guidance closed tier 1A and could never have closed 1B: the
    document states the algorithm and gives SAS code, and contains no input
    values and no published answer anywhere. Reproducing a regulator's number
    requires a regulator's number, and this document does not have one.
    """
    case = _case("FDA-HVD-SWR-FORMULA-001")
    limitation = case["source"]["limitation"]
    assert "no worked dataset" in limitation.lower()
    assert "1b" in limitation.lower()


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
