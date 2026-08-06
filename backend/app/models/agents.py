"""Typed agent inputs and outputs.

Every node returns one of these schemas rather than prose. Three things follow
from that, all of them load-bearing:

* A successful prompt injection still cannot produce arbitrary output; it can
  only fill fields that are then validated.
* Citations are lists of markers that get checked against the evidence table,
  not sentences that merely look cited.
* Uncertainty has somewhere to live. Every claim carries a support level, so
  "we do not know" is representable rather than something the model has to
  phrase its way around.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    """Reject unknown fields so schema drift surfaces immediately."""

    model_config = ConfigDict(extra="forbid")


class SupportLevel(StrEnum):
    """How well the retrieved evidence backs a statement."""

    DIRECT = "direct"          # a cited source states this
    INFERRED = "inferred"      # reasoned from cited sources
    ASSUMPTION = "assumption"  # not evidenced; stated as an assumption
    UNSUPPORTED = "unsupported"


class Confidence(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Claim(Strict):
    """A single statement with its evidential basis.

    `citations` holds evidence markers only (E1, E12). The reviewer rejects any
    marker that does not resolve to a stored record, so this field cannot smuggle
    in a fabricated source.
    """

    statement: str = Field(min_length=1)
    support: SupportLevel
    citations: list[str] = Field(
        default_factory=list,
        description="Evidence markers such as E1, E7. Only markers from the supplied allowlist.",
    )
    caveat: str | None = Field(
        default=None,
        description="Limitation on this claim: in vitro only, animal only, single study, preprint.",
    )


# --------------------------------------------------------------------------- #
# Intake and planning
# --------------------------------------------------------------------------- #


class StructuredObjective(Strict):
    """The supervisor's reading of what the user actually asked for."""

    restated_objective: str
    research_questions: list[str] = Field(min_length=1, max_length=12)
    molecule_or_modality: str | None = None
    indication: str | None = None
    delivery_technology: str | None = None
    route_of_administration: str | None = None
    dosage_form: str | None = None
    development_stage: str | None = None
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(
        default_factory=list,
        description="Explicitly excluded so the report does not overreach.",
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description="Genuinely unclear aspects of the request, rather than assumed answers.",
    )


class PlannedSearch(Strict):
    provider: str = Field(description="pubmed, europepmc, or epo_ops")
    query: str
    rationale: str


class ResearchPlan(Strict):
    approach: str
    literature_searches: list[PlannedSearch] = Field(default_factory=list, max_length=10)
    patent_searches: list[PlannedSearch] = Field(default_factory=list, max_length=10)
    required_agents: list[str] = Field(
        default_factory=list,
        description="Node names the supervisor considers necessary for this question.",
    )
    known_risks: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Specialist agents
# --------------------------------------------------------------------------- #


class BackgroundSummary(Strict):
    """General Research Agent output."""

    scientific_background: list[Claim]
    target_product_profile: list[Claim] = Field(default_factory=list)
    competing_technologies: list[Claim] = Field(default_factory=list)
    relevant_precedents: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StudyExtraction(Strict):
    """What the literature agent extracted from one retrieved paper."""

    marker: str = Field(description="Evidence marker of the paper being described.")
    evidence_category: str = Field(
        description=(
            "review, in_vitro, in_vivo, clinical, formulation, toxicology, "
            "manufacturing, analytical, or other"
        )
    )
    study_objective: str | None = None
    methods: str | None = None
    materials: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    relevance_note: str | None = None
    relevance_score: float = Field(ge=0.0, le=1.0)


class LiteratureFindings(Strict):
    """Literature Review Agent output."""

    summary: str
    extractions: list[StudyExtraction] = Field(default_factory=list)
    synthesis: list[Claim] = Field(default_factory=list)
    contradictions: list[str] = Field(
        default_factory=list,
        description="Places where retrieved sources disagree. Reported, not resolved away.",
    )
    evidence_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PatentAnalysis(Strict):
    """What the patent agent concluded about one patent family."""

    marker: str
    technical_summary: str
    formulation: str | None = None
    material: str | None = None
    delivery_route: str | None = None
    release_mechanism: str | None = None
    claimed_application: str | None = None
    relevance_score: float = Field(ge=0.0, le=1.0)


class PatentFindings(Strict):
    """Patent Research Agent output.

    Deliberately has no freedom-to-operate, validity or infringement field.
    There is nowhere for such a conclusion to be recorded, because the product
    must never present one.
    """

    summary: str
    analyses: list[PatentAnalysis] = Field(default_factory=list)
    overlapping_concepts: list[Claim] = Field(
        default_factory=list,
        description="Technical overlap with the proposed concept. Not a legal assessment.",
    )
    technology_comparison: list[Claim] = Field(default_factory=list)
    white_space_observations: list[Claim] = Field(
        default_factory=list,
        description=(
            "Areas where retrieved results were sparse. Describes the absence of "
            "results in this search only, never an absence of patents."
        ),
    )
    warnings: list[str] = Field(default_factory=list)


class RiskItem(Strict):
    category: str
    risk: str
    likelihood: str = Field(description="high, medium, or low")
    impact: str = Field(description="high, medium, or low")
    mitigation: str
    citations: list[str] = Field(default_factory=list)


class QualityAttribute(Strict):
    attribute: str
    target_or_range: str | None = None
    criticality: str = Field(description="critical, key, or non_critical")
    rationale: str
    citations: list[str] = Field(default_factory=list)


class ExperimentProposal(Strict):
    objective: str
    approach: str
    addresses_gap: str
    priority: str = Field(description="high, medium, or low")


class StageGate(Strict):
    stage: str
    objectives: list[str]
    key_activities: list[str]
    gate_criteria: list[str]


class DevelopmentStrategy(Strict):
    """Development Strategy Agent output.

    Section coverage is intentionally broad, but every list may be empty. An
    empty section means the retrieved evidence did not support saying anything,
    which is a legitimate and useful answer.
    """

    product_concept: list[Claim] = Field(default_factory=list)
    target_product_profile: list[Claim] = Field(default_factory=list)
    delivery_rationale: list[Claim] = Field(default_factory=list)
    release_mechanism: list[Claim] = Field(default_factory=list)

    formulation_pathway: list[Claim] = Field(default_factory=list)
    material_selection: list[Claim] = Field(default_factory=list)
    stability_risks: list[Claim] = Field(default_factory=list)
    sterility_strategy: list[Claim] = Field(default_factory=list)
    container_closure: list[Claim] = Field(default_factory=list)

    manufacturing_concept: list[Claim] = Field(default_factory=list)
    scale_up_risks: list[Claim] = Field(default_factory=list)

    analytical_requirements: list[Claim] = Field(default_factory=list)
    release_testing_strategy: list[Claim] = Field(default_factory=list)
    characterisation_requirements: list[Claim] = Field(default_factory=list)

    biocompatibility: list[Claim] = Field(default_factory=list)
    immunogenicity: list[Claim] = Field(default_factory=list)
    biodistribution: list[Claim] = Field(default_factory=list)
    toxicology_questions: list[Claim] = Field(default_factory=list)
    nonclinical_needs: list[Claim] = Field(default_factory=list)
    clinical_considerations: list[Claim] = Field(default_factory=list)
    regulatory_questions: list[Claim] = Field(default_factory=list)

    critical_quality_attributes: list[QualityAttribute] = Field(default_factory=list)
    critical_material_attributes: list[QualityAttribute] = Field(default_factory=list)
    critical_process_parameters: list[QualityAttribute] = Field(default_factory=list)

    risks: list[RiskItem] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommended_experiments: list[ExperimentProposal] = Field(default_factory=list)
    stage_gate_plan: list[StageGate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


class VerificationIssue(Strict):
    section_key: str
    issue_type: str = Field(
        description=(
            "unsupported_claim, unresolvable_citation, overconfident_language, "
            "unsupported_number, contradiction, mislabelled_access_level, "
            "duplicate_source, or prompt_injection_attempt"
        )
    )
    detail: str
    quoted_text: str | None = None
    suggested_correction: str | None = None
    severity: str = Field(description="high, medium, or low")


class SectionConfidence(Strict):
    section_key: str
    confidence: Confidence
    rationale: str
    supporting_source_count: int = Field(ge=0)


class VerificationReport(Strict):
    """Evidence and Citation Reviewer output."""

    issues: list[VerificationIssue] = Field(default_factory=list)
    section_confidence: list[SectionConfidence] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    requires_revision: bool = Field(
        description="True when at least one high-severity issue must be corrected."
    )
    overall_note: str


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


class ReportSectionDraft(Strict):
    section_key: str
    title: str
    body_markdown: str


class ReportDraft(Strict):
    """Supervisor synthesis output."""

    executive_summary: str
    sections: list[ReportSectionDraft]
    key_uncertainties: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


#: The report's fixed structure. Order is the order sections appear.
REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("executive_summary", "Executive summary"),
    ("objective_and_scope", "Research objective and scope"),
    ("target_product_concept", "Target product concept"),
    ("scientific_background", "Scientific and technical background"),
    ("literature_review", "Literature review"),
    ("patent_landscape", "Patent landscape"),
    ("technology_comparison", "Technology comparison"),
    ("critical_quality_attributes", "Critical quality attributes"),
    ("critical_material_attributes", "Critical material attributes"),
    ("critical_process_parameters", "Critical process parameters"),
    ("formulation_strategy", "Formulation development strategy"),
    ("analytical_strategy", "Analytical development strategy"),
    ("manufacturing_strategy", "Manufacturing and scale-up strategy"),
    ("nonclinical", "Nonclinical considerations"),
    ("regulatory", "Regulatory considerations"),
    ("key_risks", "Key risks"),
    ("evidence_gaps", "Evidence gaps"),
    ("recommended_experiments", "Recommended experiments"),
    ("stage_gate_plan", "Stage-gate development plan"),
    ("conclusions", "Conclusions"),
    ("limitations", "Limitations and disclaimers"),
    ("references", "References"),
)

SECTION_TITLES: dict[str, str] = dict(REPORT_SECTIONS)
