"""The explainability contract: every decision answers for itself.

THE NINE QUESTIONS

A bioequivalence result that a reviewer cannot interrogate is not a result, it
is a number with a colour. So anything this engine produces - a verdict, a
refusal, a route selection - must be able to answer:

    1  what method was selected
    2  why that method
    3  which regulator and which profile
    4  which design
    5  which limits or criterion
    6  which regulatory source
    7  which validation status
    8  which limitations
    9  why it passed, failed, or refused

`Explanation` is that answer as an object. Its `to_lines()` renders the nine in
order, which is the order a reviewer asks them in, and its fields are separate
so a report can lay them out however it likes without re-parsing prose.

WHY A REFUSAL GETS THE SAME OBJECT

Question 9 has three answers and the third is the one that usually goes
missing. A path that produced no decision tends to return None, or an empty
result, or - worst - a `False`. Here it returns an `Explanation` whose
`outcome` is REFUSED and whose `refusal` names the code and what would lift
it. The unsupported path is the best-documented path in the system, because it
is the one where a reader is most likely to draw a wrong conclusion from
silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.dossier.blockers import blockers_for
from be_stats.dossier.capabilities import CAPABILITY_MATRIX, CapabilityRecord
from be_stats.dossier.evidence import best_tier_for
from be_stats.dossier.findings import findings_for
from be_stats.dossier.refusals import RefusalCode, RefusalReason, refusal
from be_stats.dossier.routing import RoutingRoute, route_for
from be_stats.dossier.statuses import (
    EvidenceTier,
    ImplementationStatus,
    is_submission_ready,
)
from be_stats.provenance import ValidationStatus
from be_stats.spec import DrugClass, Endpoint, Jurisdiction, Method


class Outcome(StrEnum):
    """What happened, kept strictly separate from whether it passed."""

    #: A regulatory decision was produced. `passes` then says which way.
    DECIDED = "decided"
    #: No regulatory decision was produced, and `refusal` says why. `passes`
    #: is None - never False. See `dossier.semantics`.
    REFUSED = "refused"
    #: Describing a capability or a route rather than reporting on a study.
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why this result is this result."""

    outcome: Outcome
    #: 1. The method selected, or None where none was.
    method: Method | None
    #: 2. Why that method, in the regulator's terms.
    selection_reason: str
    #: 3. The regulator.
    jurisdiction: Jurisdiction | None
    #: 3. The profile that selected the route.
    drug_class: DrugClass | None
    endpoint: Endpoint | None
    #: 4. The design required or observed.
    design: str
    #: 5. The limits or criterion applied.
    criterion: str
    #: 6. Document, section and version.
    regulatory_source: str
    #: 7. The validation status of the capability that produced this.
    validation_status: ValidationStatus | None
    implementation_status: ImplementationStatus | None
    #: 7. The strongest tier of evidence actually established.
    evidence_tier: EvidenceTier
    #: 8. What this does not cover.
    limitations: tuple[str, ...]
    #: 9. The verdict, when there is one. None for a refusal - and it is None
    #: rather than False, which is the difference between "no decision" and
    #: "the study failed".
    passes: bool | None
    #: 9. The refusal, when there is one.
    refusal: RefusalReason | None
    #: Findings a reader must see alongside this.
    findings: tuple[str, ...] = ()
    #: Blockers holding up whatever this could not do.
    blockers: tuple[str, ...] = ()
    #: Whether a filing may rest on this.
    submission_ready: bool = False

    @property
    def decided(self) -> bool:
        """The same `decided` every result type in this package carries.

        Present so an `Explanation` obeys the three-field contract rather than
        having its own richer-but-different vocabulary. `outcome` says more -
        it distinguishes a refusal from a description - and this narrows it to
        the one bit every consumer already knows how to read.
        """
        return self.outcome is Outcome.DECIDED

    def to_lines(self) -> list[str]:
        """The nine questions, in the order a reviewer asks them."""
        lines = [
            f"method:            {self.method or 'none selected'}",
            f"why:               {self.selection_reason}",
            f"regulator:         {self.jurisdiction or 'not jurisdiction-specific'}"
            f" / {self.drug_class or 'n/a'}"
            f" / {self.endpoint or 'all endpoints'}",
            f"design:            {self.design or 'not applicable'}",
            f"criterion:         {self.criterion}",
            f"source:            {self.regulatory_source}",
            f"validation:        {self.validation_status or 'n/a'}"
            f" (evidence {self.evidence_tier})",
            f"implementation:    {self.implementation_status or 'n/a'}",
        ]
        if self.limitations:
            lines.append("limitations:")
            lines += [f"  - {item}" for item in self.limitations]
        else:
            lines.append("limitations:       none recorded")

        if self.outcome is Outcome.REFUSED and self.refusal is not None:
            lines.append(f"outcome:           REFUSED - {self.refusal.code}")
            lines.append(f"  why:             {self.refusal.summary}")
            lines.append(f"  lifted by:       {self.refusal.lifted_by}")
            lines.append(
                "  note:            passes is null, NOT false. No regulatory "
                "decision was produced."
            )
        elif self.outcome is Outcome.DECIDED:
            verdict = {True: "PASS", False: "FAIL", None: "NOT DECIDED"}[self.passes]
            lines.append(f"outcome:           {verdict}")
        else:
            lines.append("outcome:           descriptive - no study was assessed")

        if self.findings:
            lines.append(f"findings:          {', '.join(self.findings)}")
        if self.blockers:
            lines.append(f"blockers:          {', '.join(self.blockers)}")
        lines.append(
            "submission ready:  "
            + ("yes" if self.submission_ready else "no - see validation status")
        )
        return lines

    def __str__(self) -> str:
        return "\n".join(self.to_lines())


def _source_line(record: CapabilityRecord) -> str:
    citation = record.regulatory_source
    parts = [citation.authority, citation.document]
    if citation.section:
        parts.append(citation.section)
    if citation.document_version:
        parts.append(f"({citation.document_version})")
    return ", ".join(parts)


def explain_capability(capability_id: str) -> Explanation:
    """Everything the dossier knows about one capability.

    DESCRIPTIVE: it reports on the capability, not on a study. A caller that
    mistakes this for a result would find `passes` is None and `outcome` says
    so in words.
    """
    record = CAPABILITY_MATRIX[capability_id]
    status = record.validation_status
    return Explanation(
        outcome=Outcome.DESCRIPTIVE,
        method=record.method,
        selection_reason=record.title,
        jurisdiction=record.jurisdiction,
        drug_class=None,
        endpoint=None,
        design=", ".join(str(d) for d in record.design_requirement) or "any",
        criterion=record.title,
        regulatory_source=_source_line(record),
        validation_status=status,
        implementation_status=record.implementation_status,
        evidence_tier=best_tier_for(capability_id),
        limitations=record.known_limitations,
        passes=None,
        refusal=(
            refusal(record.refusal_conditions[0])
            if status is ValidationStatus.NOT_IMPLEMENTED
            and record.refusal_conditions
            else None
        ),
        findings=tuple(f.finding_id for f in findings_for(capability_id)),
        blockers=tuple(b.blocker_id for b in blockers_for(capability_id)),
        submission_ready=is_submission_ready(status),
    )


def explain_route(
    jurisdiction: Jurisdiction,
    drug_class: DrugClass,
    endpoint: Endpoint = Endpoint.AUC,
) -> Explanation:
    """Why this combination routes where it routes - including nowhere.

    The unsupported case is the reason this function exists. It returns a full
    explanation rather than raising, so a product surface can SHOW the refusal
    with its reason instead of catching an exception and rendering a shrug.
    """
    route: RoutingRoute = route_for(jurisdiction, drug_class, endpoint)
    refused = route.method is None

    record = None
    if route.method is not None:
        record = next(
            (r for r in CAPABILITY_MATRIX.values() if r.source_key is route.method),
            None,
        )

    status = record.validation_status if record else None
    capability_id = record.capability_id if record else ""

    return Explanation(
        outcome=Outcome.REFUSED if refused else Outcome.DESCRIPTIVE,
        method=route.method,
        selection_reason=route.input_classification,
        jurisdiction=jurisdiction,
        drug_class=drug_class,
        endpoint=endpoint,
        design=", ".join(str(d) for d in route.design_requirement) or "not reached",
        criterion=route.decision_rule,
        regulatory_source=_source_line(record) if record else "none - no method selected",
        validation_status=status,
        implementation_status=record.implementation_status if record else None,
        evidence_tier=best_tier_for(capability_id) if capability_id else EvidenceTier.NONE,
        limitations=record.known_limitations if record else (route.refusal_behaviour,),
        passes=None,
        refusal=(
            refusal(route.refusal_conditions[0])
            if refused and route.refusal_conditions
            else None
        ),
        findings=tuple(f.finding_id for f in findings_for(capability_id))
        if capability_id
        else (),
        blockers=tuple(b.blocker_id for b in blockers_for(capability_id))
        if capability_id
        else (),
        submission_ready=is_submission_ready(status) if status else False,
    )


def explain_refusal(code: RefusalCode) -> Explanation:
    """A refusal on its own, for a surface that has a code and nothing else."""
    reason = refusal(code)
    return Explanation(
        outcome=Outcome.REFUSED,
        method=None,
        selection_reason="No method was selected.",
        jurisdiction=None,
        drug_class=None,
        endpoint=None,
        design="not reached",
        criterion="none applied",
        regulatory_source=reason.source or "not applicable",
        validation_status=None,
        implementation_status=None,
        evidence_tier=EvidenceTier.NONE,
        limitations=(reason.summary,),
        passes=None,
        refusal=reason,
    )
