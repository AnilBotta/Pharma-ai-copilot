"""The external validation harness: one case definition, two implementations.

WHAT THIS IS FOR

`be-stats` implements FDA's rules from the FDA document. That says nothing
about whether the implementation is numerically right. An independent
implementation of the same procedures, run from the same case definition, is
tier-3 evidence: an implementation oracle.

    FDA source
        -> be-stats implementation
        -> independent PowerTOST numerical reproduction

Never the other way round. PowerTOST is not the regulatory authority, and a
disagreement is a finding to investigate, not a correction to apply. The FDA
document remains the source of the rule.

WHY THIS IS NOT A UNIT TEST

It needs R and PowerTOST, which the package does not depend on and must never
depend on at runtime. `be-stats` is a pure Python package; this directory is
validation infrastructure that happens to live beside it.

A missing R environment therefore produces SKIPPED, never PASSED. That
distinction is the entire point of the report format below: a comparison that
did not happen must not look like a comparison that succeeded.

THE HIGHEST COMMON LAYER, AND WHY IT DIFFERS BY METHOD

This is the finding that shaped the design, and it is worth stating plainly
because it limits what can be claimed.

`PowerTOST` 1.5-7 offers, for the FDA scaled procedures, only
SIMULATION-BASED POWER functions - `power.RSABE`, `power.NTID`. They take an
assumed CV, ratio, design and sample size and return the probability of a BE
decision over `nsims` simulated studies. They do NOT take a dataset and return
sWR, a treatment contrast, or a criterion value.

`be-stats` does the opposite: it analyses a dataset. There is therefore no
layer at which the two can be compared directly for RSABE or NTI.

So the comparison is made at the highest layer both expose:

    COMPARISON_DIRECT   ordinary ABE power and sample size. Both are closed
                        form. Deterministic, tight tolerance.

    COMPARISON_CONSTANT regulatory constants. PowerTOST's `reg_const("FDA")`
                        against this package's verified values. Exact.

    COMPARISON_POWER    scaled procedures. The Python side SIMULATES studies,
                        runs the be-stats criterion on each, and reports the
                        proportion declared bioequivalent. PowerTOST reports
                        its own empirical power for the same scenario. Two
                        Monte Carlo estimates of the same probability, compared
                        with a tolerance derived from the binomial error of
                        BOTH - never tuned.

What cannot be cross-checked at all is recorded per case in
`not_cross_checkable`, rather than left as an absence somebody has to notice.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE / "cases"
LOCKFILE = HERE / "environment.lock.json"

#: How a case is compared. Stored in the case file so the tolerance rationale
#: and the comparison kind cannot drift apart.
COMPARISON_DIRECT = "direct"
COMPARISON_CONSTANT = "constant"
COMPARISON_POWER = "monte_carlo_power"

COMPARISON_KINDS = frozenset(
    {COMPARISON_DIRECT, COMPARISON_CONSTANT, COMPARISON_POWER}
)

#: Outcomes. `SKIPPED` is not a pass and is never counted as one.
PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"
ERROR = "ERROR"

#: A Monte Carlo comparison further apart than this many standard errors is a
#: FINDING even when it passes.
#:
#: The declared tolerance is evaluated at the worst case p = 0.5, which is a
#: legitimate bound fixed before any run - but for a comparison at p = 0.86 it
#: is roughly 40% wider than that comparison's own sampling error justifies. A
#: real procedural difference can therefore sit inside it.
#:
#: So the report also states how many of ITS OWN standard errors each
#: comparison is out, and calls anything beyond this a finding. It does not
#: change pass or fail: retroactively tightening a tolerance because of what it
#: produced is how a tolerance stops meaning anything. It makes the thing
#: visible so a person decides.
SIGMA_FINDING = 4.0


class CaseError(ValueError):
    """A case file is malformed. Loud, because a bad case silently ignored is
    a validation gap that looks like coverage."""


# --------------------------------------------------------------- the case ---


@dataclass(frozen=True, slots=True)
class Comparison:
    """One quantity to compare, with the tolerance and why it exists."""

    quantity: str
    kind: str
    absolute_tolerance: float
    relative_tolerance: float
    #: Mandatory. A tolerance without a stated reason is a tolerance chosen by
    #: running the test until it passed.
    tolerance_basis: str
    #: True when the R side computes this quantity in closed form rather than
    #: by simulation - `p_below_switch` is a chi-square CDF, not a proportion
    #: of simulated studies. It changes only how the sigma diagnostic is
    #: scaled: one side contributes no sampling error, so dividing by a
    #: two-sided standard error would understate how far apart they are.
    r_value_is_exact: bool = False

    def agrees(self, python_value: float, r_value: float) -> tuple[bool, float, float]:
        absolute = abs(python_value - r_value)
        relative = absolute / abs(r_value) if r_value != 0 else math.inf
        ok = absolute <= self.absolute_tolerance or relative <= self.relative_tolerance
        return ok, absolute, relative


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    title: str
    method: str
    comparison_kind: str
    inputs: dict
    comparisons: tuple[Comparison, ...]
    oracle: dict
    #: What this case explicitly does NOT establish.
    not_cross_checkable: tuple[str, ...] = ()
    #: Validation finding ids that remain open against this case. A method
    #: whose cases all pass but which carries one of these is reported
    #: `PASSED_WITH_FINDING`, never bare `PASSED` - see `tier3_status`.
    open_findings: tuple[str, ...] = ()
    notes: str = ""

    @staticmethod
    def from_dict(data: dict) -> Case:
        for field_name in (
            "case_id", "title", "method", "comparison_kind", "inputs",
            "comparisons", "oracle",
        ):
            if field_name not in data:
                raise CaseError(
                    f"{data.get('case_id', '?')}: missing '{field_name}'"
                )

        kind = data["comparison_kind"]
        if kind not in COMPARISON_KINDS:
            raise CaseError(
                f"{data['case_id']}: comparison_kind {kind!r} is not one of "
                f"{sorted(COMPARISON_KINDS)}"
            )

        if not data["comparisons"]:
            raise CaseError(
                f"{data['case_id']}: states no comparisons, so it would report "
                "PASS without comparing anything"
            )

        comparisons = []
        for raw in data["comparisons"]:
            for field_name in (
                "quantity", "absolute_tolerance", "relative_tolerance",
                "tolerance_basis",
            ):
                if field_name not in raw:
                    raise CaseError(
                        f"{data['case_id']}/{raw.get('quantity', '?')}: missing "
                        f"'{field_name}'"
                    )
            if not str(raw["tolerance_basis"]).strip():
                raise CaseError(
                    f"{data['case_id']}/{raw['quantity']}: tolerance_basis is "
                    "empty. Every tolerance must say why it is what it is."
                )
            comparisons.append(
                Comparison(
                    quantity=raw["quantity"],
                    kind=kind,
                    absolute_tolerance=float(raw["absolute_tolerance"]),
                    relative_tolerance=float(raw["relative_tolerance"]),
                    tolerance_basis=raw["tolerance_basis"],
                    r_value_is_exact=bool(raw.get("r_value_is_exact", False)),
                )
            )

        oracle = data["oracle"]
        for field_name in ("tool", "function"):
            if field_name not in oracle:
                raise CaseError(
                    f"{data['case_id']}: oracle is missing '{field_name}'"
                )

        return Case(
            case_id=data["case_id"],
            title=data["title"],
            method=data["method"],
            comparison_kind=kind,
            inputs=data["inputs"],
            comparisons=tuple(comparisons),
            oracle=oracle,
            not_cross_checkable=tuple(data.get("not_cross_checkable", ())),
            open_findings=tuple(data.get("open_findings", ())),
            notes=data.get("notes", ""),
        )


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    files = sorted(directory.glob("*.json"))
    if not files:
        raise CaseError(f"no case files in {directory}")
    cases = [Case.from_dict(json.loads(f.read_text(encoding="utf-8"))) for f in files]
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise CaseError(f"duplicate case_id {case.case_id}")
        seen.add(case.case_id)
    return cases


# ------------------------------------------------------- the Python side ---


def evaluate_python(case: Case) -> dict[str, float]:
    """What `be-stats` says, for this case's inputs.

    Imported lazily so a malformed case fails before the package is touched,
    and so this module can be imported to inspect cases without be-stats
    installed.
    """
    if case.comparison_kind == COMPARISON_DIRECT:
        return _evaluate_abe(case)
    if case.comparison_kind == COMPARISON_CONSTANT:
        return _evaluate_constants(case)
    if case.comparison_kind == COMPARISON_POWER:
        return _evaluate_monte_carlo_power(case)
    raise CaseError(f"{case.case_id}: no evaluator for {case.comparison_kind}")


def _evaluate_abe(case: Case) -> dict[str, float]:
    from be_stats import (
        Citation,
        Endpoint,
        Jurisdiction,
        RegulatoryValue,
        VerificationStatus,
        power_abe,
        sample_size_abe,
    )
    from be_stats.spec import AcceptanceInterval, BeSpec, DrugClass, Method

    inputs = case.inputs
    citation = Citation(authority="external validation", document=case.case_id)
    spec = BeSpec(
        method=Method.STANDARD_ABE,
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.STANDARD,
        endpoint=Endpoint.AUC,
        alpha=inputs["alpha"],
        acceptance=AcceptanceInterval(
            lower=RegulatoryValue(
                inputs["lower_limit"] * 100.0, citation, VerificationStatus.VERIFIED
            ),
            upper=RegulatoryValue(
                inputs["upper_limit"] * 100.0, citation, VerificationStatus.VERIFIED
            ),
            basis=case.case_id,
        ),
    )
    result = sample_size_abe(
        cv_percent=inputs["cv"] * 100.0,
        spec=spec,
        design=inputs["design"],
        target_power=inputs["target_power"],
        expected_ratio=inputs["theta0"],
    )
    achieved = power_abe(
        cv_percent=inputs["cv"] * 100.0,
        n_total=result.mathematical_n,
        spec=spec,
        design=inputs["design"],
        expected_ratio=inputs["theta0"],
    ).power
    return {
        "sample_size": float(result.mathematical_n),
        "achieved_power": achieved,
    }


def _evaluate_constants(case: Case) -> dict[str, float]:
    from be_stats.spec import FDA_HVD_CONSTANTS, FDA_NTI_CONSTANTS, fda_hvd_theta

    values = {
        "hvd_sigma_w0": FDA_HVD_CONSTANTS["sigma_w0"].value,
        "hvd_swr_switching_threshold": FDA_HVD_CONSTANTS[
            "swr_switching_threshold"
        ].value,
        "hvd_r_const": math.log(1.25) / FDA_HVD_CONSTANTS["sigma_w0"].value,
        "hvd_theta": fda_hvd_theta(),
        "hvd_point_estimate_lower": FDA_HVD_CONSTANTS["point_estimate_lower"].value,
        "hvd_point_estimate_upper": FDA_HVD_CONSTANTS["point_estimate_upper"].value,
        "nti_variance_ratio_upper_limit": FDA_NTI_CONSTANTS[
            "variance_ratio_upper_limit"
        ].value,
    }
    wanted = {c.quantity for c in case.comparisons}
    missing = wanted - values.keys()
    if missing:
        raise CaseError(f"{case.case_id}: no python value for {sorted(missing)}")
    return {k: v for k, v in values.items() if k in wanted}


def _evaluate_monte_carlo_power(case: Case) -> dict[str, float]:
    """Simulate studies, run the be-stats criterion, report the proportions.

    THE ONLY LAYER AT WHICH THE SCALED PROCEDURES CAN BE COMPARED

    PowerTOST reports empirical power for a scenario. It does not expose sWR or
    a criterion value for a dataset. So the Python side is made to produce the
    same kind of quantity: simulate `nsims` studies from the case's assumptions,
    apply the be-stats decision to each, and report the proportion that pass -
    overall and per component.

    This exercises the whole pipeline: dataset construction, sWR, the treatment
    contrast, the criterion. A disagreement here is a real disagreement about
    the procedure, not about the plumbing.
    """
    from simulate import simulate_scaled_power

    return simulate_scaled_power(
        method=case.method,
        design=case.inputs["design"],
        cv_wr=case.inputs["cv_wr"],
        cv_wt=case.inputs.get("cv_wt", case.inputs["cv_wr"]),
        theta0=case.inputs["theta0"],
        n=case.inputs["n"],
        nsims=case.inputs["nsims"],
        seed=case.inputs["seed"],
        experiment=case.inputs.get("experiment"),
    )


# ------------------------------------------------------------ the R side ---


def r_available() -> bool:
    try:
        completed = subprocess.run(
            ["Rscript", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def run_r_side(output: Path, cases_dir: Path = CASES_DIR) -> dict:
    """Run `run_powertost.R` and read back its results.

    Raises rather than returning empty on failure: an R side that errored must
    not be indistinguishable from one that had nothing to say.
    """
    script = HERE / "run_powertost.R"
    completed = subprocess.run(
        ["Rscript", str(script), str(cases_dir), str(output)],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"run_powertost.R exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if not output.exists():
        raise RuntimeError(
            f"run_powertost.R exited 0 but wrote no results to {output}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


# ------------------------------------------------------------- comparing ---


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    case_id: str
    quantity: str
    outcome: str
    python_value: float | None = None
    r_value: float | None = None
    absolute_difference: float | None = None
    relative_difference: float | None = None
    absolute_tolerance: float | None = None
    relative_tolerance: float | None = None
    tolerance_basis: str = ""
    detail: str = ""
    #: For Monte Carlo comparisons: the difference in units of ITS OWN sampling
    #: standard error, at the pooled observed proportion. See `SIGMA_FINDING`.
    monte_carlo_sigmas: float | None = None

    @property
    def is_finding(self) -> bool:
        """Agreed within tolerance, and further apart than chance explains."""
        return (
            self.outcome == PASS
            and self.monte_carlo_sigmas is not None
            and self.monte_carlo_sigmas > SIGMA_FINDING
        )

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "quantity": self.quantity,
            "outcome": self.outcome,
            "python_value": self.python_value,
            "r_value": self.r_value,
            "absolute_difference": self.absolute_difference,
            "relative_difference": self.relative_difference,
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "monte_carlo_sigmas": self.monte_carlo_sigmas,
            "is_finding": self.is_finding,
            "tolerance_basis": self.tolerance_basis,
            "detail": self.detail,
        }


def compare(
    cases: list[Case],
    python_values: dict[str, dict[str, float]],
    r_values: dict[str, dict[str, float]] | None,
) -> list[ComparisonResult]:
    """Every comparison every case asks for. Nothing is skipped silently."""
    results: list[ComparisonResult] = []
    for case in cases:
        for comparison in case.comparisons:
            if r_values is None:
                results.append(
                    ComparisonResult(
                        case.case_id, comparison.quantity, SKIPPED,
                        python_value=python_values.get(case.case_id, {}).get(
                            comparison.quantity
                        ),
                        tolerance_basis=comparison.tolerance_basis,
                        detail="external validation environment unavailable "
                        "(Rscript not found)",
                    )
                )
                continue

            python_side = python_values.get(case.case_id, {})
            r_side = r_values.get(case.case_id, {})

            if comparison.quantity not in python_side:
                results.append(
                    ComparisonResult(
                        case.case_id, comparison.quantity, ERROR,
                        tolerance_basis=comparison.tolerance_basis,
                        detail="the Python side produced no value for this quantity",
                    )
                )
                continue
            if comparison.quantity not in r_side:
                results.append(
                    ComparisonResult(
                        case.case_id, comparison.quantity, ERROR,
                        python_value=python_side[comparison.quantity],
                        tolerance_basis=comparison.tolerance_basis,
                        detail="the R side produced no value for this quantity",
                    )
                )
                continue

            python_value = float(python_side[comparison.quantity])
            r_value = float(r_side[comparison.quantity])
            ok, absolute, relative = comparison.agrees(python_value, r_value)
            results.append(
                ComparisonResult(
                    case.case_id,
                    comparison.quantity,
                    PASS if ok else FAIL,
                    python_value=python_value,
                    r_value=r_value,
                    absolute_difference=absolute,
                    relative_difference=relative,
                    absolute_tolerance=comparison.absolute_tolerance,
                    relative_tolerance=comparison.relative_tolerance,
                    tolerance_basis=comparison.tolerance_basis,
                    monte_carlo_sigmas=_sigmas(
                        case, comparison, python_value, r_value
                    ),
                )
            )
    return results


def _sigmas(
    case: Case, comparison: Comparison, python_value: float, r_value: float
) -> float | None:
    """How many of its own standard errors apart two proportions are.

    Only meaningful for Monte Carlo comparisons, where at least one side is an
    estimate. `None` everywhere else - a closed-form comparison against a
    closed form has no sampling error to measure against.

    When the R side is exact - `p_below_switch` is a chi-square CDF - only the
    Python side contributes variance. Pooling both counts would inflate the
    denominator and make a real difference look smaller than it is.
    """
    if case.comparison_kind != COMPARISON_POWER:
        return None
    n_python = case.inputs.get("nsims")
    if not n_python:
        return None
    if comparison.r_value_is_exact:
        pooled = r_value
        variance = pooled * (1.0 - pooled) / n_python
    else:
        n_r = case.inputs.get("nsims_r")
        if not n_r:
            return None
        pooled = (python_value * n_python + r_value * n_r) / (n_python + n_r)
        variance = pooled * (1.0 - pooled) * (1.0 / n_python + 1.0 / n_r)
    if variance <= 0.0:
        return None
    return abs(python_value - r_value) / math.sqrt(variance)


# ---------------------------------------------- tier-3 evidence policy ---

#: What must agree before a method may be called tier-3 cross-checked.
#:
#: One agreeing case is not validation. A central case can pass while the
#: boundary is wrong, a low-variability case can pass while the scaled branch
#: is wrong, and a balanced case can pass while the unbalanced weighting is
#: wrong. So each method names the case roles it needs, and every one of them
#: must PASS - not merely not-FAIL, which SKIPPED would satisfy.
TIER3_REQUIRED_ROLES: dict[str, tuple[str, ...]] = {
    #: A central scenario, and one at limits other than 80-125 so the
    #: acceptance interval is exercised as an input rather than a constant.
    "standard_abe": ("central", "narrow_limits"),
    #: Central, plus a scenario sitting near the switching threshold where the
    #: scaled and unscaled branches are both plausible, plus a genuinely highly
    #: variable one where the scaling is doing real work.
    "fda_hvd_rsabe": ("central", "boundary_near", "high_variability"),
    #: Central, plus a scenario where the test product is markedly less
    #: reproducible than the reference - which is what criterion (c) exists to
    #: catch, and the axis a central case cannot exercise.
    "fda_nti": ("central", "unequal_variability"),
}


#: Tier-3 outcomes.
#:
#: `PASSED_WITH_FINDING` exists because `PASSED` was, for a while, the only
#: thing the FDA HVD row could say - while the run that produced it had also
#: raised VAL-FDA-HVD-001. A reader scanning the tier-3 block would have seen
#: PASSED and stopped. A status that can only say PASSED or PENDING cannot
#: carry the one thing a reviewer most needs to know: that the comparison
#: succeeded against an oracle with a known open question against it.
TIER3_PASSED = "PASSED"
TIER3_PASSED_WITH_FINDING = "PASSED_WITH_FINDING"
TIER3_PENDING = "PENDING"


def tier3_status(
    cases: list[Case], results: list[ComparisonResult]
) -> dict[str, dict]:
    """Per method: which required roles are covered, and with what caveats.

    Two things can qualify a pass, and they are kept apart because they mean
    different things:

        open_findings   declared on the case, standing questions about what
                        the comparison establishes. They survive a green run,
                        because a green run is not what closes them.

        run_findings    raised BY this run: a comparison that agreed within
                        tolerance but sits further out than sampling error
                        explains. New every time.
    """
    outcomes: dict[str, set[str]] = {}
    for result in results:
        outcomes.setdefault(result.case_id, set()).add(result.outcome)

    report: dict[str, dict] = {}
    for method, required in TIER3_REQUIRED_ROLES.items():
        method_cases = [c for c in cases if c.method == method]
        method_case_ids = {c.case_id for c in method_cases}
        roles_present = {c.inputs.get("role") for c in method_cases}
        missing_roles = [r for r in required if r not in roles_present]

        role_status: dict[str, str] = {}
        for case in method_cases:
            role = case.inputs.get("role", "unspecified")
            got = outcomes.get(case.case_id, {SKIPPED})
            if FAIL in got or ERROR in got:
                role_status[role] = FAIL
            elif SKIPPED in got:
                role_status[role] = SKIPPED
            else:
                role_status[role] = PASS

        open_findings = sorted(
            {f for case in method_cases for f in case.open_findings}
        )
        run_findings = sorted(
            {
                f"{r.case_id}/{r.quantity}"
                for r in results
                if r.is_finding and r.case_id in method_case_ids
            }
        )

        all_required_pass = not missing_roles and all(
            role_status.get(role) == PASS for role in required
        )
        if not all_required_pass:
            tier3 = TIER3_PENDING
        elif open_findings or run_findings:
            tier3 = TIER3_PASSED_WITH_FINDING
        else:
            tier3 = TIER3_PASSED

        report[method] = {
            "required_roles": list(required),
            "missing_roles": missing_roles,
            "role_status": role_status,
            "open_findings": open_findings,
            "run_findings": run_findings,
            "tier3": tier3,
        }
    return report


# --------------------------------------------------------------- report ---


def environment() -> dict:
    lock = json.loads(LOCKFILE.read_text(encoding="utf-8")) if LOCKFILE.exists() else {}
    observed = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "r_available": r_available(),
    }
    try:
        import be_stats

        observed["be_stats"] = be_stats.__version__
    except Exception:  # pragma: no cover - be-stats should always import
        observed["be_stats"] = "unavailable"
    try:
        import scipy

        observed["scipy"] = scipy.__version__
    except Exception:  # pragma: no cover
        observed["scipy"] = "unavailable"
    return {"declared": lock, "observed": observed}


def render(results: list[ComparisonResult], tier3: dict, env: dict) -> str:
    width = max((len(f"{r.case_id}/{r.quantity}") for r in results), default=20)
    lines = [
        "be-stats external validation — PowerTOST cross-check",
        "=" * 78,
        "",
        f"python      {env['observed']['python']}",
        f"be-stats    {env['observed']['be_stats']}",
        f"scipy       {env['observed']['scipy']}",
        f"R available {env['observed']['r_available']}",
    ]
    declared = env.get("declared", {})
    if declared:
        lines.append(
            f"declared    R {declared.get('r_version', '?')}, "
            f"PowerTOST {declared.get('powertost_version', '?')}"
        )
    lines += ["", "-" * 78]

    for result in results:
        label = f"{result.case_id}/{result.quantity}".ljust(width)
        if result.outcome in (SKIPPED, ERROR):
            lines.append(f"{label}  {result.outcome:<7} {result.detail}")
            continue
        sigma = (
            f" [{result.monte_carlo_sigmas:.2f} sigma]"
            if result.monte_carlo_sigmas is not None
            else ""
        )
        flag = "  <-- FINDING" if result.is_finding else ""
        lines.append(
            f"{label}  {result.outcome:<7} "
            f"py={result.python_value!r} r={result.r_value!r} "
            f"abs={result.absolute_difference:.3e} "
            f"rel={result.relative_difference:.3e} "
            f"(tol abs={result.absolute_tolerance:.3e} "
            f"rel={result.relative_tolerance:.3e})"
            f"{sigma}{flag}"
        )

    counts = {
        outcome: sum(1 for r in results if r.outcome == outcome)
        for outcome in (PASS, FAIL, SKIPPED, ERROR)
    }
    findings = [r for r in results if r.is_finding]
    lines += [
        "-" * 78,
        f"{counts[PASS]} passed, {counts[FAIL]} failed, "
        f"{counts[SKIPPED]} skipped, {counts[ERROR]} errored",
    ]

    if findings:
        lines += [
            "",
            f"FINDINGS: {len(findings)} comparison(s) agreed within the declared",
            f"tolerance and are further apart than sampling error explains",
            f"(> {SIGMA_FINDING:.0f} of their own standard errors).",
            "",
        ]
        for result in findings:
            lines.append(
                f"  {result.case_id}/{result.quantity}: "
                f"{result.monte_carlo_sigmas:.2f} sigma "
                f"(diff {result.absolute_difference:.3e})"
            )
        lines += [
            "",
            "  These are not failures and must not be treated as noise either.",
            "  The declared tolerance is evaluated at the worst case p = 0.5,",
            "  which is wider than a comparison at extreme p deserves. Each one",
            "  needs a reason before the method it belongs to is relied upon.",
        ]

    lines += [
        "",
        "Tier 3 status by method",
        "-" * 78,
    ]
    for method, status in sorted(tier3.items()):
        lines.append(f"  {method:<20} {status['tier3']}")
        for role in status["required_roles"]:
            got = status["role_status"].get(role, "ABSENT")
            lines.append(f"      {role:<18} {got}")
        if status["missing_roles"]:
            lines.append(f"      missing roles: {', '.join(status['missing_roles'])}")
        for finding in status.get("open_findings", ()):
            lines.append(f"      OPEN FINDING       {finding}")
        for finding in status.get("run_findings", ()):
            lines.append(f"      RAISED THIS RUN    {finding}")

    qualified = sorted(
        m for m, s in tier3.items() if s["tier3"] == TIER3_PASSED_WITH_FINDING
    )
    if qualified:
        lines += [
            "",
            "PASSED_WITH_FINDING is not PASSED. Every required role agreed with",
            "the oracle, and a question remains that agreement does not answer.",
            "Read the named finding before relying on the method:",
            "",
        ]
        for method in qualified:
            names = tier3[method]["open_findings"] + tier3[method]["run_findings"]
            lines.append(f"  {method}: {', '.join(names)}")

    lines += [
        "",
        "WHAT A GREEN TIER 3 DOES AND DOES NOT MEAN",
        "",
        "It means one independent implementation reproduces these numbers, and",
        "nothing more. Tier 1B - the FDA's own worked datasets - is a separate",
        "row, and no amount of tier 3 substitutes for it. A method green here",
        "is cross-checked, not validated in full.",
        "",
        "PowerTOST is an implementation oracle, not a regulatory authority.",
        "The FDA guidance remains the source of the rule; a disagreement here",
        "is a finding to investigate, not a correction to apply.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_DIR)
    parser.add_argument("--json-out", type=Path, default=HERE / "report.json")
    parser.add_argument("--text-out", type=Path, default=None)
    parser.add_argument(
        "--require-r",
        action="store_true",
        help="exit non-zero if the R environment is unavailable, instead of "
        "reporting SKIPPED",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    python_values = {case.case_id: evaluate_python(case) for case in cases}

    r_values = None
    if r_available():
        r_values = run_r_side(HERE / "powertost_results.json", args.cases)
    elif args.require_r:
        print(
            "external validation environment unavailable: Rscript not found",
            file=sys.stderr,
        )
        return 2

    results = compare(cases, python_values, r_values)
    tier3 = tier3_status(cases, results)
    env = environment()

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "environment": env,
        "comparisons": [r.as_dict() for r in results],
        "tier3": tier3,
        # Hoisted to the top level so a consumer reading the report
        # programmatically cannot render a green summary without stepping over
        # them. See `validation/findings/`.
        "open_findings": sorted({f for case in cases for f in case.open_findings}),
    }
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    text = render(results, tier3, env)
    print(text)
    if args.text_out:
        args.text_out.write_text(text, encoding="utf-8")

    if any(r.outcome in (FAIL, ERROR) for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
