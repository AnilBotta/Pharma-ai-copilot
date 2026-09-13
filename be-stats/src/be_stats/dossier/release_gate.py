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
    2  it holds QUALIFYING TIER 1B evidence - a record that is
         a  tier 1B,
         b  of source type REGULATOR_PUBLISHED_NUMBERS,
         c  PASSED or PASSED_WITH_FINDING, not skipped or pending, and
         d  published by the capability's GOVERNING AUTHORITY: the authority
            named by the capability's own regulatory source.
       Not tier 1A, not tier 3, however much of either exists - and not
       another regulator's numbers, however well they reproduce
    3  its regulatory source is PINNED - one authority, a named document, the
       section within it, and which issue is meant - with no declared citation
       exception outstanding. The definition lives in `dossier.citations` and
       nowhere else; this module used to carry a weaker copy of it
    4  no BLOCKING finding is open against it
    5  no blocker lists it as affected
    6  the transition has been explicitly reviewed - `reviewed_transitions`
       must name it

Condition 6 is the one that cannot be automated away, and the gate does not
try: it requires the reviewer to have named the capability, so that promoting
something is always a deliberate act by a person and never a consequence of
evidence arriving.

CONDITION 2d, AND WHY IT WAS MISSING

The module docstring above always SAID "a regulator's own published numbers"
and named the Appendix C near-miss as the thing it existed to stop. The code
checked `tier is TIER_1B`. `APPENDIX-C-EMA-SAS-METHOD-C` is tier 1B, EMA's, and
attached to three FDA capabilities, so for all three the tier-1B condition was
satisfied by another regulator's numbers. What actually stood between them and
a VALIDATED claim was a blocker or a finding that happened to be open -
`FDA_HVD_UNSCALED_BRANCH` was held back by the partial-replicate blocker alone.

The fix does not detach that evidence. It is good evidence: it shows the
shared mixed model computes what EMA's SAS output computed. It is SUPPORTING
for an FDA capability and QUALIFYING for none, and `assess_tier_1b` says which,
per record and per capability, so the distinction is visible rather than
enforced by deletion.

TIER VERSUS QUALIFICATION

Tier describes the SOURCE and does not change with what the record is attached
to - EMA's output is tier 1B beside an FDA capability too. Qualification is a
RELATION between a record and a capability, decided here and nowhere else.

CI VERSUS CERTIFICATION

`check_release_gate` is honest about missing environments rather than tolerant
of them. A tier-3 record that skipped is reported as skipped; a tier-1B record
that skipped disqualifies. Ordinary CI runs this and expects the current
statuses to be stable; a certification run additionally requires that no
evidence record anywhere is in a skipped state - see `certification_blockers`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from be_stats.dossier.blockers import blockers_for
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.citations import why_not_pinned
from be_stats.dossier.evidence import (
    EVIDENCE_MANIFEST,
    EvidenceRecord,
    EvidenceStatus,
    SourceType,
    evidence_for,
)
from be_stats.dossier.findings import FindingSeverity, findings_for
from be_stats.dossier.statuses import EvidenceTier, ImplementationStatus
from be_stats.provenance import Authority, ValidationStatus

#: The evidence statuses that establish something. Anything else - pending,
#: skipped, not available - is a comparison that did not produce a result.
_ESTABLISHED: frozenset[EvidenceStatus] = frozenset(
    {EvidenceStatus.PASSED, EvidenceStatus.PASSED_WITH_FINDING}
)


class Tier1BRelation(StrEnum):
    """What one tier-1B record is to one capability.

    Exactly one member is QUALIFYING. Every other member keeps the record
    visible and says why it cannot carry a VALIDATED claim - which is the
    difference between evidence that is not enough and evidence that is not
    there.
    """

    #: Counts toward condition 2: regulator-published numbers, established,
    #: from the capability's governing authority.
    QUALIFYING = "qualifying"
    #: Regulator-published and established, from a DIFFERENT authority. Real
    #: evidence about the computation, kept and shown, never qualifying.
    SUPPORTING_CROSS_AUTHORITY = "supporting_cross_authority"
    #: The record names no canonical authority, or the capability's citation
    #: resolves to none. Fails closed.
    NOT_QUALIFYING_AUTHORITY_UNKNOWN = "not_qualifying_authority_unknown"
    #: Labelled tier 1B, but not regulator-published numbers. The tier label
    #: alone qualifies nothing.
    NOT_QUALIFYING_SOURCE_TYPE = "not_qualifying_source_type"
    #: Pending, skipped or not available. A comparison that did not run.
    NOT_QUALIFYING_NOT_ESTABLISHED = "not_qualifying_not_established"


@dataclass(frozen=True, slots=True)
class Tier1BAssessment:
    """One tier-1B record, judged against one capability."""

    evidence_id: str
    capability_id: str
    governing_authority: Authority | None
    evidence_authority: Authority | None
    source_type: SourceType
    status: EvidenceStatus
    relation: Tier1BRelation
    #: Why, in a sentence a reviewer can act on.
    reason: str

    @property
    def qualifies(self) -> bool:
        return self.relation is Tier1BRelation.QUALIFYING


def _authority_name(authority: Authority | None) -> str:
    return str(authority) if authority is not None else "no canonical authority"


def _assess(
    evidence: EvidenceRecord, capability_id: str, governing: Authority | None
) -> Tier1BAssessment:
    """The four qualifying conditions, in the order a reviewer asks them.

    Source type, then status, then authority. A record failing an earlier
    condition is reported for that one, because "it is from the wrong
    regulator" is not the interesting fact about a comparison that never ran.
    """
    if evidence.source_type is not SourceType.REGULATOR_PUBLISHED_NUMBERS:
        relation = Tier1BRelation.NOT_QUALIFYING_SOURCE_TYPE
        reason = (
            f"labelled tier 1B with source type {evidence.source_type}, not "
            f"{SourceType.REGULATOR_PUBLISHED_NUMBERS}; the tier label alone "
            "qualifies nothing"
        )
    elif evidence.status not in _ESTABLISHED:
        relation = Tier1BRelation.NOT_QUALIFYING_NOT_ESTABLISHED
        reason = (
            f"status {evidence.status}; a skipped or pending comparison is "
            "not a pass"
        )
    elif governing is None or evidence.evidence_authority is None:
        relation = Tier1BRelation.NOT_QUALIFYING_AUTHORITY_UNKNOWN
        reason = (
            f"evidence authority is {_authority_name(evidence.evidence_authority)} "
            f"and the capability's governing authority is "
            f"{_authority_name(governing)}; an authority that cannot be "
            "compared qualifies nothing"
        )
    # Identity of two enum members. Not a string test of any kind: the
    # record's human-readable `source_authority` is never read by this module.
    elif evidence.evidence_authority is not governing:
        relation = Tier1BRelation.SUPPORTING_CROSS_AUTHORITY
        reason = (
            f"published by {evidence.evidence_authority}, not {governing}. "
            f"Kept as supporting evidence for the computation; it cannot carry "
            f"a {governing} VALIDATED claim"
        )
    else:
        relation = Tier1BRelation.QUALIFYING
        reason = (
            f"{governing}-published numbers, reproduced, for a capability "
            f"governed by {governing}"
        )
    return Tier1BAssessment(
        evidence_id=evidence.evidence_id,
        capability_id=capability_id,
        governing_authority=governing,
        evidence_authority=evidence.evidence_authority,
        source_type=evidence.source_type,
        status=evidence.status,
        relation=relation,
        reason=reason,
    )


def assess_tier_1b(capability_id: str) -> tuple[Tier1BAssessment, ...]:
    """Every tier-1B record bearing on a capability, and what each is to it.

    Nothing is filtered out. A cross-authority record appears here as
    SUPPORTING_CROSS_AUTHORITY rather than disappearing, so a report built on
    this function shows the evidence and says why it does not qualify.
    """
    governing = CAPABILITY_MATRIX[capability_id].governing_authority
    return tuple(
        _assess(record, capability_id, governing)
        for record in evidence_for(capability_id)
        if record.tier is EvidenceTier.TIER_1B
    )


def _no_qualifying_violation(
    capability_id: str,
    governing: Authority | None,
    assessments: tuple[Tier1BAssessment, ...],
) -> str:
    """Say what exists and why none of it counts - not "no evidence"."""
    listed = ", ".join(
        f"{a.evidence_id} ({_authority_name(a.evidence_authority)})"
        for a in assessments
    )
    if governing is None:
        source = CAPABILITY_MATRIX[capability_id].regulatory_source
        headline = (
            f"capability {capability_id} names no canonical governing "
            f"authority (its regulatory source reads {source.authority!r}), so "
            f"no tier-1B evidence can qualify it. Tier 1B evidence exists: "
            f"{listed}."
        )
    else:
        headline = f"capability {capability_id} is governed by {governing}."
        # Said only when it is true of every record. An FDA record that is
        # merely pending is FROM the governing authority, and a message
        # claiming otherwise would send the reviewer to the wrong problem.
        if all(a.evidence_authority is not governing for a in assessments):
            headline += (
                f" Tier 1B evidence exists, but none is from the governing "
                f"authority {governing}."
            )
        headline += (
            f" Tier 1B evidence held: {listed}; no qualifying {governing} "
            f"tier-1B regulator-published numerical evidence exists."
        )
    reasons = "; ".join(f"{a.evidence_id}: {a.reason}" for a in assessments)
    return f"VALIDATED without qualifying tier-1B evidence. {headline} {reasons}."


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
    #: Tier-1B records the capability holds that do NOT qualify it - another
    #: regulator's numbers, most importantly. Listed so a passing result does
    #: not hide them and a failing one does not read as "no evidence".
    supporting_evidence: tuple[str, ...] = ()

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
            if result.supporting_evidence:
                lines.append(
                    "         supporting, not qualifying: "
                    + ", ".join(result.supporting_evidence)
                )
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
    if not evidence_for(capability_id):
        violations.append("VALIDATED with no evidence record at all.")

    governing = record.governing_authority
    assessments = assess_tier_1b(capability_id)
    qualifying = [a for a in assessments if a.qualifies]
    supporting = tuple(a.evidence_id for a in assessments if not a.qualifies)

    if not assessments:
        violations.append(
            "VALIDATED without tier-1B evidence. A regulator's own published "
            "numbers are the bar; an attested algorithm (1A) and an "
            "independent implementation agreeing (3) are not substitutes."
        )
    elif not qualifying:
        violations.append(
            _no_qualifying_violation(capability_id, governing, assessments)
        )
    else:
        satisfied.append(f"{len(assessments)} tier-1B record(s)")
        satisfied.append("tier-1B evidence passed")
        satisfied.append(
            f"governed by {governing}; qualifying {governing} tier-1B "
            "regulator-published evidence: "
            + ", ".join(a.evidence_id for a in qualifying)
        )

    # SOURCE PINNING, VIA THE ONE DEFINITION.
    #
    # This condition used to read `if not record.regulatory_source.
    # document_version`, so `document_version = "current"` passed it - a
    # non-empty string - while the provenance layer correctly excluded the
    # same citation from its pinned count. One concept, two encodings, and the
    # weaker of the two sat on the control that decides whether something may
    # be called VALIDATED.
    #
    # It now calls `record.has_pinned_source`, which is
    # `dossier.citations.is_pinned`, which is also what
    # `ConstantRecord.has_pinned_citation` calls. There is one definition.
    if not record.has_pinned_source:
        exception = record.source_citation_exception
        if exception is not None:
            # A DECLARED gap is still a gap. Naming the finding here comes
            # from the citation registry, so this module hard-codes no
            # finding id and a new exception is reported without editing it.
            violations.append(
                "VALIDATED with an unresolved regulatory-source citation "
                f"exception: {exception.tracked_as}. {exception.reason} "
                f"{exception.resolution}"
            )
        else:
            reasons = "; ".join(why_not_pinned(record.regulatory_source))
            violations.append(
                f"VALIDATED against an unpinned regulatory source ({reasons}). "
                "A citation has to be somewhere a reader can look: FDA's 2001 "
                "and 2026 guidances share a title and disagree."
            )
    else:
        satisfied.append(
            f"source pinned to {record.regulatory_source.section!r}, "
            f"{record.regulatory_source.document_version!r}"
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
        supporting_evidence=supporting,
    )


#: Capabilities whose VALIDATED status has been reviewed and recorded.
#:
#: Three EMA capabilities, promoted on tier-1B evidence in the ABEL release.
#: Adding a name here is the deliberate act condition 6 requires; it is a
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

    It inherits condition 2d by calling the gate rather than restating it: a
    capability claiming VALIDATED on another regulator's numbers fails the
    gate, and so it appears here with the gate's own explanation.
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
