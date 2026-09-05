"""HTTP API for the statistical capability surface.

WHAT THESE ROUTES ARE FOR

A customer, an internal reviewer or an auditor asking what this engine can be
trusted with. Not "what is the answer for my study" - that is the calculation
path, which these routes never touch.

WHY THEY NEED NO DATABASE

Everything served here comes from `be_stats.dossier`, which is code. So the
capability surface stays available in a degraded deployment where Supabase is
unreachable - which is the deployment where somebody is most likely to be
asking what still works.

WHY THEY STILL REQUIRE AUTHENTICATION

The content is not secret and the product is not public. Consistency with every
other route is worth more than saving a customer one token; an endpoint that is
open because nobody thought about it is how an authorisation model erodes.

THE ONE RULE

No route here writes anything, and no route here can change a validation
status. Promotion is a governed statistical change made by a named reviewer -
see the SAS validation workflow - and there is deliberately no HTTP verb in
this module that could take part in one.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from be_stats import __version__ as be_stats_version
from be_stats.dossier import (
    BLOCKERS,
    CAPABILITY_MATRIX,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
    REFUSALS,
    ROUTING_MATRIX,
    UNSUPPORTED_COMBINATION,
    Audience,
    best_tier_for,
    build_validation_report,
    certification_blockers,
    check_release_gate,
    display_status,
    explain_capability,
    method_catalogue,
    open_findings,
    provenance_coverage,
    render_report_html,
    render_report_markdown,
)
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from app.auth import AuthenticatedUser, current_user
from app.statistics.schemas import (
    BlockerRow,
    CapabilityRow,
    DossierSummary,
    ExplanationResponse,
    FindingRow,
    MethodCatalogueEntry,
    ProvenanceCoverage,
    RefusalRow,
    RoutingRow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/statistics", tags=["statistics"])


def _catalogue_entries() -> list[MethodCatalogueEntry]:
    return [
        MethodCatalogueEntry(
            capability_id=entry.capability_id,
            jurisdiction=entry.jurisdiction,
            method=entry.method,
            design=entry.design,
            supported_endpoints=entry.supported_endpoints,
            status=str(entry.status),
            qualification=entry.qualification,
            key_limitation=entry.key_limitation,
            regulatory_source=entry.regulatory_source,
        )
        for entry in method_catalogue()
    ]


@router.get("/methods", response_model=list[MethodCatalogueEntry])
async def list_methods(user: AuthenticatedUser = Depends(current_user)):
    """The user-facing catalogue: three states, one qualification each.

    Deliberately short. The full matrix is a separate endpoint because a
    twenty-three row table answers a reviewer's question by burying a
    customer's.
    """
    return _catalogue_entries()


@router.get("/capabilities", response_model=list[CapabilityRow])
async def list_capabilities(user: AuthenticatedUser = Depends(current_user)):
    """The full matrix, for a reviewer."""
    return [
        CapabilityRow(
            capability_id=record.capability_id,
            title=record.title,
            jurisdiction=str(record.jurisdiction) if record.jurisdiction else None,
            method=str(record.method) if record.method else None,
            implementation_status=str(record.implementation_status),
            validation_status=str(record.validation_status),
            display_status=str(display_status(record.validation_status)),
            evidence_tier=str(best_tier_for(record.capability_id)),
            design_requirement=[str(d) for d in record.design_requirement],
            endpoints=[str(e) for e in record.endpoints],
            decision_supported=record.decision_supported,
            known_limitations=list(record.known_limitations),
            refusal_conditions=[str(c) for c in record.refusal_conditions],
            regulatory_source=str(record.regulatory_source),
            source_version=record.source_version,
        )
        for record in CAPABILITY_MATRIX.values()
    ]


@router.get("/routing", response_model=list[RoutingRow])
async def list_routes(user: AuthenticatedUser = Depends(current_user)):
    """Which regulatory test applies, including the unsupported case.

    The unsupported row is included rather than omitted. A combination that
    refuses has a documented behaviour, and leaving it out of the table would
    let a reader assume something reasonable happens.
    """
    return [
        RoutingRow(
            route_id=route.route_id,
            jurisdiction=str(route.jurisdiction),
            drug_class=str(route.drug_class),
            endpoints=[str(e) for e in route.endpoints],
            input_classification=route.input_classification,
            design_requirement=[str(d) for d in route.design_requirement],
            method=str(route.method) if route.method else None,
            decision_rule=route.decision_rule,
            refusal_behaviour=route.refusal_behaviour,
            raises=route.raises,
            refusal_conditions=[str(c) for c in route.refusal_conditions],
        )
        for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION)
    ]


@router.get("/refusals", response_model=list[RefusalRow])
async def list_refusals(user: AuthenticatedUser = Depends(current_user)):
    """Every reason this engine declines to produce a regulatory decision."""
    return [
        RefusalRow(
            code=str(reason.code),
            summary=reason.summary,
            lifted_by=reason.lifted_by,
            source=reason.source,
        )
        for reason in REFUSALS.values()
    ]


@router.get("/dossier", response_model=DossierSummary)
async def dossier_summary(user: AuthenticatedUser = Depends(current_user)):
    """One response for a status page.

    `certification_blockers` is included on purpose and is the field most
    likely to be misread as noise. It lists claims that are NOT currently
    established - most often because an external oracle environment was not
    available - and an empty list is a strong statement rather than a quiet
    default.
    """
    counts: dict[str, int] = {}
    for record in CAPABILITY_MATRIX.values():
        key = str(record.validation_status)
        counts[key] = counts.get(key, 0) + 1

    return DossierSummary(
        be_stats_version=be_stats_version,
        capability_counts=counts,
        catalogue=_catalogue_entries(),
        provenance=ProvenanceCoverage(**provenance_coverage()),
        open_findings=[
            FindingRow(
                finding_id=finding.finding_id,
                severity=str(finding.severity),
                status=str(finding.status),
                affected_capabilities=list(finding.affected_capabilities),
                description=finding.description,
                resolution_condition=finding.resolution_condition,
            )
            for finding in open_findings()
        ],
        blockers=[
            BlockerRow(
                blocker_id=blocker.blocker_id,
                status=str(blocker.status),
                affected_capabilities=list(blocker.affected_capabilities),
                summary=blocker.summary,
                required_evidence=blocker.required_evidence,
                current_behaviour=blocker.current_behaviour,
            )
            for blocker in BLOCKERS.values()
        ],
        partial_oracle_ready=PARTIAL_ORACLE_READY,
        real_sas_oracle_status=REAL_SAS_ORACLE_STATUS,
        release_gate_passed=check_release_gate().passed,
        certification_blockers=certification_blockers(),
    )


@router.get("/validation-report")
async def validation_report(
    format: str = "json",
    user: AuthenticatedUser = Depends(current_user),
):
    """The exportable validation report, in one of three renderings.

    ONE ENDPOINT, NOT THREE, AND ONE REPORT OBJECT BEHIND ALL OF THEM.

    `?format=json|markdown|html`. A separate route per format would be three
    places to forget a governance rule; here the report is assembled once by
    `build_validation_report` and the renderers only read it. The UI consumes
    the JSON, so the page and the exported document cannot disagree.

    WHY IT DOES NOT EXTEND `/dossier`

    `/dossier` is a summary sized for a status page - counts, the catalogue,
    open findings. This is a document: every capability with its explainability
    answers, every constant with its provenance, evidence grouped by tier, and
    the qualifications that make each status mean something. Folding it into
    `/dossier` would make the page's payload an order of magnitude larger to
    serve a different question.

    AUDIENCE IS FIXED SERVER-SIDE.

    Always `REVIEWER`. The internal audience carries candidate values for the
    unresolved partial-replicate question, and a client must not be able to ask
    for them - a query parameter selecting the audience would be exactly that.
    Internal QA reads them through `build_bundle`, which never leaves the
    repository.
    """
    if format not in ("json", "markdown", "html"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown format {format!r}. Use json, markdown or html.",
        )

    report = build_validation_report(
        audience=Audience.REVIEWER,
        git_sha=os.environ.get("VERCEL_GIT_COMMIT_SHA") or None,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    name = f"be-stats-validation-report-{stamp}"

    if format == "json":
        return JSONResponse(
            content=report.to_dict(),
            headers={
                "Content-Disposition": f'attachment; filename="{name}.json"'
            },
        )
    if format == "markdown":
        return PlainTextResponse(
            render_report_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
        )
    return HTMLResponse(render_report_html(report))


@router.get("/capabilities/{capability_id}/explain", response_model=ExplanationResponse)
async def explain(
    capability_id: str,
    user: AuthenticatedUser = Depends(current_user),
):
    """The nine questions, answered for one capability.

    A capability that is not implemented answers them too - with a refusal
    code and what would lift it - rather than returning 404. A 404 says "we
    have never heard of this", which is a different and less useful thing to
    tell somebody whose study just came back undecided.
    """
    if capability_id not in CAPABILITY_MATRIX:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No capability {capability_id!r}.",
        )

    explanation = explain_capability(capability_id)
    return ExplanationResponse(
        capability_id=capability_id,
        outcome=str(explanation.outcome),
        decided=explanation.decided,
        passes=explanation.passes,
        method=str(explanation.method) if explanation.method else None,
        selection_reason=explanation.selection_reason,
        jurisdiction=(
            str(explanation.jurisdiction) if explanation.jurisdiction else None
        ),
        design=explanation.design,
        criterion=explanation.criterion,
        regulatory_source=explanation.regulatory_source,
        validation_status=(
            str(explanation.validation_status)
            if explanation.validation_status
            else None
        ),
        implementation_status=(
            str(explanation.implementation_status)
            if explanation.implementation_status
            else None
        ),
        evidence_tier=str(explanation.evidence_tier),
        limitations=list(explanation.limitations),
        refusal_code=(
            str(explanation.refusal.code) if explanation.refusal else None
        ),
        refusal_summary=(
            explanation.refusal.summary if explanation.refusal else None
        ),
        refusal_lifted_by=(
            explanation.refusal.lifted_by if explanation.refusal else None
        ),
        findings=list(explanation.findings),
        blockers=list(explanation.blockers),
        submission_ready=explanation.submission_ready,
        rendered=str(explanation),
    )
