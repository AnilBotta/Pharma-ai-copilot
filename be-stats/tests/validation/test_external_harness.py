"""The external validation harness, tested without R.

WHAT THESE TESTS ARE FOR

The harness decides what counts as agreement. If it can report PASS for a
comparison that did not happen, or accept a tolerance nobody justified, then
every green report it ever produces is worthless. So the harness itself gets
tested, and it gets tested here - in the ordinary suite, with no R and no
Docker, because that is the environment it has to behave correctly in.

The comparisons against PowerTOST are NOT run here. They need R, they take
minutes, and they belong to the separate `validation-r` job.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

EXTERNAL = Path(__file__).resolve().parents[2] / "validation" / "external"


def _load(name: str):
    """Import a module from validation/external by path.

    It is not a package and deliberately not importable as one: it is
    validation scaffolding beside `be_stats`, not part of it.
    """
    if str(EXTERNAL) not in sys.path:
        sys.path.insert(0, str(EXTERNAL))
    spec = importlib.util.spec_from_file_location(name, EXTERNAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


harness = _load("harness")
simulate = _load("simulate")


# ------------------------------------------------------------ case files ---


def test_every_case_file_loads():
    cases = harness.load_cases()
    assert cases
    assert len({c.case_id for c in cases}) == len(cases)


def test_every_comparison_states_why_its_tolerance_exists():
    """The rule this directory exists to enforce.

    A tolerance without a stated basis is a tolerance chosen by running the
    comparison and widening until it passed.
    """
    for case in harness.load_cases():
        for comparison in case.comparisons:
            assert comparison.tolerance_basis.strip(), (
                f"{case.case_id}/{comparison.quantity}"
            )
            assert len(comparison.tolerance_basis) > 40, (
                f"{case.case_id}/{comparison.quantity}: the basis is too short "
                "to be a reason"
            )


def test_a_case_without_a_tolerance_basis_is_rejected():
    bad = {
        "case_id": "BAD", "title": "t", "method": "m",
        "comparison_kind": "direct", "inputs": {},
        "oracle": {"tool": "PowerTOST", "function": "f"},
        "comparisons": [
            {
                "quantity": "q", "absolute_tolerance": 1.0,
                "relative_tolerance": 1.0, "tolerance_basis": "   ",
            }
        ],
    }
    with pytest.raises(harness.CaseError, match="tolerance_basis"):
        harness.Case.from_dict(bad)


def test_a_case_with_no_comparisons_is_rejected():
    """It would otherwise report PASS having compared nothing."""
    bad = {
        "case_id": "BAD", "title": "t", "method": "m",
        "comparison_kind": "direct", "inputs": {},
        "oracle": {"tool": "PowerTOST", "function": "f"},
        "comparisons": [],
    }
    with pytest.raises(harness.CaseError, match="no comparisons"):
        harness.Case.from_dict(bad)


def test_every_case_names_its_oracle_function():
    """"PowerTOST agrees" is not a claim unless it says which function.

    Similarly named functions do not implement the same procedure -
    `power.RSABE`, `power.NTID` and `power.HVNTID` are three different FDA
    procedures.
    """
    for case in harness.load_cases():
        assert case.oracle["tool"] == "PowerTOST"
        assert case.oracle["function"]
        if case.comparison_kind != harness.COMPARISON_CONSTANT:
            assert case.oracle.get("arguments"), case.case_id


def test_every_case_records_what_it_cannot_establish():
    for case in harness.load_cases():
        assert case.not_cross_checkable, (
            f"{case.case_id} claims no limits, which is itself a claim"
        )


def test_the_phase_one_scenarios_are_present_and_are_the_known_ones():
    """The harness sanity check. If these two do not reproduce, nothing
    downstream is trustworthy whatever it reports."""
    cases = {c.case_id: c for c in harness.load_cases()}
    first = cases["ABE-001-CENTRAL"].inputs
    second = cases["ABE-002-NARROW-LIMITS"].inputs

    assert (first["cv"], first["theta0"], first["target_power"]) == (0.20, 0.95, 0.80)
    assert (second["cv"], second["theta0"]) == (0.125, 0.975)
    assert second["lower_limit"] == 0.90


# --------------------------------------------------- the comparison logic ---


def _case(quantity="q", abs_tol=1e-6, rel_tol=1e-6):
    return harness.Case.from_dict(
        {
            "case_id": "C", "title": "t", "method": "standard_abe",
            "comparison_kind": "direct",
            "inputs": {"role": "central"},
            "oracle": {"tool": "PowerTOST", "function": "f", "arguments": "a"},
            "not_cross_checkable": ["nothing"],
            "comparisons": [
                {
                    "quantity": quantity,
                    "absolute_tolerance": abs_tol,
                    "relative_tolerance": rel_tol,
                    "tolerance_basis": "a reason long enough to be a real one, "
                    "stated here for the test fixture",
                }
            ],
        }
    )


def test_a_missing_r_side_is_skipped_and_never_passed():
    """The single most important behaviour in this module."""
    case = _case()
    results = harness.compare([case], {"C": {"q": 1.0}}, None)

    assert len(results) == 1
    assert results[0].outcome == harness.SKIPPED
    assert results[0].outcome != harness.PASS
    assert "unavailable" in results[0].detail
    # The Python value is still reported, so the run was not wasted.
    assert results[0].python_value == 1.0


def test_agreement_within_tolerance_passes():
    case = _case(abs_tol=1e-6, rel_tol=0.0)
    results = harness.compare([case], {"C": {"q": 1.0}}, {"C": {"q": 1.0 + 5e-7}})
    assert results[0].outcome == harness.PASS
    assert results[0].absolute_difference == pytest.approx(5e-7)


def test_disagreement_beyond_tolerance_fails():
    case = _case(abs_tol=1e-9, rel_tol=1e-9)
    results = harness.compare([case], {"C": {"q": 1.0}}, {"C": {"q": 1.01}})
    assert results[0].outcome == harness.FAIL


def test_a_quantity_the_r_side_did_not_produce_is_an_error_not_a_pass():
    """A comparison with one operand must be loud."""
    case = _case()
    results = harness.compare([case], {"C": {"q": 1.0}}, {"C": {}})
    assert results[0].outcome == harness.ERROR
    assert "R side produced no value" in results[0].detail


def test_a_quantity_the_python_side_did_not_produce_is_an_error():
    case = _case()
    results = harness.compare([case], {"C": {}}, {"C": {"q": 1.0}})
    assert results[0].outcome == harness.ERROR


def test_relative_tolerance_alone_can_carry_agreement():
    case = _case(abs_tol=0.0, rel_tol=1e-3)
    results = harness.compare([case], {"C": {"q": 1000.0}}, {"C": {"q": 1000.5}})
    assert results[0].outcome == harness.PASS


# ------------------------------------------------------ tier-3 policy ---


def test_tier3_is_pending_when_everything_is_skipped():
    """The state this repository is actually in."""
    cases = harness.load_cases()
    results = harness.compare(
        cases, {c.case_id: {} for c in cases}, None
    )
    status = harness.tier3_status(cases, results)

    assert set(status) == set(harness.TIER3_REQUIRED_ROLES)
    for method, detail in status.items():
        assert detail["tier3"] == "PENDING", method
        assert not detail["missing_roles"], (
            f"{method} is missing case roles: {detail['missing_roles']}"
        )


def test_every_required_role_has_a_case():
    """The policy names roles; the cases must supply them.

    A required role with no case would make the policy unsatisfiable and,
    worse, would look like rigour.
    """
    cases = harness.load_cases()
    for method, required in harness.TIER3_REQUIRED_ROLES.items():
        roles = {c.inputs.get("role") for c in cases if c.method == method}
        missing = set(required) - roles
        assert not missing, f"{method}: no case for role(s) {sorted(missing)}"


def test_one_agreeing_case_does_not_make_tier3_passed():
    """The policy exists so a single green row cannot promote a method."""
    cases = [c for c in harness.load_cases() if c.method == "fda_hvd_rsabe"]
    central = next(c for c in cases if c.inputs["role"] == "central")

    python_values = {c.case_id: {} for c in cases}
    r_values = {c.case_id: {} for c in cases}
    for comparison in central.comparisons:
        python_values[central.case_id][comparison.quantity] = 0.5
        r_values[central.case_id][comparison.quantity] = 0.5

    results = harness.compare(cases, python_values, r_values)
    status = harness.tier3_status(cases, results)["fda_hvd_rsabe"]

    assert status["role_status"]["central"] == harness.PASS
    assert status["tier3"] == "PENDING", (
        "one passing role must not promote the method"
    )


def test_a_failing_role_keeps_tier3_pending_even_if_others_pass():
    cases = [c for c in harness.load_cases() if c.method == "standard_abe"]
    python_values, r_values = {}, {}
    for case in cases:
        python_values[case.case_id] = {}
        r_values[case.case_id] = {}
        disagree = case.inputs["role"] == "narrow_limits"
        for comparison in case.comparisons:
            python_values[case.case_id][comparison.quantity] = 1.0
            r_values[case.case_id][comparison.quantity] = 99.0 if disagree else 1.0

    results = harness.compare(cases, python_values, r_values)
    status = harness.tier3_status(cases, results)["standard_abe"]

    assert status["role_status"]["central"] == harness.PASS
    assert status["role_status"]["narrow_limits"] == harness.FAIL
    assert status["tier3"] == "PENDING"


# ----------------------------------------------------- the Python side ---


def test_the_python_side_reproduces_the_phase_one_sample_sizes():
    """Independent of R entirely: the values Phase 1 already established."""
    cases = {c.case_id: c for c in harness.load_cases()}

    first = harness.evaluate_python(cases["ABE-001-CENTRAL"])
    assert first["sample_size"] == 20
    assert first["achieved_power"] == pytest.approx(0.834680, abs=1e-5)

    second = harness.evaluate_python(cases["ABE-002-NARROW-LIMITS"])
    assert second["sample_size"] == 32
    # The exact 1/0.9, not Phase 1's truncated 1.1111 - see the case's
    # tolerance_basis. Asserted tightly, because a loose assertion here is what
    # let the misattribution stand: |0.8002182 - 0.800212| is 6.2e-06, so a
    # 1e-5 tolerance would accept either value and hide which one is produced.
    assert second["achieved_power"] == pytest.approx(0.8002181715, abs=1e-9)


def test_the_truncated_limit_explains_the_phase_one_power_difference():
    """The finding that building this harness produced.

    Phase 1 recorded a 6.0e-06 difference on this scenario and attributed it to
    the non-central t approximation against exact Owen's Q. It is not: that
    case truncates the upper limit to 1.1111, and the truncation dominates.

    Both numbers are computed here so the attribution cannot drift again.
    """
    from be_stats import (
        Citation, Endpoint, Jurisdiction, RegulatoryValue,
        VerificationStatus, power_abe,
    )
    from be_stats.spec import AcceptanceInterval, BeSpec, DrugClass, Method

    citation = Citation(authority="test", document="limit precision")

    def power_at(upper: float) -> float:
        spec = BeSpec(
            method=Method.STANDARD_ABE,
            jurisdiction=Jurisdiction.FDA,
            drug_class=DrugClass.STANDARD,
            endpoint=Endpoint.AUC,
            alpha=0.05,
            acceptance=AcceptanceInterval(
                lower=RegulatoryValue(90.0, citation, VerificationStatus.VERIFIED),
                upper=RegulatoryValue(
                    upper * 100.0, citation, VerificationStatus.VERIFIED
                ),
                basis="limit precision",
            ),
        )
        return power_abe(
            cv_percent=12.5, n_total=32, spec=spec,
            design="2x2", expected_ratio=0.975,
        ).power

    published = 0.800218
    truncated = power_at(1.1111)
    exact = power_at(1.0 / 0.9)

    assert abs(truncated - published) == pytest.approx(6.0e-06, rel=0.05)
    assert abs(exact - published) == pytest.approx(1.7e-07, rel=0.2)

    # The truncation accounts for essentially all of the original difference.
    assert abs(truncated - exact) > 30 * abs(exact - published)


def test_the_python_side_produces_the_constants_the_case_asks_for():
    cases = {c.case_id: c for c in harness.load_cases()}
    values = harness.evaluate_python(cases["CONSTANTS-001-FDA"])

    assert values["hvd_r_const"] == pytest.approx(math.log(1.25) / 0.25, rel=1e-15)
    assert values["hvd_point_estimate_lower"] == 0.8
    assert values["hvd_point_estimate_upper"] == 1.25
    assert values["nti_variance_ratio_upper_limit"] == 2.5


def test_the_swr_switch_is_deliberately_not_compared_against_powertost():
    """PowerTOST's `CVswitch` is a CV; FDA's 0.294 is on the sWR scale.

    They are adjacent quantities on different scales, and conflating them is
    the exact confusion the highly-variable release corrected. So the case
    records it as not cross-checkable rather than comparing them.
    """
    cases = {c.case_id: c for c in harness.load_cases()}
    case = cases["CONSTANTS-001-FDA"]

    compared = {c.quantity for c in case.comparisons}
    assert "hvd_swr_switching_threshold" not in compared

    reasons = " ".join(case.not_cross_checkable)
    assert "CVswitch" in reasons
    assert "different scales" in reasons or "not the same constant" in reasons


# ------------------------------------------------------- the simulator ---


def test_the_simulator_reports_the_components_powertost_reports():
    result = simulate.simulate_scaled_power(
        method="fda_hvd_rsabe", design="2x2x4",
        cv_wr=0.45, cv_wt=0.45, theta0=0.90, n=24, nsims=200, seed=1,
    )
    assert set(result) >= {"p_be_sabec", "p_be_pe", "fraction_below_switch"}
    for key in ("p_be_sabec", "p_be_pe"):
        assert 0.0 <= result[key] <= 1.0


def test_the_simulator_does_not_report_an_overall_p_be():
    """There is no be-stats value for it: the mixed procedure needs the
    unscaled branch, which is not implemented."""
    for method, cv_wt in (("fda_hvd_rsabe", 0.45), ("fda_nti", 0.11)):
        result = simulate.simulate_scaled_power(
            method=method, design="2x2x4",
            cv_wr=0.45 if method == "fda_hvd_rsabe" else 0.10,
            cv_wt=cv_wt, theta0=0.95, n=24, nsims=100, seed=2,
        )
        assert "p_be" not in result


def test_the_nti_simulator_reports_the_variance_ratio_component():
    result = simulate.simulate_scaled_power(
        method="fda_nti", design="2x2x4",
        cv_wr=0.10, cv_wt=0.30, theta0=0.975, n=32, nsims=200, seed=3,
    )
    assert "p_be_sratio" in result
    assert "p_be_pe" not in result, "the PE constraint is an RSABE criterion"
    # A test product three times as variable should fail criterion (c) often.
    assert result["p_be_sratio"] < 0.5


def test_the_between_subject_variance_cannot_affect_the_result():
    """It cancels in every within-subject contrast the procedures use.

    Asserted rather than assumed, because if it did leak in, the comparison
    against PowerTOST would be comparing two different studies.
    """
    baseline = simulate.simulate_scaled_power(
        method="fda_hvd_rsabe", design="2x2x4",
        cv_wr=0.45, cv_wt=0.45, theta0=0.90, n=24, nsims=150, seed=5,
    )
    original = simulate.BETWEEN_SUBJECT_SD
    try:
        simulate.BETWEEN_SUBJECT_SD = original * 10.0
        moved = simulate.simulate_scaled_power(
            method="fda_hvd_rsabe", design="2x2x4",
            cv_wr=0.45, cv_wt=0.45, theta0=0.90, n=24, nsims=150, seed=5,
        )
    finally:
        simulate.BETWEEN_SUBJECT_SD = original

    assert moved["p_be_sabec"] == baseline["p_be_sabec"]
    assert moved["p_be_pe"] == baseline["p_be_pe"]


def test_the_monte_carlo_tolerance_is_derived_not_chosen():
    """4 standard deviations of the difference of two binomial proportions."""
    tolerance = simulate.monte_carlo_tolerance(0.5, 20_000, 100_000)
    expected = 4.0 * math.sqrt(0.25 * (1 / 20_000 + 1 / 100_000))
    assert tolerance == pytest.approx(expected, rel=1e-12)
    assert tolerance == pytest.approx(0.015492, abs=1e-6)

    # Worst case at p = 0.5, so every case file may use that one number.
    for p in (0.05, 0.2, 0.8, 0.95):
        assert simulate.monte_carlo_tolerance(p, 20_000, 100_000) <= tolerance


def test_the_power_cases_use_the_worst_case_tolerance():
    """Every Monte Carlo case carries the derived number, not a rounder one."""
    expected = 4.0 * math.sqrt(0.25 * (1 / 20_000 + 1 / 100_000))
    for case in harness.load_cases():
        if case.comparison_kind != harness.COMPARISON_POWER:
            continue
        assert case.inputs["nsims"] == 20_000
        assert case.inputs["nsims_r"] == 100_000
        for comparison in case.comparisons:
            assert comparison.absolute_tolerance == pytest.approx(
                expected, abs=1e-5
            ), f"{case.case_id}/{comparison.quantity}"


# ----------------------------------------------------------- the report ---


def test_the_report_distinguishes_skipped_from_passed_in_its_counts():
    cases = harness.load_cases()
    results = harness.compare(cases, {c.case_id: {} for c in cases}, None)
    text = harness.render(results, harness.tier3_status(cases, results),
                          harness.environment())

    assert "0 passed" in text
    assert "skipped" in text
    assert "SKIPPED" in text
    assert "PASS" not in text.split("Tier 3 status")[0].replace("passed", "")


def test_the_report_states_the_hierarchy():
    cases = harness.load_cases()
    results = harness.compare(cases, {c.case_id: {} for c in cases}, None)
    text = harness.render(results, harness.tier3_status(cases, results),
                          harness.environment())
    assert "implementation oracle, not a regulatory authority" in text
    assert "FDA guidance remains the source of the rule" in text


def test_the_environment_lockfile_declares_the_pins_and_its_own_status():
    lock = json.loads((EXTERNAL / "environment.lock.json").read_text(encoding="utf-8"))
    assert lock["powertost_version"] == "1.5-7"
    assert lock["r_version"]
    assert lock["r_repository_snapshot"].startswith("https://")
    status = lock["verification_status"]
    assert "NOT YET EXERCISED" in status["state"]
    assert status["what_would_change_this"]
