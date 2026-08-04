"""evidence_reviewer.

Checks the drafted report before it is finalised. Deliberately a hybrid: the
checks that can be made deterministically are, and only the judgement calls go
to a model.

Deterministic (code):
  - citation markers that do not resolve to a retrieved record
  - quantitative claims with no citation
  - certainty language
  - abstract-only sources described as full text
  - duplicate identifiers across evidence records

Model:
  - contradictions between sections
  - claims that are unsupported in substance rather than merely uncited

Putting citation resolution in code rather than in the prompt is the whole
point: asking a model to check its own citations means trusting the component
that made the error to find it.
"""

from __future__ import annotations

import logging
from collections import Counter

from app.graph.context import RunContext
from app.graph.state import ResearchState, evidence_markers
from app.llm.citations import (
    extract_markers,
    find_overconfident_language,
    find_uncited_numeric_claims,
)
from app.llm.prompts import build_instructions
from app.llm.provider import LLMError, ModelRole
from app.models.agents import VerificationIssue, VerificationReport

logger = logging.getLogger(__name__)

NODE = "evidence_reviewer"

#: One revision only. A model that cannot satisfy the reviewer twice will not
#: satisfy it on the third attempt, and each pass costs real money.
MAX_REVISIONS = 1

INSTRUCTIONS = """\
You are the Evidence and Citation Reviewer. Deterministic checks for citation
resolution, uncited numbers and overconfident language have already run and
their findings are supplied to you. Do not repeat them.

Your job is the judgement that code cannot make:

- Contradictions BETWEEN sections. Does the report say something in one place
  that it contradicts elsewhere?
- Claims that are unsupported in substance. A statement may carry a citation
  that does not actually support it, or may generalise far beyond what a single
  cited study can carry.
- Access-level misuse. Does the text describe methods or detailed results for a
  source that was retrieved at abstract level only?
- Scope overreach. Does the report claim regulatory acceptance, safety,
  efficacy, patent clearance or freedom to operate?

Set `requires_revision` true only when at least one issue is high severity:
something that would mislead a reader making a decision. Do not request
revision for stylistic matters.

For each section, assign confidence and state the reasoning. Base it on how
well the section's claims are actually evidenced, not on how well written it is.
"""


async def evidence_reviewer(state: ResearchState, context: RunContext) -> dict:
    run_id = state["run_id"]
    draft = state.get("report")
    evidence = state.get("evidence_records", [])
    known = evidence_markers(state)

    await context.emit(
        run_id, "node_started", "Verifying citations and evidence", node=NODE,
        agent_id="evidence_reviewer",
    )

    if draft is None:
        return {
            "verification": VerificationReport(
                issues=[],
                section_confidence=[],
                contradictions=[],
                requires_revision=False,
                overall_note="No report was available to verify.",
            )
        }

    deterministic = _deterministic_checks(draft, evidence, known)

    await context.emit(
        run_id,
        "status",
        f"Automated checks found {len(deterministic)} issue(s)",
        node=NODE,
        data={"issue_count": len(deterministic)},
    )

    findings_block = (
        "\n".join(
            f"- [{i.severity}] {i.section_key} / {i.issue_type}: {i.detail}"
            for i in deterministic
        )
        or "No issues found by automated checks."
    )

    report_text = "\n\n".join(
        f"## {s.title} (section_key: {s.section_key})\n\n{s.body_markdown}"
        for s in draft.sections
    )

    try:
        result = await context.models.complete_structured(
            role=ModelRole.VERIFICATION,
            schema=VerificationReport,
            instructions=build_instructions(INSTRUCTIONS, includes_untrusted=False),
            user_input=(
                f"Research question:\n{state['original_question']}\n\n"
                f"Automated check findings:\n{findings_block}\n\n"
                f"Number of evidence records available: {len(evidence)}\n\n"
                f"Report under review:\n{report_text}"
            ),
            node=NODE,
            purpose="evidence verification",
        )
        verification = result.output
        # The model's issues supplement the deterministic ones; they never
        # replace them, because deterministic findings are facts.
        verification.issues = deterministic + verification.issues
    except LLMError as exc:
        logger.warning("Model verification failed: %s", exc)
        # Fall back to deterministic findings alone rather than skipping
        # verification entirely.
        verification = VerificationReport(
            issues=deterministic,
            section_confidence=[],
            contradictions=state.get("contradictions", []),
            requires_revision=any(i.severity == "high" for i in deterministic),
            overall_note=(
                "Model-assisted verification was unavailable; automated citation "
                "and language checks were still applied."
            ),
        )

    high = [i for i in verification.issues if i.severity == "high"]
    revision_count = state.get("revision_count", 0)
    needs_revision = bool(high) and revision_count < MAX_REVISIONS
    verification.requires_revision = needs_revision

    await context.emit(
        run_id,
        "node_completed",
        (
            f"Verification complete: {len(verification.issues)} issue(s), "
            f"{len(high)} high severity"
            + (". Requesting revision." if needs_revision else ".")
        ),
        node=NODE,
        agent_id="evidence_reviewer",
        data={"issues": len(verification.issues), "high_severity": len(high)},
    )

    warnings = []
    if high and not needs_revision:
        warnings.append(
            f"{len(high)} high-severity verification issue(s) remain after the "
            "revision limit was reached; they are listed in the report."
        )

    return {
        "verification": verification,
        "contradictions": verification.contradictions,
        "warnings": warnings,
        "revision_count": revision_count + (1 if needs_revision else 0),
    }


def _deterministic_checks(draft, evidence, known: set[str]) -> list[VerificationIssue]:
    """Checks that do not require judgement, and so must not require a model."""
    issues: list[VerificationIssue] = []

    abstract_only = {
        e["marker"] for e in evidence if e.get("access_level") == "abstract_only"
    }

    for section in draft.sections:
        body = section.body_markdown

        for marker in extract_markers(body):
            if marker not in known:
                issues.append(
                    VerificationIssue(
                        section_key=section.section_key,
                        issue_type="unresolvable_citation",
                        detail=(
                            f"Citation {marker} does not correspond to any retrieved "
                            f"record and will be removed."
                        ),
                        quoted_text=marker,
                        suggested_correction="Remove the claim or cite a retrieved source.",
                        severity="high",
                    )
                )

        for sentence in find_uncited_numeric_claims(body)[:5]:
            issues.append(
                VerificationIssue(
                    section_key=section.section_key,
                    issue_type="unsupported_number",
                    detail="A quantitative claim is not tied to a cited source.",
                    quoted_text=sentence[:300],
                    suggested_correction="Cite the source, or state the value as to be set.",
                    severity="high",
                )
            )

        for phrase in find_overconfident_language(body)[:5]:
            issues.append(
                VerificationIssue(
                    section_key=section.section_key,
                    issue_type="overconfident_language",
                    detail=f"'{phrase}' asserts more certainty than research evidence supports.",
                    quoted_text=phrase,
                    suggested_correction="Use language proportionate to the evidence.",
                    severity="medium",
                )
            )

        # Detailed methods described for a source we only read the abstract of.
        cited_abstract_only = [m for m in extract_markers(body) if m in abstract_only]
        if cited_abstract_only and _describes_full_text(body):
            issues.append(
                VerificationIssue(
                    section_key=section.section_key,
                    issue_type="mislabelled_access_level",
                    detail=(
                        "The text describes full-text detail while citing sources "
                        f"retrieved at abstract level only ({', '.join(cited_abstract_only[:5])})."
                    ),
                    suggested_correction="Say these sources were read at abstract level.",
                    severity="medium",
                )
            )

    issues.extend(_duplicate_source_issues(evidence))
    return issues


def _duplicate_source_issues(evidence) -> list[VerificationIssue]:
    """Two evidence records pointing at the same document inflate source counts,
    which inflates computed confidence."""
    identifiers = Counter(
        e["identifier"] for e in evidence if e.get("identifier")
    )
    return [
        VerificationIssue(
            section_key="references",
            issue_type="duplicate_source",
            detail=f"Identifier {identifier} appears in {count} evidence records.",
            quoted_text=identifier,
            suggested_correction="Deduplicate before counting sources.",
            severity="medium",
        )
        for identifier, count in identifiers.items()
        if count > 1
    ]


_FULL_TEXT_PHRASES = (
    "the authors report in the methods",
    "full text",
    "as described in section",
    "supplementary",
    "figure 1",
    "figure 2",
    "table 1",
    "table 2",
)


def _describes_full_text(body: str) -> bool:
    lowered = body.lower()
    return any(phrase in lowered for phrase in _FULL_TEXT_PHRASES)
