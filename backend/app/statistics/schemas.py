"""Wire shapes for the statistical capability surface.

WHY THE STATUS IS TWO FIELDS ON THE WIRE TOO

It would be easy to send one string. The frontend would render it, the customer
would read it, and the two questions - does it run, may I rely on it - would be
answered by one word again, three layers away from where the distinction is
maintained. So the split survives to the client, and `display_status` is a
THIRD field derived from the validation status rather than a replacement for
it.

NOTHING HERE IS AUTHORED

Every value comes from `be_stats.dossier`. This module names types and does not
decide anything, which is why there is no place in it to write a status down.
"""

from __future__ import annotations

from pydantic import BaseModel


class MethodCatalogueEntry(BaseModel):
    """One row of the user-facing catalogue."""

    capability_id: str
    jurisdiction: str
    method: str
    design: str
    supported_endpoints: str
    #: One of VALIDATED, IMPLEMENTED - VALIDATION PENDING, NOT IMPLEMENTED.
    status: str
    qualification: str
    key_limitation: str
    regulatory_source: str


class CapabilityRow(BaseModel):
    """One row of the full matrix, for a reviewer rather than a user."""

    capability_id: str
    title: str
    jurisdiction: str | None
    method: str | None
    #: Two axes, kept apart all the way to the client.
    implementation_status: str
    validation_status: str
    display_status: str
    #: The strongest tier of evidence ACTUALLY ESTABLISHED - a pending or
    #: skipped comparison contributes nothing to it.
    evidence_tier: str
    design_requirement: list[str]
    endpoints: list[str]
    decision_supported: bool
    known_limitations: list[str]
    refusal_conditions: list[str]
    regulatory_source: str
    source_version: str


class RoutingRow(BaseModel):
    route_id: str
    jurisdiction: str
    drug_class: str
    endpoints: list[str]
    input_classification: str
    design_requirement: list[str]
    method: str | None
    decision_rule: str
    refusal_behaviour: str
    raises: str
    refusal_conditions: list[str]


class RefusalRow(BaseModel):
    code: str
    summary: str
    lifted_by: str
    source: str


class FindingRow(BaseModel):
    finding_id: str
    severity: str
    status: str
    affected_capabilities: list[str]
    description: str
    resolution_condition: str


class BlockerRow(BaseModel):
    blocker_id: str
    status: str
    affected_capabilities: list[str]
    summary: str
    required_evidence: str
    current_behaviour: str


class ProvenanceCoverage(BaseModel):
    total: int
    verified: int
    derived: int
    unverified: int
    normative: int
    illustrative: int


class DossierSummary(BaseModel):
    """The one response a status page needs."""

    be_stats_version: str
    #: Counts by validation status.
    capability_counts: dict[str, int]
    catalogue: list[MethodCatalogueEntry]
    provenance: ProvenanceCoverage
    open_findings: list[FindingRow]
    blockers: list[BlockerRow]
    #: False, and it stays false until real SAS evidence is accepted.
    partial_oracle_ready: bool
    real_sas_oracle_status: str
    release_gate_passed: bool
    #: Claims that are not currently established - a missing external oracle
    #: environment, or awaited evidence. Never empty by accident: an empty list
    #: means everything is established, which is a strong statement.
    certification_blockers: list[str]


class ExplanationResponse(BaseModel):
    """The nine questions, answered."""

    capability_id: str
    outcome: str
    decided: bool
    passes: bool | None
    method: str | None
    selection_reason: str
    jurisdiction: str | None
    design: str
    criterion: str
    regulatory_source: str
    validation_status: str | None
    implementation_status: str | None
    evidence_tier: str
    limitations: list[str]
    refusal_code: str | None
    refusal_summary: str | None
    refusal_lifted_by: str | None
    findings: list[str]
    blockers: list[str]
    submission_ready: bool
    #: The whole thing rendered, for a log or a report footer.
    rendered: str
