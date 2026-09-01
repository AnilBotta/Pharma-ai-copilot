"""The single document a reviewer reads before deciding, and its labels.

WHY THIS IS ASSEMBLED IN ONE PLACE

A reviewer deciding whether a SAS run is suitable oracle evidence has to hold
seven different kinds of fact in mind at once - which package, who ran it, what
was verified, what SAS reported, what a regulator published, what a model
thinks, and what any earlier reviewer decided. Assembled ad hoc on a screen,
those blur together, and the ones that blur first are exactly the ones that
matter: a candidate number starts to read like a published one.

So the report is built once, server-side, with every value carrying its own
provenance label, and the same structure serves the API, the screen and any
export.

THE LABELS ARE NOT DECORATION

    REGULATOR PUBLISHED      EMA published it. Authoritative for what it says.
    INDEPENDENT CANDIDATE    our own computation. NOT regulator-confirmed.
    EXTERNAL IMPLEMENTATION  another package's answer. NOT regulator-confirmed.

19.8906 and 22.5403 are both plausible denominator df values from different
methods, and neither is a target the SAS run is supposed to hit. A report that
printed either as "expected" would turn an open question into an answer key,
and the whole purpose of the first live run is to leave the question open until
SAS answers it.

WHAT THIS MODULE CANNOT DO

It reads. It does not decide, promote, or compute a statistic. No path here
touches a validation status, and it imports nothing from be_stats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.sas_validation.ai_reviewer import ADVISORY_LABEL
from app.sas_validation.attestation import ATTESTATION_LIMITATION, EvidenceOrigin
from app.sas_validation.human_review import ACCEPTANCE_MEANING

#: Printed at the head of any report built from a fixture. Loud, and first,
#: because the numbers below it will look exactly like real ones.
DRY_RUN_BANNER = (
    "OPERATIONAL DRY RUN - NOT SAS VALIDATION EVIDENCE. This run was recorded "
    "with evidence_origin = test_fixture. Nothing in it is regulatory "
    "evidence, whatever the values shown."
)

#: What an acceptance would and would not mean, carried on the report itself so
#: it travels with any copy of it.
DECISION_SEMANTICS = {
    "accepted_means": (
        "This evidence is accepted as suitable ORACLE EVIDENCE for the "
        "subsequent statistical implementation/validation task."
    ),
    "accepted_does_not_mean": [
        "the statistical method is implemented",
        "the statistical method is validated",
        "FDA has confirmed the denominator df",
        "partial_oracle_ready may be set true",
    ],
}


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    """Seven labelled sections. Absences are stated, not left blank."""

    run_id: str
    evidence_origin: EvidenceOrigin
    banner: str | None

    package: dict[str, Any]
    execution: dict[str, Any]
    integrity: dict[str, Any]
    statistics: dict[str, Any]
    reference_context: list[dict[str, Any]]
    ai_analysis: dict[str, Any] | None
    human_reviews: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_regulatory_evidence(self) -> bool:
        return self.evidence_origin.is_regulatory_evidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "evidence_origin": self.evidence_origin.value,
            "is_regulatory_evidence": self.is_regulatory_evidence,
            "banner": self.banner,
            "package": self.package,
            "execution": self.execution,
            "integrity": self.integrity,
            "statistics": self.statistics,
            "reference_context": self.reference_context,
            "ai_analysis": self.ai_analysis,
            "advisory_label": ADVISORY_LABEL,
            "human_reviews": self.human_reviews,
            "decision_semantics": DECISION_SEMANTICS,
            "acceptance_meaning": ACCEPTANCE_MEANING,
        }


def _origin(run: dict[str, Any]) -> EvidenceOrigin:
    """Read the declared origin, deferring to the acceptance gate's own rule.

    Imported from `workflow` rather than reimplemented, so the report and the
    gate can never disagree about what a run is. A second copy of this that
    drifted would put "MANUAL_EXTERNAL_SAS" at the top of a report for a run
    the gate was refusing as a fixture, which is the worst of both.

    Imported lazily because `workflow` imports this module.
    """
    from app.sas_validation.workflow import read_evidence_origin

    return read_evidence_origin(run)


def build_evidence_report(
    *,
    run: dict[str, Any],
    package: dict[str, Any],
    attestations: list[dict[str, Any]] | None = None,
    ai_review: dict[str, Any] | None = None,
    human_reviews: list[dict[str, Any]] | None = None,
) -> EvidenceReport:
    """Assemble the reviewer's document from stored facts only."""
    comparison = run.get("comparison") or {}
    integrity = comparison.get("integrity") or {}
    origin = _origin(run)
    attestations = attestations or []

    return EvidenceReport(
        run_id=str(run.get("id") or ""),
        evidence_origin=origin,
        banner=None if origin.is_regulatory_evidence else DRY_RUN_BANNER,
        package={
            "package_id": package.get("id"),
            "case_id": package.get("case_id"),
            "regulatory_method": package.get("regulatory_method"),
            "archive_sha256": package.get("archive_sha256"),
            "dataset_sha256": package.get("dataset_sha256"),
            "program_sha256": package.get("program_sha256"),
            "be_stats_version": package.get("be_stats_version"),
            "git_sha": package.get("git_sha"),
        },
        execution={
            "sas_version": run.get("sas_version") or "not reported",
            "execution_timestamp": run.get("execution_timestamp"),
            "uploaded_at": run.get("uploaded_at"),
            # A list, because a corrected attestation is a second one and both
            # are the record.
            "operator_attestations": [
                {
                    "operator_name": row.get("operator_name"),
                    "operator_organization": row.get("operator_organization"),
                    "operator_email": row.get("operator_email"),
                    "sas_version": row.get("sas_version"),
                    "operating_environment": row.get("operating_environment"),
                    "executed_at": row.get("executed_at"),
                    "attested_at": row.get("attested_at"),
                    "attestation_version": row.get("attestation_version"),
                    "attestation_hash": row.get("attestation_hash"),
                    "attestation_text": row.get("attestation_text"),
                }
                for row in attestations
            ],
            # PRESENT or ABSENT, said explicitly rather than left to be
            # inferred from an empty list. For a real SAS run the absence of an
            # attestation is something a reviewer should weigh - there is then
            # no record of who executed the package - and an empty section
            # reads as "nothing to report" rather than "nobody said".
            #
            # It is NOT a precondition. The reviewer weighs it; the machine
            # does not decide it, and nothing here manufactures one.
            "operator_attestation": "present" if attestations else "absent",
            "attestation_absent_note": (
                None
                if attestations
                else (
                    "No operator attestation has been recorded. For a real SAS "
                    "run this means there is no named account of who executed "
                    "the package, in which organisation, or on which SAS "
                    "version. It does not block a decision; it is for the "
                    "reviewer to weigh."
                )
            ),
            # Present whether or not anyone attested, because its absence is
            # what a reader would otherwise take for verification.
            "attestation_limitation": ATTESTATION_LIMITATION,
        },
        integrity={
            "package_archive": integrity.get("package_integrity"),
            "dataset_provenance": integrity.get("dataset_provenance"),
            "validation_case_provenance": integrity.get("validation_case_stamp"),
            "program_execution": integrity.get("program_execution_integrity"),
            "program_execution_qualification": integrity.get("qualification"),
        },
        statistics={
            "estimate_percent": run.get("estimate_ratio"),
            "estimate_log": run.get("estimate_log"),
            "standard_error": run.get("standard_error"),
            "denominator_df": run.get("denominator_df"),
            "ci_lower_percent": run.get("ci_lower_ratio"),
            "ci_upper_percent": run.get("ci_upper_ratio"),
            "covariance_parameters": run.get("covariance_parameters"),
            "convergence_status": run.get("convergence_status"),
            "log_signals": run.get("warnings") or [],
            # Said plainly. Every number above is what SAS reported, which is a
            # different claim from what is true.
            "source": "as reported by SAS in the uploaded structured result",
        },
        # Passed through from the comparison, which already carries an
        # evidence_status on every entry. Not re-labelled here: one place
        # decides what a number's provenance is.
        reference_context=list(comparison.get("reference_context", [])),
        ai_analysis=ai_review,
        human_reviews=list(human_reviews or []),
    )


__all__ = [
    "DECISION_SEMANTICS",
    "DRY_RUN_BANNER",
    "EvidenceReport",
    "build_evidence_report",
]
