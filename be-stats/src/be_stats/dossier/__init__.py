"""The statistical validation dossier.

WHAT THIS PACKAGE IS

One canonical, machine-readable account of what `be-stats` can do, what has
been checked about it, against whose authority, and what remains unresolved -
plus the generators that turn it into documents nobody has to keep in sync by
hand.

WHAT IT IS NOT

A second copy of anything. Validation statuses live in `be_stats.spec` and are
READ here; regulatory constants live in `be_stats.provenance` and `be_stats.spec`
and are INDEXED here. Nothing in this package restates a fact that exists
elsewhere in the package, and the tests prove it: mutate a status in `spec` and
the matrix follows.

THE ONE RULE THIS PACKAGE ENFORCES ABOVE ALL OTHERS

Implemented is not validated. They are different axes with different
consequences, and any surface that shows one word for both is answering the
safety question with the engineering one.

    from be_stats.dossier import CAPABILITY_MATRIX, explain_capability

    record = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    record.implementation_status   # not_implemented
    record.validation_status       # not_implemented
    print(explain_capability(record.capability_id))
"""

from be_stats.dossier.blockers import (
    BLOCKERS,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
    Blocker,
    BlockerStatus,
    blockers_for,
    open_blockers,
)
from be_stats.dossier.bundle import build_bundle
from be_stats.dossier.capabilities import (
    CAPABILITY_MATRIX,
    CapabilityRecord,
    by_validation_status,
    capabilities_for,
    capability,
    decision_capabilities,
)
from be_stats.dossier.citations import (
    CITATION_EXCEPTIONS,
    CitationException,
    exception_for,
    is_pinned,
    names_one_authority,
    version_is_pinned,
    why_not_pinned,
)
from be_stats.dossier.catalogue import (
    CATALOGUE_IDS,
    CatalogueEntry,
    DisplayStatus,
    catalogue_entry,
    catalogue_for,
    display_status,
    method_catalogue,
)
from be_stats.dossier.constants import (
    CONSTANT_INDEX,
    ConstantKind,
    ConstantRecord,
    constant,
    constants_of_kind,
    provenance_coverage,
)
from be_stats.dossier.evidence import (
    EVIDENCE,
    EVIDENCE_MANIFEST,
    EvidenceRecord,
    EvidenceStatus,
    SourceType,
    best_tier_for,
    evidence_for,
    records_by_status,
)
from be_stats.dossier.explain import (
    Explanation,
    Outcome,
    explain_capability,
    explain_refusal,
    explain_route,
)
from be_stats.dossier.findings import (
    FINDINGS,
    FINDINGS_REGISTER,
    Finding,
    FindingSeverity,
    FindingStatus,
    blocking_findings,
    findings_for,
    open_findings,
)
from be_stats.dossier.refusals import (
    DIAGNOSTIC_FOR,
    REFUSALS,
    RefusalCode,
    RefusalReason,
    refusal,
)
from be_stats.dossier.release_gate import (
    REVIEWED_TRANSITIONS,
    GateResult,
    ReleaseGateReport,
    certification_blockers,
    check_capability,
    check_release_gate,
)
from be_stats.dossier.render import render_dossier
from be_stats.dossier.report import (
    REPORT_SCHEMA,
    Audience,
    CapabilitySection,
    ReportIdentity,
    ValidationReport,
    build_validation_report,
)
from be_stats.dossier.report_render import (
    render_report_html,
    render_report_markdown,
)
from be_stats.dossier.routing import (
    ROUTING_MATRIX,
    UNSUPPORTED_COMBINATION,
    RoutingRoute,
    route_for,
    routes_for,
)
from be_stats.dossier.semantics import (
    CONTRACT,
    SemanticsViolation,
    assert_result_semantics,
    check_result_semantics,
)
from be_stats.dossier.statuses import (
    SUBMISSION_READY,
    EvidenceTier,
    ImplementationStatus,
    implementation_status_of,
    is_submission_ready,
)

__all__ = [
    "Audience",
    "BLOCKERS",
    "Blocker",
    "BlockerStatus",
    "CAPABILITY_MATRIX",
    "CATALOGUE_IDS",
    "CITATION_EXCEPTIONS",
    "CONSTANT_INDEX",
    "CONTRACT",
    "CapabilityRecord",
    "CapabilitySection",
    "CatalogueEntry",
    "CitationException",
    "ConstantKind",
    "ConstantRecord",
    "DIAGNOSTIC_FOR",
    "DisplayStatus",
    "EVIDENCE",
    "EVIDENCE_MANIFEST",
    "EvidenceRecord",
    "EvidenceStatus",
    "EvidenceTier",
    "Explanation",
    "FINDINGS",
    "FINDINGS_REGISTER",
    "Finding",
    "FindingSeverity",
    "FindingStatus",
    "GateResult",
    "ImplementationStatus",
    "Outcome",
    "PARTIAL_ORACLE_READY",
    "REAL_SAS_ORACLE_STATUS",
    "REFUSALS",
    "REPORT_SCHEMA",
    "REVIEWED_TRANSITIONS",
    "ROUTING_MATRIX",
    "RefusalCode",
    "RefusalReason",
    "ReleaseGateReport",
    "ReportIdentity",
    "RoutingRoute",
    "SUBMISSION_READY",
    "SemanticsViolation",
    "SourceType",
    "UNSUPPORTED_COMBINATION",
    "ValidationReport",
    "assert_result_semantics",
    "best_tier_for",
    "blockers_for",
    "blocking_findings",
    "build_bundle",
    "build_validation_report",
    "by_validation_status",
    "capabilities_for",
    "capability",
    "catalogue_entry",
    "catalogue_for",
    "certification_blockers",
    "check_capability",
    "check_release_gate",
    "check_result_semantics",
    "constant",
    "constants_of_kind",
    "decision_capabilities",
    "display_status",
    "evidence_for",
    "exception_for",
    "explain_capability",
    "explain_refusal",
    "explain_route",
    "findings_for",
    "implementation_status_of",
    "is_pinned",
    "is_submission_ready",
    "method_catalogue",
    "names_one_authority",
    "open_blockers",
    "open_findings",
    "provenance_coverage",
    "records_by_status",
    "refusal",
    "render_dossier",
    "render_report_html",
    "render_report_markdown",
    "route_for",
    "routes_for",
    "version_is_pinned",
    "why_not_pinned",
]
