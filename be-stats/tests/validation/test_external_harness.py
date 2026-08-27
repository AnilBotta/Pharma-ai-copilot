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
    """Without an R environment, no method may be promoted.

    This is what a local run produces. CI has since gone green and marks all
    three PASSED; here there is no R, and the absence must not read as
    agreement.
    """
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
        experiment=simulate.SCALED_CRITERION_ISOLATED,
    )
    assert set(result) >= {"p_be_sabec", "p_be_pe", "p_below_switch"}
    for key in ("p_be_sabec", "p_be_pe", "p_below_switch"):
        assert 0.0 <= result[key] <= 1.0


def test_an_rsabe_case_must_ask_for_the_isolated_scaled_criterion():
    """VAL-FDA-HVD-001, guarded so it cannot recur silently.

    Under `regulator = "FDA"` PowerTOST reports the MIXED decision as
    `p(BE-sABEc)`, and this simulator reports the scaled criterion alone. The
    two are different quantities, they agree wherever little falls below the
    switch, and the mismatch passed the declared tolerance - so nothing
    downstream would have caught it. Refusing is the only place it can be
    caught cheaply.
    """
    for experiment in (None, simulate.FDA_MIXED_PROCEDURE, "anything_else"):
        with pytest.raises(ValueError, match="VAL-FDA-HVD-001"):
            simulate.simulate_scaled_power(
                method="fda_hvd_rsabe", design="2x2x4",
                cv_wr=0.45, cv_wt=0.45, theta0=0.90, n=24, nsims=10, seed=1,
                experiment=experiment,
            )


def test_the_simulator_does_not_report_an_overall_p_be():
    """There is no be-stats value for it: the mixed procedure needs the
    unscaled branch, which is not implemented."""
    for method, cv_wt in (("fda_hvd_rsabe", 0.45), ("fda_nti", 0.11)):
        result = simulate.simulate_scaled_power(
            method=method, design="2x2x4",
            cv_wr=0.45 if method == "fda_hvd_rsabe" else 0.10,
            cv_wt=cv_wt, theta0=0.95, n=24, nsims=100, seed=2,
            experiment=(
                simulate.SCALED_CRITERION_ISOLATED
                if method == "fda_hvd_rsabe"
                else None
            ),
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
        experiment=simulate.SCALED_CRITERION_ISOLATED,
    )
    original = simulate.BETWEEN_SUBJECT_SD
    try:
        simulate.BETWEEN_SUBJECT_SD = original * 10.0
        moved = simulate.simulate_scaled_power(
            method="fda_hvd_rsabe", design="2x2x4",
            cv_wr=0.45, cv_wt=0.45, theta0=0.90, n=24, nsims=150, seed=5,
            experiment=simulate.SCALED_CRITERION_ISOLATED,
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
    """Every Monte Carlo tolerance is the derived number for ITS OWN counts.

    Three rules, and each case must land on whichever applies to it. The point
    is not that they are all the same number - RSABE-004 runs a larger oracle
    and an exact comparator, so it is not - but that every one of them is
    reproducible from the case's own inputs by a formula fixed in advance.
    """
    for case in harness.load_cases():
        if case.comparison_kind != harness.COMPARISON_POWER:
            continue
        n_python = case.inputs["nsims"]
        n_r = case.inputs["nsims_r"]
        assert n_python == 20_000
        for comparison in case.comparisons:
            label = f"{case.case_id}/{comparison.quantity}"
            if comparison.r_value_is_exact:
                # Only the Python side carries sampling error.
                expected = 4.0 * math.sqrt(0.25 / n_python)
            else:
                expected = 4.0 * math.sqrt(0.25 * (1 / n_python + 1 / n_r))
            assert comparison.absolute_tolerance == pytest.approx(
                expected, abs=1e-5
            ), label


def test_the_resolved_findings_tolerance_was_not_tightened_afterwards():
    """VAL-FDA-HVD-001 was a mismatch of quantities, not of tolerances.

    The case that raised it keeps the 0.01549 derived before the first run.
    Narrowing it now - when the comparison agrees and the narrower value would
    still pass - is exactly how a tolerance stops being a pre-declared bound
    and becomes a description of what happened to be observed.
    """
    case = next(
        c for c in harness.load_cases() if c.case_id == "RSABE-002-BOUNDARY-NEAR"
    )
    sabec = next(c for c in case.comparisons if c.quantity == "p_be_sabec")
    assert sabec.absolute_tolerance == pytest.approx(0.01549, abs=1e-6)
    assert "UNCHANGED FROM PR #58" in sabec.tolerance_basis


# ----------------------------------------------------------- the report ---


def test_a_monte_carlo_comparison_reports_how_many_sigmas_apart_it_is():
    """A difference inside the tolerance can still be too big for chance.

    The declared tolerance is evaluated at the worst case p = 0.5, which is a
    legitimate pre-declared bound and is wider than a comparison at extreme p
    deserves. The sigma figure says how far apart two estimates are in units of
    THEIR OWN sampling error.
    """
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_POWER
    )
    quantity = case.comparisons[0].quantity

    results = harness.compare(
        [case],
        {case.case_id: {quantity: 0.87055}},
        {case.case_id: {quantity: 0.85817}},
    )
    assert results[0].outcome == harness.PASS
    assert results[0].monte_carlo_sigmas == pytest.approx(4.61, abs=0.05)
    assert results[0].is_finding


def test_the_sigma_bands_classify_but_never_gate():
    """Three bands, and none of them changes an outcome.

    A single threshold at 4 answered "is this a finding" as a yes or no. The
    bands say how close to the line a comparison sits, which is the difference
    between "look at this" and "this is fine" - without giving anyone a new
    number to tune.
    """
    assert harness.sigma_band(None) is None
    assert harness.sigma_band(0.19) == harness.SIGMA_COMPATIBLE
    assert harness.sigma_band(2.99) == harness.SIGMA_COMPATIBLE
    assert harness.sigma_band(3.01) == harness.SIGMA_WORTH_REVIEW
    assert harness.sigma_band(4.00) == harness.SIGMA_WORTH_REVIEW
    assert harness.sigma_band(4.61) == harness.SIGMA_IS_FINDING

    # Only the top band is a finding, and a finding is still a PASS.
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_POWER
    )
    quantity = case.comparisons[0].quantity
    for python_value, expected_band in (
        (0.87104, harness.SIGMA_COMPATIBLE),
        (0.85817, harness.SIGMA_IS_FINDING),
    ):
        results = harness.compare(
            [case],
            {case.case_id: {quantity: python_value}},
            {case.case_id: {quantity: 0.87055}},
        )
        assert results[0].outcome == harness.PASS
        assert results[0].band == expected_band
        assert results[0].is_finding == (expected_band == harness.SIGMA_IS_FINDING)


def test_the_report_tallies_the_bands():
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_POWER
    )
    quantity = case.comparisons[0].quantity
    results = harness.compare(
        [case],
        {case.case_id: {quantity: 0.87055}},
        {case.case_id: {quantity: 0.87104}},
    )
    text = harness.render(results, {}, harness.environment())
    assert "Monte Carlo distance:" in text
    assert "1 compatible" in text
    assert "no band changes pass or fail" in text


def test_a_closed_form_comparison_has_no_sigma():
    """There is no sampling error to measure against."""
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_DIRECT
    )
    results = harness.compare(
        [case],
        {case.case_id: {"sample_size": 20.0, "achieved_power": 0.83}},
        {case.case_id: {"sample_size": 20.0, "achieved_power": 0.83}},
    )
    for result in results:
        assert result.monte_carlo_sigmas is None
        assert not result.is_finding


def test_an_ordinary_monte_carlo_agreement_is_not_a_finding():
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_POWER
    )
    quantity = case.comparisons[0].quantity
    results = harness.compare(
        [case],
        {case.case_id: {quantity: 0.8163}},
        {case.case_id: {quantity: 0.81351}},
    )
    assert results[0].outcome == harness.PASS
    assert results[0].monte_carlo_sigmas < harness.SIGMA_FINDING
    assert not results[0].is_finding


def test_a_finding_is_shown_loudly_in_the_report():
    """It passed, and the report must not let that be the whole story."""
    case = next(
        c for c in harness.load_cases()
        if c.comparison_kind == harness.COMPARISON_POWER
    )
    quantity = case.comparisons[0].quantity
    results = harness.compare(
        [case],
        {case.case_id: {quantity: 0.87055}},
        {case.case_id: {quantity: 0.85817}},
    )
    text = harness.render(results, {}, harness.environment())

    assert "FINDING" in text
    assert "4.61 sigma" in text
    assert "must not be treated as noise" in text


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

    # The oracle is enforced; transitive versions are recorded, not pinned.
    assert lock["enforced"] == {"PowerTOST": "1.5-7"}
    assert "jsonlite" in lock["recorded"]

    status = lock["verification_status"]
    assert "GREEN" in status["state"]
    assert status["what_would_change_this"]
    assert len(status["history"]) >= 3, (
        "three build attempts; the lockfile must say what happened in each"
    )
    # The versions came from a run, not from someone typing them.
    assert lock["recorded"]["PowerTOST"] == "1.5.7"
    assert "green CI run" in lock["recorded"]["_source"]


def test_the_boundary_near_finding_is_recorded_not_buried():
    """A comparison that passed and should not simply be forgotten.

    `RSABE-002-BOUNDARY-NEAR/p_be_sabec` agreed within the declared tolerance
    at 4.61 standard errors. It is the one comparison sampling error does not
    explain, and the documentation has to carry it or it disappears the moment
    the report is regenerated.
    """
    lock = json.loads((EXTERNAL / "environment.lock.json").read_text(encoding="utf-8"))
    assert "FINDING" in lock["verification_status"]["detail"]
    assert "4.61" in lock["verification_status"]["detail"]

    readme = (EXTERNAL / "README.md").read_text(encoding="utf-8")
    assert "RSABE-002-BOUNDARY-NEAR" in readme
    assert "4.61" in readme
    assert "was not tightened" in readme, (
        "the README must say the tolerance was not adjusted after the fact"
    )


def test_the_r_install_does_not_pull_suggests():
    """The bug the first CI build found, guarded so it cannot come back.

    `install.packages(..., dependencies = TRUE)` also installs Suggests.
    PowerTOST suggests `emmeans`, whose chain reaches `s2`, which needs Abseil
    C++ and cmake. The build spent three minutes failing on a geospatial
    library that nothing here uses.
    """
    script = (EXTERNAL / "install_r_packages.R").read_text(encoding="utf-8")

    assert 'dependencies = c("Depends", "Imports")' in script
    assert "dependencies = TRUE" not in script

    # And only the two packages `run_powertost.R` actually calls are installed
    # by name, so a future addition is a deliberate edit.
    assert 'direct <- c("PowerTOST", "jsonlite")' in script

    r_side = (EXTERNAL / "run_powertost.R").read_text(encoding="utf-8")
    for package in ("jsonlite", "PowerTOST"):
        assert f"library({package})" in r_side


def test_the_r_side_reports_the_versions_it_actually_resolved():
    """The lockfile says what was asked for; the run must say what ran."""
    r_side = (EXTERNAL / "run_powertost.R").read_text(encoding="utf-8")
    assert "r_packages_resolved" in r_side
    assert "packageVersion" in r_side


# ---------------------------------------------------- validation findings ---

FINDINGS = Path(__file__).resolve().parents[2] / "validation" / "findings"

#: The classifications a finding may carry. A free-text status is a status
#: nobody can query, and "mostly resolved" is not a category.
FINDING_STATUSES = {
    "OPEN",
    "RESOLVED_MONTE_CARLO_VARIATION",
    "RESOLVED_SIMULATION_MODEL_DIFFERENCE",
    "RESOLVED_POWERTOST_LEGACY_METHOD_DIFFERENCE",
    "RESOLVED_BE_STATS_DEFECT",
    "RESOLVED_POWERTOST_CONFIGURATION_ERROR",
    "ACCEPTED_ORACLE_DIVERGENCE",
}


def _findings() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(FINDINGS.glob("VAL-*.json"))
        if not path.stem.endswith("-evidence")
    }


def test_every_finding_record_is_complete_and_classified():
    records = _findings()
    assert records, "the findings directory must not be empty once one is raised"
    for name, record in records.items():
        assert record["finding_id"] == name
        assert record["status"] in FINDING_STATUSES, name
        for key in ("title", "method", "raised_by", "raised_on"):
            assert str(record.get(key, "")).strip(), f"{name}: missing {key}"
        # Human-readable twin, so the record is not JSON-only.
        assert (FINDINGS / f"{name}.md").exists(), name


def test_every_open_finding_named_by_a_case_actually_exists():
    """A case may not point at a finding nobody wrote.

    An `open_findings` entry downgrades a whole method's tier-3 row. A typo
    would silently downgrade nothing, which is the wrong direction to fail in.
    """
    known = set(_findings())
    for case in harness.load_cases():
        for finding in case.open_findings:
            assert finding in known, f"{case.case_id} names unknown {finding}"


def test_the_root_cause_finding_cites_the_oracle_precisely():
    """A finding that says 'PowerTOST does something different' is not a
    finding. It has to name the version, the file and the line."""
    record = _findings()["VAL-FDA-HVD-001"]
    cause = record["root_cause"]
    assert cause["oracle"]["version"] == "1.5-7"
    assert "power_RSABE2L_isc.R" in cause["oracle"]["implemented_in"]
    lines = cause["decisive_lines"]
    assert any("BEul" in entry["line"] for entry in lines)
    assert any("ifelse(s2wRs>s2switch" in entry["line"] for entry in lines)
    assert any(entry.get("line_number") for entry in lines)


def test_the_resolution_is_confirmed_against_the_real_oracle_not_the_instrument():
    """The investigation transcribes PowerTOST, so it cannot corroborate it.

    The record has to carry the corrected cases run against the actual package,
    and the one line that settles the question: the be-stats value is the SAME
    in both runs, so nothing on the Python side moved.
    """
    confirmed = _findings()["VAL-FDA-HVD-001"]["confirmed_against_the_real_oracle"]
    decisive = confirmed["decisive_line"]

    assert decisive["before"]["python"] == decisive["after"]["python"] == 0.87055
    assert decisive["before"]["sigmas"] > harness.SIGMA_FINDING
    assert decisive["after"]["sigmas"] < 1.0

    # And the whole suite, not just the case that raised it.
    assert all(
        row["sigmas"] < harness.SIGMA_FINDING
        for row in confirmed["all_rsabe_comparisons"]
    )
    assert "0 failed" in confirmed["whole_run"]


def test_the_root_cause_finding_records_what_was_not_changed():
    """The brief's constraint, kept where it can be checked.

    An investigation that quietly edits production logic until the numbers
    agree produces the same green report as one that explains the difference.
    The record has to state which of the two happened.
    """
    resolution = _findings()["VAL-FDA-HVD-001"]["resolution"]
    assert resolution["classification"] == "RESOLVED_POWERTOST_CONFIGURATION_ERROR"
    unchanged = " ".join(resolution["changes_deliberately_not_made"])
    assert "No production statistical logic was changed" in unchanged
    assert "No tolerance was altered retrospectively" in unchanged


def test_the_engineering_observation_is_kept_out_of_the_statistical_finding():
    """A flaky test is not evidence about a statistical method.

    It is recorded, and recorded separately, so it can neither be lost nor
    mistaken for part of the numerical explanation.
    """
    record = _findings()["VAL-FDA-HVD-001"]
    observations = record["engineering_observations"]
    assert observations
    assert observations[0]["status"] in {"NOT_PURSUED", "EXPLAINED_AND_FIXED"}
    assert "pytest" in observations[0]["what"]
    # And it must not have leaked into the root cause.
    assert "pytest" not in json.dumps(record["root_cause"])


def test_the_invocation_dependent_test_failure_stays_fixed():
    """ENG-001. It was never intermittent - it depended on the invocation.

    `test_algorithm_conformance.py` imports from `tests.unit.test_rsabe_criterion`,
    which resolved only when the working directory was `be-stats/`. Run as
    `pytest be-stats/tests` from the repository root, those tests failed with
    ModuleNotFoundError. `rootdir` is `be-stats/pyproject.toml` either way, so
    one relative pythonpath entry covers both.
    """
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["pythonpath"] == ["."]

    # The import that needs it must still be the one being protected.
    conformance = (
        root / "tests" / "validation" / "test_algorithm_conformance.py"
    ).read_text(encoding="utf-8")
    assert "from tests.unit.test_rsabe_criterion import" in conformance


def test_the_threshold_divergence_is_a_separate_accepted_finding():
    """PowerTOST derives the switch from CV = 0.30; FDA states 0.294.

    Real, permanent, and not the cause of VAL-FDA-HVD-001. Keeping it as its
    own record is what stops a resolved finding from being reopened every time
    somebody rediscovers the fourth decimal.
    """
    record = _findings()["VAL-FDA-HVD-002"]
    assert record["status"] == "ACCEPTED_ORACLE_DIVERGENCE"
    powertost = record["what_differs"]["powertost"]
    assert powertost["value_on_the_swr_scale"] == pytest.approx(
        math.sqrt(math.log(0.30**2 + 1)), rel=1e-12
    )
    assert record["what_differs"]["fda"]["rule"] == "sWR >= 0.294"
    assert record["action_required"].startswith("None in be-stats")


def test_the_switch_thresholds_really_do_differ_by_what_the_finding_claims():
    """Recomputed here rather than trusted from the record."""
    from be_stats.spec import FDA_HVD_CONSTANTS

    fda = FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    powertost = math.sqrt(math.log(0.30**2 + 1))
    assert fda == 0.294
    assert powertost == pytest.approx(0.293560379208524, abs=1e-15)
    claimed = _findings()["VAL-FDA-HVD-002"]["what_differs"]["difference"]
    assert fda - powertost == pytest.approx(claimed, abs=1e-12)


# ------------------------------------------- tier 3 cannot read as validated -


def _tier3_for(open_findings: tuple[str, ...]) -> dict:
    """A minimal all-passing method, with and without a standing finding."""
    template = json.loads(
        (EXTERNAL / "cases" / "rsabe_002_boundary_near.json").read_text("utf-8")
    )
    cases = []
    for role in harness.TIER3_REQUIRED_ROLES["fda_hvd_rsabe"]:
        data = json.loads(json.dumps(template))
        data["case_id"] = f"SYNTH-{role}"
        data["inputs"]["role"] = role
        data["open_findings"] = list(open_findings)
        cases.append(harness.Case.from_dict(data))

    results = [
        harness.ComparisonResult(case.case_id, "p_be_sabec", harness.PASS,
                                 python_value=0.5, r_value=0.5,
                                 absolute_difference=0.0, relative_difference=0.0,
                                 absolute_tolerance=0.1, relative_tolerance=0.0)
        for case in cases
    ]
    return cases, results, harness.tier3_status(cases, results)


def test_a_clean_sweep_with_no_finding_is_a_plain_pass():
    _, _, tier3 = _tier3_for(())
    assert tier3["fda_hvd_rsabe"]["tier3"] == harness.TIER3_PASSED


def test_an_open_finding_downgrades_a_passing_method():
    """Every required role agreed, and a question remains that agreement does
    not answer. `PASSED` would be true and misleading."""
    _, _, tier3 = _tier3_for(("VAL-FDA-HVD-002",))
    status = tier3["fda_hvd_rsabe"]
    assert status["tier3"] == harness.TIER3_PASSED_WITH_FINDING
    assert status["open_findings"] == ["VAL-FDA-HVD-002"]


def test_the_report_cannot_show_a_qualified_pass_as_a_plain_one():
    cases, results, tier3 = _tier3_for(("VAL-FDA-HVD-002",))
    text = harness.render(results, tier3, harness.environment())

    assert "PASSED_WITH_FINDING" in text
    assert "PASSED_WITH_FINDING is not PASSED" in text
    assert "OPEN FINDING       VAL-FDA-HVD-002" in text


def test_no_report_can_render_the_words_fully_validated():
    """Tier 3 is one independent implementation agreeing. It is not
    validation, and the report must not let a skim reader conclude it is."""
    cases = harness.load_cases()
    results = harness.compare(cases, {c.case_id: {} for c in cases}, None)
    text = harness.render(results, harness.tier3_status(cases, results),
                          harness.environment())
    # Not even inside a negation. A consumer grepping the report for a
    # reassuring phrase must not find one, and "not fully validated" contains
    # "fully validated".
    assert "fully validated" not in text.lower()
    assert "cross-checked, not validated in full" in text
    assert "Tier 1B" in text


def test_the_shipped_rsabe_cases_carry_the_standing_finding():
    """Not a synthetic construction: the real case files must do this."""
    rsabe = [c for c in harness.load_cases() if c.method == "fda_hvd_rsabe"]
    assert rsabe
    for case in rsabe:
        assert "VAL-FDA-HVD-002" in case.open_findings, case.case_id


def test_the_open_findings_reach_the_machine_readable_report(tmp_path):
    """A consumer reading report.json must trip over them, not have to know
    to look in the tier-3 block."""
    report = tmp_path / "report.json"
    harness.main(["--json-out", str(report)])
    data = json.loads(report.read_text(encoding="utf-8"))
    assert "VAL-FDA-HVD-002" in data["open_findings"]


# ---------------------------------------- the corrected RSABE comparison ---


def test_every_rsabe_case_isolates_the_scaled_criterion():
    """The correction from VAL-FDA-HVD-001, asserted on the shipped files.

    Without `CVswitch = 0` on the R side, PowerTOST's `p(BE-sABEc)` is the
    mixed decision and the comparison is between two different quantities.
    """
    for case in harness.load_cases():
        if case.method != "fda_hvd_rsabe":
            continue
        assert case.inputs["experiment"] == simulate.SCALED_CRITERION_ISOLATED
        arguments = case.oracle["arguments"]
        assert "CVswitch=0" in arguments.replace(" ", ""), case.case_id
        assert "r_const=log(1.25)/0.25" in arguments.replace(" ", ""), case.case_id


def test_the_r_side_disables_switching_without_touching_the_constant():
    """The USER regSet must change the routing and nothing else.

    If it also changed `r_const`, the comparison would silently be against a
    different criterion - which would be a worse version of the bug it fixes.
    """
    r_side = (EXTERNAL / "run_powertost.R").read_text(encoding="utf-8")
    assert 'reg_const(' in r_side
    assert '"USER"' in r_side
    assert "CVswitch = 0" in r_side
    assert "r_const = log(1.25) / 0.25" in r_side
    assert "CVcap = Inf" in r_side
    # And it must explain itself, since a reader meeting `CVswitch = 0` in a
    # validation harness is right to be suspicious of it.
    assert "VAL-FDA-HVD-001" in r_side


def test_the_switching_fraction_matches_the_exact_chi_square():
    """The comparison `p_below_switch` makes, checked on the Python side alone.

    sWR^2 * dfRR / sigma^2_wR is chi-square on dfRR under the simulated model,
    so the expected fraction below the switch is a closed form. This is the one
    check that separates the sWR estimator and the switch from the criterion,
    and it needs no R.
    """
    from scipy import stats as scipy_stats

    n, cv = 36, 0.31
    result = simulate.simulate_scaled_power(
        method="fda_hvd_rsabe", design="2x2x4",
        cv_wr=cv, cv_wt=cv, theta0=0.90, n=n, nsims=4000, seed=20260828,
        experiment=simulate.SCALED_CRITERION_ISOLATED,
    )
    df_rr = n - 2
    exact = float(
        scipy_stats.chi2.cdf(df_rr * 0.294**2 / math.log1p(cv**2), df_rr)
    )
    assert exact == pytest.approx(0.4354, abs=5e-4)
    # Four standard errors of the Python side's own binomial sampling error.
    assert result["p_below_switch"] == pytest.approx(
        exact, abs=4.0 * math.sqrt(exact * (1 - exact) / 4000)
    )


def test_an_exact_r_value_is_not_scored_as_if_it_had_sampling_error():
    """Pooling both counts would inflate the denominator and make a real
    difference look smaller than it is."""
    case = next(
        c for c in harness.load_cases() if c.case_id == "RSABE-002-BOUNDARY-NEAR"
    )
    exact = next(c for c in case.comparisons if c.quantity == "p_below_switch")
    pooled = next(c for c in case.comparisons if c.quantity == "p_be_sabec")
    assert exact.r_value_is_exact
    assert not pooled.r_value_is_exact

    one_sided = harness._sigmas(case, exact, 0.44, 0.4354)
    two_sided = harness._sigmas(case, pooled, 0.44, 0.4354)
    assert one_sided > two_sided


# ------------------------------------------------ the investigation script ---


def test_the_investigation_instrument_is_not_part_of_the_package():
    """It transcribes PowerTOST, so it must never be importable as be-stats.

    A transcription of the oracle cannot corroborate the oracle, and a
    transcription of the oracle's non-FDA below-switch branch must not be
    reachable by anything asking what FDA would conclude.
    """
    package = Path(__file__).resolve().parents[2] / "src" / "be_stats"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "powertost_reproduction" not in text, path.name
        assert "investigate_val_fda_hvd_001" not in text, path.name


def test_the_investigation_script_labels_its_instrument_as_one():
    script = (EXTERNAL / "investigate_val_fda_hvd_001.py").read_text("utf-8")
    assert "INVESTIGATION INSTRUMENT, NOT EVIDENCE" in script
    assert "NOT A be-stats RESULT, AND NOT AN FDA RESULT" in script


def test_the_frozen_evidence_reproduces_the_explanation():
    """The numbers the finding rests on, read back from the file that made
    them rather than retyped into the record."""
    evidence = json.loads(
        (FINDINGS / "VAL-FDA-HVD-001-evidence.json").read_text(encoding="utf-8")
    )
    # Experiment A: the same quantity, compared against itself, agrees.
    assert evidence["experiment_a"]["sigmas"] < harness.SIGMA_FINDING
    # The sweep's gap vanishes exactly where the switching fraction does.
    by_cv = {row["cv_wr"]: row for row in evidence["sweep"]}
    assert by_cv[0.60]["fraction_below_switch"] == 0.0
    assert by_cv[0.60]["gap"] == pytest.approx(0.0, abs=1e-12)
    assert abs(by_cv[0.31]["gap"]) > 5 * abs(by_cv[0.40]["gap"])
    # And it is not sampling noise: it survives every seed.
    assert evidence["reproducibility"]["gap_range"] < 0.005
    assert evidence["reproducibility"]["gap_min"] > 0.005


def test_the_version_pin_is_compared_as_a_version_not_a_string():
    """The bug the second CI build found.

    CRAN writes PowerTOST's version as `1.5-7`; R's `package_version`
    normalises the separator, so `as.character(packageVersion(...))` is
    `1.5.7`. A string comparison fails on the very version it asked for -
    which is what happened, immediately after PowerTOST 1.5-7 installed
    successfully.

    Comparing through `package_version` on both sides makes the check correct
    rather than lenient: `1.5-7` and `1.5.7` match, `1.5.8` still does not.
    """
    for name in ("install_r_packages.R", "run_powertost.R"):
        script = (EXTERNAL / name).read_text(encoding="utf-8")
        assert "package_version(" in script, name
        assert 'gsub("-", ".",' in script, name
        # The string comparison that broke it must not return.
        assert "identical(as.character(lock$powertost_version)" not in script
        assert "if (!identical(got, want))" not in script
