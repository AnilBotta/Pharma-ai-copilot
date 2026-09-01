"""An assistant that reads the evidence and recommends. It cannot approve.

    AI MAY RECOMMEND. AI MUST NOT BE THE FINAL APPROVER.

That rule is enforced by vocabulary, not by discipline. `AIRecommendation` and
`OracleClosureDecision` are disjoint enums with no overlapping member, so there
is no value this module can produce that means "accepted". The model is not
trusted to stay on the right side of a line; it is given a language in which
the wrong side cannot be said.

FACTS AND INTERPRETATION ARE SEPARATED IN THE PROMPT

The evidence sent to the model is split into two clearly labelled parts:

    FACTS           determined by deterministic code - integrity states, the
                    parsed numbers, convergence, log signals, published
                    reference values. The model is told these are settled and
                    that it must not restate or revise them.

    INTERPRETATION  what the model is actually for - whether discrepancies
                    matter, what a reviewer should weigh, what is missing.

The split matters because the failure mode of a language model here is not
refusing to answer; it is confidently rewriting a fact. A model that reported
`program_execution_integrity` as verified, or called 19.8906 "the regulator
value", would be corrupting the record it was summarising.

THE ASSISTANT IS OPTIONAL

If the provider is unavailable, slow, or returns something unparseable, the
result is `AI_REVIEW_UNAVAILABLE` and the human review proceeds on the
deterministic evidence alone. A regulatory review that could be blocked by an
LLM outage would be a worse system than one with no assistant at all.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Bumped whenever the prompt changes. Stored with every review, because an
#: analysis is only interpretable against the instructions that produced it.
PROMPT_VERSION = "sas-oracle-review/1"


class AIRecommendation(StrEnum):
    """What the assistant may say.

    DISJOINT FROM `OracleClosureDecision` BY CONSTRUCTION. The nearest thing to
    approval available here is "acceptable for human review", which asserts
    only that a person's time would not be wasted - not that anything is
    accepted. A test asserts the two enums share no member.
    """

    ACCEPTABLE_FOR_HUMAN_REVIEW = "acceptable_for_human_review"
    REJECT_RECOMMENDED = "reject_recommended"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ESCALATE_TO_STATISTICIAN = "escalate_to_statistician"


class AIConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AIReviewResponse(BaseModel):
    """The structured shape the model must return.

    Free prose would be easier to generate and impossible to govern: a summary
    that buried a recommendation in a paragraph could not be tested, stored as
    an enum, or checked for the words it must not contain.
    """

    summary: str = Field(
        description=(
            "Two to four sentences for a statistician who has not seen this "
            "run. Describe what the evidence shows; do not decide anything."
        )
    )
    evidence_strengths: list[str] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)
    detected_discrepancies: list[str] = Field(default_factory=list)
    regulatory_concerns: list[str] = Field(default_factory=list)
    statistical_concerns: list[str] = Field(default_factory=list)
    recommendation: AIRecommendation
    recommendation_reason: str
    confidence: AIConfidence

    #: Always true, and present so the field appears in the stored artefact and
    #: on screen. There is no code path that sets it false.
    requires_human_review: bool = True


@dataclass(frozen=True, slots=True)
class AIReviewOutcome:
    """What came back, including the case where nothing did."""

    succeeded: bool
    response: AIReviewResponse | None
    evidence_snapshot: dict[str, Any]
    evidence_snapshot_hash: str
    prompt_version: str
    model_provider: str | None = None
    model_name: str | None = None
    failure_reason: str | None = None
    generated_at: str = ""

    @property
    def recommendation(self) -> AIRecommendation | None:
        return self.response.recommendation if self.response else None

    def response_hash(self) -> str | None:
        if self.response is None:
            return None
        return hashlib.sha256(
            self.response.model_dump_json().encode("utf-8")
        ).hexdigest()


#: The assistant could not be reached, or could not answer. A state, not an
#: error: the deterministic evidence is unaffected and review proceeds.
AI_REVIEW_UNAVAILABLE = "AI_REVIEW_UNAVAILABLE"

#: The assistant was configured WRONGLY - a provider that does not implement
#: `ReviewProvider`. Distinguished from unavailability because an outage clears
#: itself and a wiring bug does not, and reporting the second as the first
#: means nobody ever investigates.
AI_REVIEW_MISCONFIGURED = "AI_REVIEW_MISCONFIGURED"

#: Shown wherever the analysis is displayed. Not a footnote: a reader skimming
#: a confident paragraph needs to know what produced it.
ADVISORY_LABEL = "AI-generated advisory analysis — not an approval."

SYSTEM_PROMPT = """\
You are assisting a statistician who is deciding whether an uploaded SAS result
should be accepted as ORACLE EVIDENCE for a bioequivalence validation question.

YOUR ROLE IS ADVISORY. You do not approve anything. A qualified human reviewer
makes the decision, and your analysis is one input to it.

THE FACTS BELOW ARE SETTLED. They were determined by deterministic code, not by
you. Do not restate them as uncertain, do not revise them, and do not describe
any of them as something other than what they say. In particular:

  - if program execution integrity is UNVERIFIED_MANUAL_EXECUTION, that is a
    permanent property of customer-run SAS and NOT a defect in this upload
  - a value labelled INDEPENDENT CANDIDATE or EXTERNAL IMPLEMENTATION is NOT
    regulator-confirmed. Never refer to such a value as "the regulator value",
    "the correct value", or "the expected value"
  - only values labelled REGULATOR PUBLISHED were published by a regulator

YOUR JOB IS INTERPRETATION: whether the discrepancies matter, what a reviewer
should weigh, what is missing, and how confident you are. Be concise and be
willing to say the evidence is insufficient.
"""


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """What a provider hands back: the validated response and the model used."""

    value: AIReviewResponse
    model: str | None


class ReviewProvider(Protocol):
    """The ONLY thing this module asks of a model provider.

    Stated as a Protocol rather than left implicit, because the failure it
    prevents is the quiet one. `review()` below turns every provider exception
    into `AI_REVIEW_UNAVAILABLE` - which is right for an outage, but would also
    swallow a `TypeError` from calling a provider whose signature never matched.
    The assistant would then be permanently "unavailable" in production and
    nothing would say why.

    `app/llm/provider.py::ModelProvider` does NOT satisfy this: it takes
    `role`, `instructions` and `user_input` and returns a `StructuredResult`
    with `.output`. `ModelProviderReviewAdapter` below does the translation in
    one visible place.
    """

    provider_name: str

    async def complete_structured(
        self, *, schema: type[AIReviewResponse], system: str, prompt: str
    ) -> ProviderResult: ...


class ModelProviderReviewAdapter:
    """Binds the application's `ModelProvider` to `ReviewProvider`.

    VERIFICATION is the role deliberately chosen. This call checks work that
    already exists rather than generating new analysis, and it is the role the
    reviewer node in `app/graph/nodes/reviewer.py` uses for the same reason.
    """

    provider_name = "app.llm.ModelProvider"

    def __init__(self, models: Any, *, role: Any = None) -> None:
        from app.llm.provider import ModelRole

        self._models = models
        self._role = role or ModelRole.VERIFICATION

    async def complete_structured(
        self, *, schema: type[AIReviewResponse], system: str, prompt: str
    ) -> ProviderResult:
        result = await self._models.complete_structured(
            role=self._role,
            schema=schema,
            instructions=system,
            user_input=prompt,
            node="sas_validation_ai_review",
            purpose="advisory statistical review of a manual SAS validation run",
        )
        return ProviderResult(
            value=result.output, model=getattr(result.usage, "model", None)
        )


class SASValidationAIReviewer:
    """Wraps whatever model provider the deployment has configured.

    Takes the provider as a collaborator rather than constructing one, so no
    vendor is bound here and a deployment without a model simply passes None.
    Credentials stay wherever the provider keeps them - server-side, and never
    in anything this module returns.
    """

    def __init__(self, provider: ReviewProvider | None) -> None:
        self._provider = provider

    async def review(self, evidence: dict[str, Any]) -> AIReviewOutcome:
        """Analyse the evidence. Never raises; failure is a recorded state.

        A regulatory review must not be blocked by an LLM outage, so every
        failure path returns an outcome with `succeeded = False` and a reason a
        reviewer can read.
        """
        snapshot = _canonical(evidence)
        snapshot_hash = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        stamp = datetime.now(UTC).replace(microsecond=0).isoformat()

        if self._provider is None:
            return AIReviewOutcome(
                succeeded=False,
                response=None,
                evidence_snapshot=evidence,
                evidence_snapshot_hash=snapshot_hash,
                prompt_version=PROMPT_VERSION,
                failure_reason=(
                    f"{AI_REVIEW_UNAVAILABLE}: no model provider is configured "
                    "for this deployment. The deterministic evidence is "
                    "unaffected and human review may proceed."
                ),
                generated_at=stamp,
            )

        try:
            result = await self._provider.complete_structured(
                schema=AIReviewResponse,
                system=SYSTEM_PROMPT,
                prompt=build_prompt(evidence),
            )
            response = getattr(result, "value", result)
        except TypeError as error:
            # A signature mismatch, not an outage. Reported separately and at
            # exception level, because the catch-all below would otherwise
            # render a permanent wiring bug as a transient model problem and
            # the assistant would be silently absent forever. See
            # `ReviewProvider`.
            logger.exception("SAS AI review provider does not match ReviewProvider")
            return AIReviewOutcome(
                succeeded=False,
                response=None,
                evidence_snapshot=evidence,
                evidence_snapshot_hash=snapshot_hash,
                prompt_version=PROMPT_VERSION,
                failure_reason=(
                    f"{AI_REVIEW_MISCONFIGURED}: the configured provider does "
                    f"not implement ReviewProvider ({error})"
                ),
                generated_at=stamp,
            )
        except Exception as error:
            logger.warning("SAS AI review failed: %s", error)
            return AIReviewOutcome(
                succeeded=False,
                response=None,
                evidence_snapshot=evidence,
                evidence_snapshot_hash=snapshot_hash,
                prompt_version=PROMPT_VERSION,
                failure_reason=f"{AI_REVIEW_UNAVAILABLE}: {error}",
                generated_at=stamp,
            )

        return AIReviewOutcome(
            succeeded=True,
            response=response,
            evidence_snapshot=evidence,
            evidence_snapshot_hash=snapshot_hash,
            prompt_version=PROMPT_VERSION,
            model_provider=getattr(self._provider, "provider_name", None),
            model_name=getattr(result, "model", None),
            generated_at=stamp,
        )


def _canonical(evidence: dict[str, Any]) -> str:
    """Stable serialisation, so the same evidence always hashes the same."""
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)


def build_prompt(evidence: dict[str, Any]) -> str:
    """FACTS first, under a heading that says they are not up for revision.

    The reference values carry their evidence status inline rather than in a
    legend, because a model - like a reader - attaches whatever label is
    nearest the number.
    """
    facts = _canonical_block(evidence)
    return f"""\
=== FACTS (determined by deterministic code - do not revise) ===

{facts}

=== INTERPRETATION REQUESTED ===

Considering only the facts above:

1. Summarise what this evidence shows.
2. List its strengths and its limitations.
3. List any discrepancies you detect, and say whether each is material.
4. Raise any regulatory or statistical concerns.
5. Recommend one of: acceptable_for_human_review, reject_recommended,
   insufficient_evidence, escalate_to_statistician - and say why.
6. State your confidence.

You are not deciding whether this evidence is accepted. A human reviewer does
that, and may disagree with you.
"""


def _canonical_block(evidence: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in sorted(evidence.items()):
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for inner_key, inner_value in sorted(value.items()):
                lines.append(f"  {inner_key}: {inner_value}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


__all__ = [
    "ADVISORY_LABEL",
    "AI_REVIEW_MISCONFIGURED",
    "AI_REVIEW_UNAVAILABLE",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "AIConfidence",
    "AIRecommendation",
    "AIReviewOutcome",
    "AIReviewResponse",
    "ModelProviderReviewAdapter",
    "ProviderResult",
    "ReviewProvider",
    "SASValidationAIReviewer",
    "build_prompt",
]
