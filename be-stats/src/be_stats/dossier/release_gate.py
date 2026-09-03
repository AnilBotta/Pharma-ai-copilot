"""The gate a capability must pass before it may be called VALIDATED.

WHY A GATE RATHER THAN A REVIEW

Reviews happen. The failure mode is not that nobody looks; it is that somebody
looks at ONE number, sees it match, and promotes. That is exactly how a
package ends up claiming a regulator's authority for an oracle's agreement -
and this repository has the near-miss on record: FDA's Appendix C model
reproduces EMA's published SAS output to every printed decimal, and promoting
FDA_REPLICATE_STANDARD_ABE_FULL on it would have inflated one regulator's
authority into another's.

So the conditions are enumerated, machine-checked, and all of them must hold:

    1  the capability is implemented
    2  it holds TIER 1B evidence - a REGULATOR'S OWN published numbers,
       reproduced. Not tier 1A, not tier 3, however much of either exists
    3  that evidence PASSED, and did not skip because an environment was
       missing
    4  its regulatory source is PINNED to a document version
    5  no BLOCKING finding is open against it
    6  no blocker lists it as affected
    7  the transition has been explicitly reviewed - `reviewed_transitions`
       must name it

Condition 7 is the one that cannot be automated away, and the gate does not
try: it requires the reviewer to have named the capability, so that promoting
something is always a deliberate act by a person and never a consequence of
evidence arriving.

CI VERSUS CERTIFICATION

`check_release_gate` is honest about missing environments rather than tolerant
of them. A tier-3 record that skipped is reported as skipped; a tier-1B record
that skipped disqualifies. Ordinary CI runs this and expects the current
statuses to be stable; a certification run additionally requires that no
evidence record anywhere is in a skipped state - see `certification_blockers`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from be_stats.dossier.blockers import blockers_for
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.evidence import (
    EVIDENCE_MANIFEST,
    EvidenceStatus,
    evidence_for,
)
from be_stats.dossier.findings import FindingSeverity, findings_for
from be_stats.dossier.statuses import EvidenceTier, ImplementationStatus
from be_stats.provenance import ValidationStatus


@dataclass(frozen=True, slots=True)
class GateResult:
    """Whether one capability may hold the status it holds."""

    capability_id: str
    claimed_status: ValidationStatus
    #: Empty means the claim is supportable.
    violations: tuple[str, ...] = ()
    #: Conditions that held, so a reviewer can see what was checked rather
    #: than only what failed.
    satisfied: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.violations


@dataclass(frozen=True, slots=True)
class ReleaseGateReport:
    """The gate over the whole matrix."""

    results: tuple[GateResult, ...]
    #: Capabilities whose claimed status is not supportable.
    failures: tuple[GateResult, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_lines(self) -> list[str]:
        lines = [f"release gate: {'PASS' if self.passed else 'FAIL'}"]
        for result in self.results:
            mark = "ok  " if result.passed else "FAIL"
            lines.append(f"  {mark} {result.capability_id} = {result.claimed_status}")
            for violation in result.violations:
                lines.append(f"         - {violation}")
        return lines


def check_capability(
    capability_id: str,
    *,
    reviewed_transitions: frozenset[str] = frozenset(),
) -> GateResult:
    """Whether this capability's CLAIMED status is supportable by the evidence.

    Note the direction. The gate does not decide what a capability's status
    should be; it checks that the status already claimed in `spec` is one the
    evidence can carry. A status claimed without evidence fails here, which is
    what stops a promotion landing quietly in a diff.
    """
    record = CAPABILITY_MATRIX[capability_id]
    claimed = record.validation_status
    violations: list[str] = []
    satisfied: list[str] = []

    # Statuses below VALIDATED assert nothing that needs qualifying evidence.
    # They still have to be internally coherent, which is checked first.
    if record.implementation_status is ImplementationStatus.NOT_IMPLEMENTED:
        if not record.refusal_conditions:
            violations.append(
                "NOT_IMPLEMENTED with no refusal condition. A capability that "
                "cannot run must be able to say so with a code."
            )
        else:
            satisfied.append("not implemented, and refuses with a named code")
        if record.decision_supported:
            violations.append(
                "NOT_IMPLEMENTED and decision_supported=True. Nothing that "
                "does not run may be advertised as producing a verdict."
            )
        return GateResult(
            capability_id=capability_id,
            claimed_status=claimed,
            violations=tuple(violations),
            satisfied=tuple(satisfied),
        )

    if claimed is not ValidationStatus.VALIDATED:
        satisfied.append(
            f"status {claimed} claims no regulatory agreement, so the "
            "qualifying-evidence conditions do not apply"
        )
        return GateResult(
            capability_id=capability_id,
            claimed_status=claimed,
            satisfied=tuple(satisfied),
        )

    # --------------------------------------------- VALIDATED is claimed ---
    records = evidence_for(capability_id)
    if not records:
        violations.append("VALIDATED with no evidence record at all.")

    tier_1b = [r for r in records if r.tier is EvidenceTier.TIER_1B]
    if not tier_1b:
        violations.append(
            "VALIDATED without tier-1B evidence. A regulator's own published "
            "numbers are the bar; an attested algorithm (1A) and an "
            "independent implementation agreeing (3) are not substitutes."
        )
    else:
        satisfied.append(f"{len(tier_1b)} tier-1B record(s)")

    established = [
        r
        for r in tier_1b
        if r.status in (EvidenceStatus.PASSED, EvidenceStatus.PASSED_WITH_FINDING)
    ]
    if tier_1b and not established:
        statuses = ", ".join(str(r.status) for r in tier_1b)
        violations.append(
            f"VALIDATED on tier-1B evidence that did not establish anything "
            f"({statuses}). A skipped or pending comparison is not a pass."
        )
    elif established:
        satisfied.append("tier-1B evidence passed")

    if not record.regulatory_source.document_version:
        violations.append(
            "VALIDATED against an unpinned regulatory source. A document "
            "version is part of the claim - FDA's 2001 and 2026 guidances "
            "share a title and disagree."
        )
    else:
        satisfied.append(
            f"source pinned to {record.regulatory_source.document_version!r}"
        )

    blocking = [
        f
        for f in findings_for(capability_id)
        if f.severity is FindingSeverity.BLOCKING and f.is_open
    ]
    if blocking:
        violations.append(
            "VALIDATED with open blocking finding(s): "
            + ", ".join(f.finding_id for f in blocking)
        )
    else:
        satisfied.append("no open blocking finding")

    blockers = blockers_for(capability_id)
    if blockers:
        violations.append(
            "VALIDATED while listed as affected by blocker(s): "
            + ", ".join(b.blocker_id for b in blockers)
        )
    else:
        satisfied.append("no open blocker names this capability")

    if capability_id not in reviewed_transitions:
        violations.append(
            "VALIDATED without an explicitly reviewed status transition. "
            "Pass the capability id in reviewed_transitions to record that a "
            "named reviewer approved this promotion. Evidence arriving is "
            "not evidence accepted."
        )
    else:
        satisfied.append("status transition explicitly reviewed")

    return GateResult(
        capability_id=capability_id,
        claimed_status=claimed,
        violations=tuple(violations),
        satisfied=tuple(satisfied),
    )


#: Capabilities whose VALIDATED status has been reviewed and recorded.
#:
#: Three EMA capabilities, promoted on tier-1B evidence in the ABEL release.
#: Adding a name here is the deliberate act condition 7 requires; it is a
#: visible line in a diff, which is the whole point of it being data.
REVIEWED_TRANSITIONS: frozenset[str] = frozenset(
    {
        "EMA_HVD_REFERENCE_VARIABILITY",
        "EMA_REPLICATE_METHOD_A",
        "EMA_ABEL_LIMIT_CALCULATION",
    }
)


def check_release_gate(
    *, reviewed_transitions: frozenset[str] = REVIEWED_TRANSITIONS
) -> ReleaseGateReport:
    """Run the gate over every capability in the matrix."""
    results = tuple(
        check_capability(cid, reviewed_transitions=reviewed_transitions)
        for cid in CAPABILITY_MATRIX
    )
    return ReleaseGateReport(
        results=results,
        failures=tuple(r for r in results if not r.passed),
    )


def certification_blockers() -> list[str]:
    """What stops this build being certifiable, as opposed to merely green.

    ORDINARY CI AND CERTIFICATION ASK DIFFERENT QUESTIONS. CI asks "did
    anything regress"; a missing R or Julia is then an environment fact and
    the comparison reports SKIPPED, which is correct and not a failure.
    Certification asks "is every claim currently established", and there a
    comparison that did not run is indistinguishable from one that would have
    failed.

    So this function exists separately from `check_release_gate`, and a
    missing external environment appears here and only here.
    """
    problems: list[str] = []

    skipped = [
        r
        for r in EVIDENCE_MANIFEST
        if r.status is EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE
    ]
    for record in skipped:
        problems.append(
            f"{record.evidence_id}: {record.status} - the external oracle "
            f"environment was unavailable, so this comparison established "
            f"nothing. Run it in the pinned container before certifying."
        )

    pending = [r for r in EVIDENCE_MANIFEST if r.status is EvidenceStatus.PENDING]
    for record in pending:
        problems.append(
            f"{record.evidence_id}: {record.status} - awaited evidence that "
            f"has not arrived."
        )

    gate = check_release_gate()
    for failure in gate.failures:
        problems.append(
            f"{failure.capability_id}: release gate failure - "
            + "; ".join(failure.violations)
        )

    return problems
