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
    "FDA-HVD-RSABE-CRITERION-001": None,
    "FDA-NTI-CRITERIA-001": None,
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
        assert _states_expectations(case), (
            f"{case['case_id']} is a structural case and states no expectations "
            "anywhere; a case that asserts nothing is documentation"
        )


def _states_expectations(node: object) -> bool:
    """Does an `expected` block appear anywhere in this case?

    Recursive because a structural case groups its expectations under whatever
    aspect they belong to, at whatever depth reads best - the criterion case
    puts them under `criteria.A` and `criteria.B`. A one-level check would pass
    that case only by accident of nesting.
    """
    if isinstance(node, dict):
        if node.get("expected"):
            return True
        return any(_states_expectations(v) for v in node.values())
    if isinstance(node, list):
        return any(_states_expectations(v) for v in node)
    return False


def _assert_source_is_complete(case: dict) -> None:
    """Every field a tier-1A citation needs, checked on one case.

    A HELPER RATHER THAN INLINE ASSERTIONS, FOR ONE REASON

    `test_the_source_check_fails_when_the_metadata_is_corrupted` calls it with
    deliberately broken metadata and requires it to raise. A check nobody has
    ever seen fail is a check nobody has evidence works - which is precisely
    the state these assertions were in, unreachable, for three releases.

    THESE ASSERTIONS WERE DEAD FROM 0.4.0 UNTIL NOW

    They were the tail of `test_case_states_its_rule_and_its_source`. In
    `8ffe4f2` the helper `_states_expectations` was inserted between that
    test's expectations block and this tail, which left them stranded inside
    the new function AFTER its `return False`. Python is happy to parse
    unreachable code, pytest reported the test as passing, and no tool in the
    suite looked. Nothing failed, because nothing ran.
    """
    source = case["source"]
    for field in ("tier", "subtier", "authority", "document", "section"):
        assert source.get(field), f"{case['case_id']} source is missing {field}"
    assert source["tier"] == 1, (
        f"{case['case_id']} is in the tier-1A module with tier "
        f"{source['tier']!r}"
    )
    assert source["subtier"] == "1A", (
        f"{case['case_id']} claims subtier {source['subtier']!r}. 1A is "
        "algorithm and decision-rule conformance; 1B is reproduction of "
        "regulator-published numerical output. Tier 1B is REQUIRED numerical "
        "evidence for a VALIDATED promotion, and neither tier alone "
        "establishes VALIDATED status or submission suitability - the release "
        "gate additionally requires a pinned regulatory source, no "
        "disqualifying blocker or finding, and an explicitly reviewed "
        "transition."
    )

    # How it was checked is part of the record, not only whether. Every case
    # here was attested at review rather than transcribed from the PDF by this
    # tooling, and the file must say so.
    assert source.get("verified_by"), f"{case['case_id']} does not say how it was checked"
    assert source.get("limitation"), (
        f"{case['case_id']} must state what its evidence does NOT cover"
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_source_is_complete_and_correctly_tiered(case: dict):
    """The restored check, now in a test of its own.

    Kept separate from `test_case_states_its_rule_and_its_source` rather than
    folded back into it. They answer different questions - does the case state
    a rule, and can a reviewer find the words that rule came from - and a
    parameterised test stops at its first failing assertion, so combining them
    means a missing `section` hides behind a missing `expected`.
    """
    _assert_source_is_complete(case)


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


def test_the_engine_reproduces_the_criterion_boundaries_the_case_states():
    """Both Appendix G conditions, driven from the case file rather than from
    numbers repeated in a test."""
    from be_stats.hvd import PointEstimateConstraint
    from be_stats.spec import FDA_HVD_CONSTANTS
    from tests.unit.test_rsabe_criterion import make_criterion  # noqa: PLC0415

    case = _case("FDA-HVD-RSABE-CRITERION-001")

    for row in case["criteria"]["A"]["expected"]:
        criterion = make_criterion(
            estimate=0.05, standard_error=0.04,
            ci_lower=-0.02, ci_upper=0.12, s2wr=0.2, df_d=20,
            upper_confidence_bound=row["upper_bound"],
        )
        assert criterion.passes is row["passes"], row

    for row in case["criteria"]["B"]["expected"]:
        constraint = PointEstimateConstraint(
            geometric_mean_ratio=row["ratio"],
            lower_limit=FDA_HVD_CONSTANTS["point_estimate_lower"].value,
            upper_limit=FDA_HVD_CONSTANTS["point_estimate_upper"].value,
        )
        assert constraint.passes is row["passes"], row


def test_the_engine_requires_both_criteria_as_the_case_states():
    from be_stats.hvd import PointEstimateConstraint, RsabeResult
    from tests.unit.test_rsabe_criterion import make_criterion  # noqa: PLC0415

    case = _case("FDA-HVD-RSABE-CRITERION-001")
    for row in case["criteria"]["conjunction"]["expected"]:
        result = RsabeResult(
            scaled_criterion=make_criterion(
                estimate=0.05, standard_error=0.04,
                ci_lower=-0.02, ci_upper=0.12, s2wr=0.2, df_d=20,
                upper_confidence_bound=-0.01 if row["A"] else 0.01,
            ),
            point_estimate_constraint=PointEstimateConstraint(
                geometric_mean_ratio=1.0 if row["B"] else 1.4,
                lower_limit=0.8000,
                upper_limit=1.2500,
            ),
            reference_variance=None,  # type: ignore[arg-type]
            treatment_contrast=None,  # type: ignore[arg-type]
        )
        assert result.passes is row["overall"], row


def test_no_external_numerical_oracle_has_been_run_and_the_case_says_so():
    """Tier 3 is empty for RSABE, and that is recorded rather than implied.

    PowerTOST would be a reasonable implementation oracle. R is not available
    in this environment, so no cross-implementation check has been performed on
    the criterion - only on the Phase-1 power and sample size.
    """
    case = _case("FDA-HVD-RSABE-CRITERION-001")
    limitation = case["source"]["limitation"].lower()
    assert "no external numerical oracle" in limitation
    assert "powertost" in limitation


def test_the_nti_case_drives_all_three_criteria_and_their_conjunction():
    """Every boundary and every combination, read from the case file."""
    from be_stats.howe import HoweUpperBound
    from be_stats.nti import (
        FdaNtiResult,
        NtiScaledMeanCriterion,
        NtiUnscaledAbeCriterion,
        NtiVariabilityRatioCriterion,
    )
    from be_stats.replicate import ReplicateDesign
    from be_stats.spec import fda_nti_theta

    case = _case("FDA-NTI-CRITERIA-001")

    def scaled(passes: bool | float) -> NtiScaledMeanCriterion:
        bound = passes if isinstance(passes, float) else (-0.01 if passes else 0.01)
        return NtiScaledMeanCriterion(
            bound=HoweUpperBound(
                x=0.001, bound_x=0.01, y=-0.02, bound_y=-0.013,
                theta=fda_nti_theta(), reference_variance=0.018,
                reference_variance_df=22, upper_confidence_bound=bound,
            ),
            sigma_w0=0.10, delta=1.0 / 0.9,
            estimate=0.03, standard_error=0.02, ci_lower=-0.01, ci_upper=0.07,
        )

    for row in case["criteria"]["a"]["expected"]:
        assert scaled(float(row["upper_bound"])).passes is row["passes"], row

    for row in case["criteria"]["b"]["expected"]:
        criterion = NtiUnscaledAbeCriterion(
            lower_limit_percent=case["constants"]["unscaled_lower_percent"],
            upper_limit_percent=case["constants"]["unscaled_upper_percent"],
            computed=True,
            reason="from case",
            ci_lower_percent=row["ci_lower_percent"],
            ci_upper_percent=row["ci_upper_percent"],
        )
        assert criterion.passes is row["passes"], row

    for row in case["criteria"]["c"]["expected"]:
        criterion = NtiVariabilityRatioCriterion(
            swt=0.2, swr=0.15, ratio=1.33, df_test=22, df_reference=22,
            ci_lower=0.9, ci_upper=row["ci_upper"],
            limit=case["constants"]["variance_ratio_upper_limit"],
        )
        assert criterion.passes is row["passes"], row

    for row in case["criteria"]["conjunction"]["expected"]:
        result = FdaNtiResult(
            endpoint="AUC",
            design=ReplicateDesign.FULLY_REPLICATE,
            scaled_mean_criterion=scaled(row["a"]),
            unscaled_abe_criterion=NtiUnscaledAbeCriterion(
                80.0, 125.0, computed=True, reason="",
                ci_lower_percent=92.0 if row["b"] else 74.0,
                ci_upper_percent=118.0,
            ),
            variability_ratio_criterion=NtiVariabilityRatioCriterion(
                swt=0.2, swr=0.15, ratio=1.33, df_test=22, df_reference=22,
                ci_lower=0.9, ci_upper=2.0 if row["c"] else 3.1, limit=2.5,
            ),
            reference_variance=None,  # type: ignore[arg-type]
            test_variance=None,  # type: ignore[arg-type]
            treatment_contrast=None,
            decided=True,
        )
        assert result.passes is row["overall"], row


def test_the_nti_case_records_the_delta_precision_discrepancy():
    """The three metadata fields, and the measurement behind them.

    Classified as a PRECISION DISCREPANCY between a stated constant and an
    example-code approximation - not as a contradiction, and not as something
    affecting the algorithm, which is identical either way.
    """
    from be_stats.spec import (
        FDA_NTI_CONSTANTS,
        FDA_NTI_SAS_EXAMPLE_DELTA,
        fda_nti_theta,
        fda_nti_theta_sas_example,
    )

    case = _case("FDA-NTI-CRITERIA-001")
    record = case["constants"]["delta_precision_discrepancy"]

    assert record["normative_constant_source"] == "Appendix F prose — Delta = 1/0.9"
    assert record["example_code_literal"] == "Appendix F SAS — 1.11111"
    assert record["implementation_choice"] == "use normative 1/0.9"

    assert "precision discrepancy" in record["classification"]
    assert "NOT the guidance contradicting itself" in record["not_a_contradiction"]
    assert "does not affect the algorithm" in record["not_a_contradiction"]

    # The engine agrees with what the file records.
    assert FDA_NTI_CONSTANTS["delta"].value == 1.0 / 0.9
    assert FDA_NTI_SAS_EXAMPLE_DELTA.value == 1.11111

    theta_regulatory = fda_nti_theta()
    theta_sas_example = fda_nti_theta_sas_example()
    assert str(theta_regulatory) in record["theta_regulatory"]
    assert str(theta_sas_example) in record["theta_sas_example"]

    measured = abs(theta_regulatory - theta_sas_example) / theta_regulatory
    assert measured == pytest.approx(
        record["relative_difference_in_theta"], rel=0.01
    )


def test_the_nti_case_records_that_swt_is_an_interpretation():
    """Appendix F states the closed form for sWR only."""
    case = _case("FDA-NTI-CRITERIA-001")
    assert case["test_variance"]["guidance_states_it"] is False
    assert "symmetric reading" in case["test_variance"]["interpretation_note"]
    assert "sWT is an interpretation" in case["source"]["limitation"]


def test_the_nti_case_forbids_the_ema_narrowed_interval():
    case = _case("FDA-NTI-CRITERIA-001")
    assert case["constants"]["unscaled_lower_percent"] == 80.00
    assert case["constants"]["unscaled_upper_percent"] == 125.00
    assert "90.00-111.11" in case["criteria"]["b"]["not_the_ema_interval"]


def test_the_two_appendices_were_compared_line_by_line_before_sharing():
    """The evidence for one shared Howe helper, in the case file.

    Every SAS line matches but `theta`, which is why the helper takes theta as
    an argument and knows nothing about drug class.
    """
    case = _case("FDA-NTI-CRITERIA-001")
    evidence = case["howe_comparison"]["evidence"]
    differing = [pair for pair in evidence if pair[0] != pair[1]]
    assert len(differing) == 1
    assert "theta" in differing[0][0] and "theta" in differing[0][1]
    assert "1.11111" in differing[0][0], "Appendix F"
    assert "1.25" in differing[0][1], "Appendix G"
    assert "mode flag" in case["howe_comparison"]["consequence"]

    # The Appendix F side of that line is the EXAMPLE literal. The engine
    # decides with the prose constant, so the SAS line and the implementation
    # legitimately differ here - which is the precision discrepancy recorded
    # separately, not a conformance failure.
    record = case["constants"]["delta_precision_discrepancy"]
    assert record["implementation_choice"] == "use normative 1/0.9"


def test_the_source_check_fails_when_the_metadata_is_corrupted():
    """A check nobody has seen fail is a check nobody has evidence works.

    Every field is broken in turn, on a copy of a real case, and each must
    raise. Restoring an assertion that cannot fail would restore the appearance
    of coverage and none of the coverage - which is the state this PR exists to
    end, so proving the restored check bites is the point rather than a
    flourish.
    """
    import copy

    original = _case("FDA-HVD-SWITCH-001")
    _assert_source_is_complete(original)  # the unmodified case passes

    corruptions: list[tuple[str, object]] = [
        ("tier", 2),
        ("subtier", "1B"),
        ("authority", ""),
        ("document", ""),
        ("section", ""),
        ("verified_by", ""),
        ("limitation", ""),
    ]

    for field, broken in corruptions:
        case = copy.deepcopy(original)
        case["source"][field] = broken
        with pytest.raises(AssertionError):
            _assert_source_is_complete(case)

    for field in ("tier", "subtier", "authority", "document", "section",
                  "verified_by", "limitation"):
        case = copy.deepcopy(original)
        del case["source"][field]
        with pytest.raises((AssertionError, KeyError)):
            _assert_source_is_complete(case)


def test_no_module_in_this_package_has_unreachable_statements():
    """The defect class, caught structurally rather than by review.

    A statement after an unconditional `return` or `raise` parses, imports and
    reports green. These assertions sat behind one for three releases while the
    module they belong to was cited as tier-1A evidence.

    An AST walk over source AND tests: a dead assertion in a test is silent
    lost coverage, and a dead statement in `src` is a branch somebody believes
    exists. `ruff` catches neither by default in this repository - the F401 and
    F821 it reported here were symptoms, and nothing failed the build on them.
    """
    import ast

    package_root = Path(__file__).resolve().parents[2]
    terminal = (ast.Return, ast.Raise, ast.Continue, ast.Break)
    offenders: list[str] = []

    scanned = 0
    for path in sorted(package_root.glob("**/*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as error:
            # A module that will not parse is a real problem and must fail
            # here - but as a named finding rather than as a bare SyntaxError
            # from inside a test about something else. On Windows the usual
            # cause is a UTF-8 BOM written by PowerShell's default encoding.
            offenders.append(
                f"{path.relative_to(package_root)}: does not parse "
                f"({error.msg} at line {error.lineno})"
            )
            continue
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            for index, statement in enumerate(body[:-1]):
                if isinstance(statement, terminal):
                    dead = body[index + 1]
                    offenders.append(
                        f"{path.relative_to(package_root)}:{dead.lineno} "
                        f"(unreachable after {type(statement).__name__} on "
                        f"line {statement.lineno})"
                    )
                    break

    assert scanned > 20, (
        f"only {scanned} modules scanned; the glob has stopped matching and "
        "this guard would pass vacuously"
    )
    assert not offenders, (
        "Unreachable statements found. Code after a terminal statement never "
        f"runs, and an assertion there provides no coverage: {offenders}"
    )


def test_tier_1a_does_not_promote_a_method_to_validated():
    """1A is not 1B, and neither on its own is a submission.

    Attesting that the engine implements FDA's algorithm says nothing about
    whether its arithmetic reproduces a regulator-published result. The method
    is implemented now and still not VALIDATED, which is the distinction this
    test exists for - it was much weaker when the method was merely absent.
    """
    from be_stats import VALIDATION, ValidationStatus
    from be_stats.spec import Method as M

    assert VALIDATION[M.FDA_HVD_RSABE] is (
        ValidationStatus.IMPLEMENTED_UNVALIDATED
    )
    for status in VALIDATION.values():
        assert status is not ValidationStatus.VALIDATED
