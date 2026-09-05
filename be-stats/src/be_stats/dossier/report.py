"""The validation report: the dossier, arranged for somebody outside the team.

WHY THIS IS NOT `bundle.py`

`build_bundle` already assembles everything for internal QA, and it is the
right thing for that job. It is the wrong thing to hand a customer, for one
concrete reason: it contains the candidate partial-replicate denominator
degrees of freedom. Those are a live statistical question recorded in a blocker
beside the reason each candidate is insufficient - exactly where a reviewer of
this package should see them, and exactly where a customer should not. A number
in a customer document stops being a candidate and starts being a
specification.

So there are two audiences and one truth. `Audience.INTERNAL` is the QA view;
`Audience.REVIEWER` is what leaves the building. Both are built from the same
canonical objects in `be_stats.dossier`, and neither re-states a status.

WHAT THIS MODULE MAY NOT DO

Assemble regulatory truth. Every status here is READ from `spec` through the
capability matrix; every explanation comes from `explain_capability`; every
tier comes from the evidence manifest; every constant from the provenance
index. If a fact appears in this file as a literal, it is a bug - the whole
dossier exists because a second copy of a regulatory claim is how a product
ends up telling a customer one thing and an auditor another.

THE ONE SENTENCE THIS REPORT MUST NEVER LET A READER BELIEVE

That an implemented method is a validated one. `IMPLEMENTED_UNVALIDATED` means
the code runs and no regulator's published output has been reproduced through
it. Tier 1B is the numerical evidence a `VALIDATED` promotion requires and is
not sufficient for one; the release gate weighs several further conditions.
Every capability section states its qualification, and
`tests/validation/test_validation_report.py` fails if any of that is softened.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from be_stats import __version__
from be_stats.dossier.blockers import (
    BLOCKERS,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
    blockers_for,
    open_blockers,
)
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.catalogue import CATALOGUE_IDS, catalogue_entry, display_status
from be_stats.dossier.citations import why_not_pinned
from be_stats.dossier.constants import (
    CONSTANT_INDEX,
    ConstantKind,
    provenance_coverage,
    unpinned_normative_constants,
)
from be_stats.dossier.evidence import (
    EVIDENCE_MANIFEST,
    EvidenceStatus,
    best_tier_for,
    evidence_for,
)
from be_stats.dossier.explain import explain_capability
from be_stats.dossier.findings import findings_for, open_findings
from be_stats.dossier.refusals import refusal
from be_stats.dossier.release_gate import certification_blockers, check_release_gate
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import ValidationStatus

#: The report's own schema. Bumped when a field changes meaning, so a consumer
#: can tell a new report from a differently-shaped one.
REPORT_SCHEMA = "be-stats.validation-report/1"


class Audience(StrEnum):
    """Who the report is being prepared for. Changes what is INCLUDED only.

    It never changes a status, a tier, or an evidence outcome. A reviewer
    report and an internal report disagree about detail and never about fact -
    `test_the_two_audiences_never_disagree_about_a_status` holds that.
    """

    #: A customer, auditor, statistician or regulatory reviewer outside the
    #: team. Excludes candidate values for unresolved statistical questions.
    REVIEWER = "reviewer"
    #: Internal QA. Includes the candidate evidence recorded against each
    #: blocker, each beside the reason it is insufficient.
    INTERNAL = "internal"


#: Said once, quoted wherever the distinction is made, so the wording cannot
#: drift between the JSON, the Markdown, the HTML and the UI.
TIER_RULE = (
    "Tier 1A is conformance to the regulator's stated algorithm or decision "
    "rule. Tier 1B is reproduction of a regulator's own published numerical "
    "output. Tier 1B is the numerical evidence a VALIDATED promotion "
    "requires, and neither tier alone establishes VALIDATED status or "
    "submission suitability: the release gate also requires a pinned "
    "regulatory source, evidence that passed rather than skipped or pending, "
    "no disqualifying finding, no blocker naming the capability, and an "
    "explicitly reviewed transition."
)

ORACLE_RULE = (
    "PowerTOST and ReplicateBE.jl are independent implementations. Agreement "
    "with them is engineering evidence that the arithmetic is right; it is "
    "not regulatory authority and does not substitute for a regulator's own "
    "published output."
)

SKIPPED_RULE = (
    "A comparison whose external environment was unavailable is reported as "
    "skipped, never as passed. A validation that did not run is "
    "indistinguishable from one that would have failed."
)

TENANCY_NOTE = (
    "This report describes the calculation engine, not any customer's study "
    "data. It contains no study, subject, or tenant data of any kind, and is "
    "identical for every caller. Prepared for tenant isolation; this "
    "deployment is single-organisation."
)


# ------------------------------------------------------------ identity ---


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unavailable"


@dataclass(frozen=True, slots=True)
class ReportIdentity:
    """Where this document came from. GENERATED metadata, not evidence.

    Kept in its own section, and labelled, because a timestamp and a git SHA
    sitting beside a regulatory citation invite a reader to weigh them the
    same way. One says which build produced the document; the other is the
    claim the document is about.
    """

    schema: str
    be_stats_version: str
    git_sha: str
    generated_at: str
    audience: Audience
    #: Runtime facts. Present for reproducibility and explicitly NOT evidence.
    runtime: dict[str, str] = field(default_factory=dict)
    note: str = (
        "Everything in this section is generated at export time and describes "
        "the build, not the regulatory evidence. Nothing here supports or "
        "qualifies any validation claim."
    )


# ---------------------------------------------------------- capability ---


@dataclass(frozen=True, slots=True)
class CapabilitySection:
    """One capability, as a reviewer needs to read it."""

    capability_id: str
    method: str
    jurisdiction: str
    design: str
    endpoints: str
    implementation_status: str
    validation_status: str
    display_status: str
    decision_supported: bool
    #: The sentence that makes the status mean something.
    qualification: str
    regulatory_source: str
    source_version: str
    source_pinned: bool
    #: Why the source is not pinned, when it is not. Empty otherwise.
    source_pinning_gap: str
    citation_exception: str
    #: The strongest tier ESTABLISHED - pending and skipped contribute nothing.
    established_evidence_tier: str
    evidence: list[dict[str, str]]
    blockers: list[str]
    open_findings: list[str]
    refusal_conditions: list[dict[str, str]]
    #: The nine explainability answers, from `explain_capability`.
    explainability: dict[str, Any]
    submission_ready: bool
    #: What a passing result from this does NOT establish.
    does_not_establish: str


def _refusal_rows(record) -> list[dict[str, str]]:
    return [
        {
            "code": str(code),
            "meaning": refusal(code).summary,
            "lifted_by": refusal(code).lifted_by,
        }
        for code in record.refusal_conditions
    ]


def _evidence_rows(capability_id: str) -> list[dict[str, str]]:
    """Every evidence record for a capability, with its tier NEVER collapsed.

    `tier` and `status` stay separate fields and separate words. A single
    "validated by PowerTOST" string would merge an independent implementation
    into a regulatory claim, which is the error `ORACLE_RULE` exists to name.
    """
    return [
        {
            "evidence_id": record.evidence_id,
            "tier": str(record.tier),
            "tier_meaning": _TIER_MEANING[record.tier],
            "source_type": str(record.source_type),
            "source_authority": record.source_authority,
            "status": str(record.status),
            "scenario": record.scenario,
            "tolerance": record.tolerance,
            "established_by": record.established_by,
        }
        for record in evidence_for(capability_id)
    ]


_TIER_MEANING: dict[EvidenceTier, str] = {
    EvidenceTier.TIER_1A: "regulator's stated algorithm or decision rule",
    EvidenceTier.TIER_1B: "regulator's own published numerical output",
    EvidenceTier.TIER_2: "published textbook or reference dataset",
    EvidenceTier.TIER_3: (
        "independent implementation - engineering evidence, not regulatory "
        "authority"
    ),
    EvidenceTier.TIER_4: "internal simulation or structural check",
    EvidenceTier.NONE: "no evidence established",
}


def _does_not_establish(record) -> str:
    """Stated for every capability, including the validated ones.

    The field exists so that no section can be read as an unqualified
    endorsement. A VALIDATED capability still does not validate the wiring
    around it, and an unvalidated one does not become validated by having
    tier-3 agreement.
    """
    status = record.validation_status
    if status is ValidationStatus.NOT_IMPLEMENTED:
        return (
            "This capability produces no regulatory decision. A study routed "
            "here is refused with a named reason; it is neither a pass nor a "
            "fail."
        )
    if status is ValidationStatus.VALIDATED:
        return (
            "Reproducing the regulator's published output for this component "
            "does not validate the procedure assembled around it, and does "
            "not by itself make a result submission-ready."
        )
    if status is ValidationStatus.IMPLEMENTED:
        return (
            "This is structural conformance. It produces no number for a "
            "regulator to disagree with, so it establishes nothing about "
            "numerical agreement."
        )
    return (
        "No regulator's published numerical output has been reproduced "
        "through this path. It computes a result; it does not establish that "
        "the result is the one the regulator would compute, and it is not "
        "submission-ready."
    )


def _capability_section(capability_id: str) -> CapabilitySection:
    record = CAPABILITY_MATRIX[capability_id]
    entry = catalogue_entry(capability_id) if capability_id in CATALOGUE_IDS else None
    exception = record.source_citation_exception
    explanation = explain_capability(capability_id)

    return CapabilitySection(
        capability_id=capability_id,
        method=record.title,
        jurisdiction=str(record.jurisdiction) if record.jurisdiction else "FDA / EMA",
        design=", ".join(str(d) for d in record.design_requirement) or "any",
        endpoints=", ".join(str(e) for e in record.endpoints),
        implementation_status=str(record.implementation_status),
        validation_status=str(record.validation_status),
        display_status=str(display_status(record.validation_status)),
        decision_supported=record.decision_supported,
        qualification=(
            entry.qualification if entry else _does_not_establish(record)
        ),
        regulatory_source=str(record.regulatory_source),
        source_version=record.source_version,
        source_pinned=record.has_pinned_source,
        source_pinning_gap=(
            "; ".join(why_not_pinned(record.regulatory_source))
            if not record.has_pinned_source
            else ""
        ),
        citation_exception=(
            f"{exception.reason} Tracked as {exception.tracked_as}."
            if exception
            else ""
        ),
        established_evidence_tier=str(best_tier_for(capability_id)),
        evidence=_evidence_rows(capability_id),
        blockers=[b.blocker_id for b in blockers_for(capability_id)],
        open_findings=[f.finding_id for f in findings_for(capability_id) if f.is_open],
        refusal_conditions=_refusal_rows(record),
        explainability={
            "method_selected": (
                str(explanation.method) if explanation.method else "none"
            ),
            "why_selected": explanation.selection_reason,
            "regulator": explanation.jurisdiction or "not jurisdiction-specific",
            "design": explanation.design,
            "criterion": explanation.criterion,
            "regulatory_source": explanation.regulatory_source,
            "validation_status": str(explanation.validation_status or "n/a"),
            "implementation_status": str(explanation.implementation_status or "n/a"),
            "evidence_tier_established": str(explanation.evidence_tier),
            "limitations": list(explanation.limitations),
            "outcome": str(explanation.outcome),
            "refusal": (
                {
                    "code": str(explanation.refusal.code),
                    "why": explanation.refusal.summary,
                    "lifted_by": explanation.refusal.lifted_by,
                }
                if explanation.refusal
                else None
            ),
        },
        submission_ready=explanation.submission_ready,
        does_not_establish=_does_not_establish(record),
    )


# ----------------------------------------------------------- the report ---


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The canonical report object. Renderers read it; nothing else builds it."""

    identity: ReportIdentity
    #: How to read tiers, oracles and skipped comparisons. Quoted, not
    #: paraphrased, by every renderer.
    reading_notes: dict[str, str]
    capabilities: list[CapabilitySection]
    #: Evidence grouped by tier, never merged into a single "validated by".
    evidence_by_tier: dict[str, list[dict[str, str]]]
    provenance: dict[str, Any]
    limitations: dict[str, Any]
    governance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Deterministic JSON. Key order is the declaration order above."""
        from dataclasses import asdict

        return {
            "schema": self.identity.schema,
            "identity": asdict(self.identity) | {"audience": str(self.identity.audience)},
            "reading_notes": self.reading_notes,
            "capabilities": [asdict(section) for section in self.capabilities],
            "evidence_by_tier": self.evidence_by_tier,
            "provenance": self.provenance,
            "limitations": self.limitations,
            "governance": self.governance,
        }


def _evidence_by_tier() -> dict[str, list[dict[str, str]]]:
    """Grouped by tier, in tier order, with every group present.

    An absent group and an empty one look identical in a report, and only one
    of them means somebody checked - so tier 2, which this package genuinely
    has none of, appears as an explicit empty list.
    """
    grouped: dict[str, list[dict[str, str]]] = {}
    for tier in (
        EvidenceTier.TIER_1A,
        EvidenceTier.TIER_1B,
        EvidenceTier.TIER_2,
        EvidenceTier.TIER_3,
        EvidenceTier.TIER_4,
    ):
        grouped[str(tier)] = [
            {
                "evidence_id": record.evidence_id,
                "tier_meaning": _TIER_MEANING[tier],
                "source_authority": record.source_authority,
                "status": str(record.status),
                "scenario": record.scenario,
                "expected": record.expected,
                "observed": record.observed,
                "tolerance": record.tolerance,
                "capabilities": list(record.capabilities),
                "established_by": record.established_by,
            }
            for record in EVIDENCE_MANIFEST
            if record.tier is tier
        ]
    return grouped


def _provenance_section() -> dict[str, Any]:
    coverage = provenance_coverage()
    return {
        "coverage": coverage,
        "note": (
            "Counted separately by kind. A derived value carries no regulatory "
            "section because no regulator states it; a normative value without "
            "one is outstanding work. `normative_pinned` is the only figure "
            "counting document sections, and its denominator is the normative "
            "set."
        ),
        "normative": [
            {
                "constant_id": record.constant_id,
                "value": record.value,
                "authority": record.citation.authority,
                "document": record.document,
                "section": record.section or "",
                "document_version": record.document_version,
                "verification": str(record.verification),
                "role": record.role,
                "pinned": record.has_pinned_citation,
                "citation_exception": record.citation_exception,
            }
            for record in CONSTANT_INDEX.values()
            if record.kind is ConstantKind.NORMATIVE
        ],
        "derived": [
            {
                "constant_id": record.constant_id,
                "value": record.value,
                "derivation": record.derivation,
                "derived_from": list(record.derived_from),
                "verification": str(record.verification),
                "role": record.role,
                "consumed_by": list(record.consumed_by),
            }
            for record in CONSTANT_INDEX.values()
            if record.kind is ConstantKind.DERIVED
        ],
        "illustrative": [
            {
                "constant_id": record.constant_id,
                "value": record.value,
                "role": record.role,
                "consumed_by": list(record.consumed_by),
            }
            for record in CONSTANT_INDEX.values()
            if record.kind is ConstantKind.ILLUSTRATIVE
        ],
        "unresolved_citation_gaps": [
            {
                "constant_id": record.constant_id,
                "why": record.citation_exception,
            }
            for record in unpinned_normative_constants()
        ],
    }


def _finding_row(finding, audience: Audience) -> dict[str, str]:
    """One finding, phrased for its audience.

    A finding tied to a BLOCKER is described by the blocker's summary for a
    reviewer. That is not a second copy of the finding: it is the same fact,
    and it is the phrasing that does not carry the candidate denominator
    degrees of freedom recorded in the finding's own description. Internal
    readers get the description, where those candidates belong.
    """
    if audience is Audience.INTERNAL or not finding.blocker_id:
        description = finding.description
    else:
        description = BLOCKERS[finding.blocker_id].summary
    return {
        "finding_id": finding.finding_id,
        "severity": str(finding.severity),
        "status": str(finding.status),
        "affected_capabilities": list(finding.affected_capabilities),
        "description": description,
        "resolution_condition": finding.resolution_condition,
    }


def _blocker_row(blocker, audience: Audience) -> dict[str, Any]:
    row: dict[str, Any] = {
        "blocker_id": blocker.blocker_id,
        "status": str(blocker.status),
        "affected_capabilities": list(blocker.affected_capabilities),
        "summary": blocker.summary,
        "required_evidence": blocker.required_evidence,
        "current_behaviour": blocker.current_behaviour,
    }
    if audience is Audience.INTERNAL:
        # Candidate values live here, each beside the reason it is
        # insufficient. They are a live statistical question and stay inside.
        row["candidate_evidence"] = [
            {
                "source": candidate.source,
                "establishes": candidate.establishes,
                "insufficient_because": candidate.insufficient_because,
            }
            for candidate in blocker.candidate_evidence
        ]
    return row


def _limitations(audience: Audience) -> dict[str, Any]:
    unavailable = [
        {
            "evidence_id": record.evidence_id,
            "tier": str(record.tier),
            "status": str(record.status),
            "why": record.software_environment,
        }
        for record in EVIDENCE_MANIFEST
        if record.status
        in (
            EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE,
            EvidenceStatus.PENDING,
            EvidenceStatus.NOT_AVAILABLE,
        )
    ]
    return {
        "open_findings": [_finding_row(f, audience) for f in open_findings()],
        "open_blockers": [_blocker_row(b, audience) for b in open_blockers()],
        "unresolved_citation_gaps": [
            record.constant_id for record in unpinned_normative_constants()
        ],
        "evidence_not_established": unavailable,
        "certification_blockers": certification_blockers(),
        "note": (
            "Everything in this section is outstanding work. A claim that is "
            "not currently established is listed here rather than inferred "
            "from its absence elsewhere."
        ),
    }


def _governance() -> dict[str, Any]:
    gate = check_release_gate()
    return {
        "release_gate_passed": gate.passed,
        "release_gate_meaning": (
            "The gate checks that each capability's CLAIMED status is "
            "supportable by the evidence recorded. Passing means no capability "
            "claims more than its evidence carries; it does not mean every "
            "capability is validated."
        ),
        "partial_oracle_ready": PARTIAL_ORACLE_READY,
        "real_sas_oracle_status": REAL_SAS_ORACLE_STATUS,
        "promotion_policy": (
            "No automated process promotes a capability to VALIDATED. A "
            "promotion requires tier-1B evidence that passed, a pinned "
            "regulatory source, no disqualifying finding or blocker, and a "
            "named reviewer recording the transition. AI assistance may "
            "explain evidence and may never approve a promotion."
        ),
        "tenancy": TENANCY_NOTE,
    }


def build_validation_report(
    *,
    audience: Audience = Audience.REVIEWER,
    git_sha: str | None = None,
    generated_at: str | None = None,
    capability_ids: tuple[str, ...] | None = None,
) -> ValidationReport:
    """Assemble the report from the canonical dossier objects.

    `capability_ids` defaults to EVERY capability rather than to the catalogue
    subset. A reviewer's question is "what is the state of this engine", and
    answering it with the seven rows a customer browses would omit the
    components whose limitations explain the methods' statuses.

    `generated_at` is injectable so a caller can produce a byte-identical
    report twice. That is not only for snapshots: a test scanning the report
    for stray numbers has to be able to hold the clock still, because an ISO
    timestamp contains `seconds.microseconds` and will eventually land inside
    any numeric range the test is looking for. One did.
    """
    ids = capability_ids if capability_ids is not None else tuple(CAPABILITY_MATRIX)

    return ValidationReport(
        identity=ReportIdentity(
            schema=REPORT_SCHEMA,
            be_stats_version=__version__,
            git_sha=git_sha if git_sha is not None else _git_sha(),
            generated_at=(
                generated_at
                if generated_at is not None
                else datetime.now(UTC).isoformat()
            ),
            audience=audience,
            runtime={
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
        ),
        reading_notes={
            "evidence_tiers": TIER_RULE,
            "independent_implementations": ORACLE_RULE,
            "unavailable_environments": SKIPPED_RULE,
            "status_meanings": (
                "NOT IMPLEMENTED - no regulatory decision is produced. "
                "IMPLEMENTED - VALIDATION PENDING - the method runs and no "
                "regulator-published output has been reproduced through it. "
                "VALIDATED - a regulator's own published output has been "
                "reproduced and the release gate's further conditions were "
                "met."
            ),
        },
        capabilities=[_capability_section(cid) for cid in ids],
        evidence_by_tier=_evidence_by_tier(),
        provenance=_provenance_section(),
        limitations=_limitations(audience),
        governance=_governance(),
    )
