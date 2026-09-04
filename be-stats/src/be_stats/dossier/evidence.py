"""The validation evidence manifest: what has actually been checked, and how.

WHAT A RECORD HAS TO SAY

A claim like "EMA ABEL is validated" is unauditable. The reviewer's questions
are always the same six, and a record that cannot answer all six is not
evidence:

    against WHAT       the source, and whose authority stands behind it
    on WHICH DATA      the dataset, identified well enough to fetch again
    expecting WHAT     the published numbers, transcribed
    within WHAT        the tolerance, and why that tolerance
    producing WHAT     what this package actually computed
    established WHERE  the test that re-runs it, every time

The sixth is the one that keeps the other five honest. A manifest of frozen
numbers is a snapshot of a past run; a manifest that names the test which
re-derives them is a claim about the present. Every record here carries
`established_by`, and `test_every_evidence_record_names_a_real_test` fails if
it points at a test that does not exist.

TIER IS ABOUT AUTHORITY, NOT EFFORT

Forty-two synthetic Appendix C cases are tier 4. One EMA table is tier 1B. The
second is the evidence a VALIDATED promotion requires, and the first is what
stops a refactor breaking something. Both are worth having and they are not
interchangeable, so `EvidenceTier` is a required field and the release gate
reads it.

Required is not sufficient. Neither tier alone establishes VALIDATED status or
submission suitability; the gate reads this field alongside a pinned regulatory
source, the open findings and blockers, and an explicitly reviewed transition.

A MISSING ENVIRONMENT IS NEVER A PASS

Tier-3 records depend on R, Julia and a pinned container that a developer
machine does not have. The status vocabulary has a member for exactly that -
`SKIPPED_ENVIRONMENT_UNAVAILABLE` - and the release gate treats it as
disqualifying rather than neutral. A validation that quietly did not run is
worse than one that failed, because it reports green.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.dossier.statuses import EvidenceTier


class EvidenceStatus(StrEnum):
    """What the last authoritative run of this comparison established."""

    #: Agreement inside the declared tolerance, with nothing qualifying it.
    PASSED = "passed"
    #: Agreement inside the tolerance, with an open or accepted finding that
    #: a reader must see alongside the tick. Never displayed as PASSED.
    PASSED_WITH_FINDING = "passed_with_finding"
    #: The comparison exists and has not been run against real evidence yet.
    #: The state the partial-replicate SAS oracle is in.
    PENDING = "pending"
    #: The comparison could not run because its environment was unavailable.
    #: DISQUALIFYING for certification, neutral for ordinary CI, and never
    #: reportable as PASSED.
    SKIPPED_ENVIRONMENT_UNAVAILABLE = "skipped_environment_unavailable"
    #: No evidence of this kind exists and none is expected to. Recorded so
    #: the absence is visible rather than inferred from an empty row.
    NOT_AVAILABLE = "not_available"


class SourceType(StrEnum):
    """What kind of thing the expected values came from."""

    #: A rule or algorithm stated in prose by the regulator, conformed to.
    REGULATORY_ALGORITHM = "regulatory_algorithm"
    #: Numbers the regulator itself published.
    REGULATOR_PUBLISHED_NUMBERS = "regulator_published_numbers"
    #: A textbook or peer-reviewed reference dataset.
    PUBLISHED_REFERENCE = "published_reference"
    #: Another implementation of the same method.
    INDEPENDENT_IMPLEMENTATION = "independent_implementation"
    #: This package checking itself - simulation, or an algebraic identity
    #: derived independently of the implementation under test.
    INTERNAL_STRUCTURAL = "internal_structural"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One comparison, complete enough to be audited without asking anybody."""

    evidence_id: str
    #: Capability ids from `dossier.capabilities`.
    capabilities: tuple[str, ...]
    tier: EvidenceTier
    source_type: SourceType
    #: Who stands behind the expected values. "FDA", "EMA", "PowerTOST",
    #: "be-stats". Named separately from the source type because tier 3 and
    #: tier 1B can both be "published" and only one of them is a regulator.
    source_authority: str
    #: The scenario, in one line.
    scenario: str
    #: The data, identified well enough to fetch again.
    dataset: str
    #: The software and environment the expected values came from, where they
    #: came from software at all.
    software_environment: str
    #: What the source says, transcribed. Free text because the shape differs
    #: per record - an interval, a table, a boolean rule.
    expected: str
    #: What this package produces. Where a number is quoted it is a SNAPSHOT,
    #: and `established_by` names the test that re-derives it on every run.
    observed: str
    #: The tolerance, and why it is that tolerance. A tolerance with no reason
    #: is a number somebody tuned until the test went green.
    tolerance: str
    status: EvidenceStatus
    #: The test that re-establishes this. Module path relative to be-stats.
    established_by: str
    #: A COMMITTED artefact, tracked in this repository.
    #:
    #: "Committed" is the load-bearing word and it was got wrong once. This
    #: field held `validation/external/report.json` - a file `.gitignore`
    #: excludes because the harness generates it. It existed on the machine
    #: where the manifest was written, so an `.exists()` check passed there
    #: and failed on a clean checkout. An artefact nobody else can fetch is
    #: not evidence, so the test now asks git rather than the filesystem.
    artifact: str = ""
    #: Where a RUN deposits its output. Generated, gitignored, and absent
    #: until somebody runs it.
    #:
    #: Separate from `artifact` on purpose. Both are useful to record and only
    #: one of them is a thing a reviewer can open from the repository; naming
    #: them with one field is what let a generated path be cited as evidence.
    run_output: str = ""
    #: Findings that qualify this record.
    findings: tuple[str, ...] = ()
    note: str = ""


#: The manifest. Ordered by tier, because that is the order a reviewer reads
#: it in: what does the regulator say, then what did the regulator publish,
#: then who else agrees, then what did we check ourselves.
EVIDENCE_MANIFEST: tuple[EvidenceRecord, ...] = (
    # ------------------------------------------------------------ tier 1A ---
    EvidenceRecord(
        evidence_id="FDA-HVD-SWITCH-001",
        capabilities=("FDA_HVD_METHOD_SELECTION", "FDA_HVD_RSABE"),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="FDA",
        scenario=(
            "Which analysis Appendix G selects across the sWR range, "
            "including the boundary case sWR = 0.294 exactly."
        ),
        dataset="Six enumerated sWR values spanning the threshold.",
        software_environment="None - the rule is asserted, not computed.",
        expected=(
            "sWR < 0.294 selects the two one-sided tests procedure; "
            "sWR >= 0.294 selects reference-scaled ABE. The boundary case "
            "goes to the scaled side, which III.C and Appendix G both state."
        ),
        observed="The same selection for all six values, including 0.294.",
        tolerance=(
            "Exact. A selection is a discrete choice and there is no "
            "tolerance to state; a near-miss here is a wrong analysis."
        ),
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_algorithm_conformance.py",
        artifact="validation/phase1/algorithm/FDA_HVD_SWITCH_001.json",
    ),
    EvidenceRecord(
        evidence_id="FDA-HVD-SWR-FORMULA-001",
        capabilities=("FDA_HVD_REFERENCE_VARIANCE",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="FDA",
        scenario="The sWR estimator Appendix G specifies.",
        dataset="Enumerated structural cases.",
        software_environment="None.",
        expected="The estimator and its degrees of freedom as Appendix G states them.",
        observed="Conforms.",
        tolerance="Exact on structure; 1e-12 on the arithmetic identities.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_algorithm_conformance.py",
        artifact="validation/phase1/algorithm/FDA_HVD_SWR_FORMULA_001.json",
    ),
    EvidenceRecord(
        evidence_id="FDA-HVD-RSABE-CRITERION-001",
        capabilities=("FDA_HVD_RSABE",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="FDA",
        scenario=(
            "The scaled criterion AND the point-estimate constraint, both "
            "required by Appendix G step 3."
        ),
        dataset="Enumerated criterion combinations.",
        software_environment="None.",
        expected=(
            "Upper 95% bound on (muT-muR)^2 - theta.sWR^2 must be <= 0, AND "
            "the point estimate must fall within 0.8000-1.2500."
        ),
        observed="Both criteria enforced; neither alone decides.",
        tolerance="Exact on the conjunction.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_algorithm_conformance.py",
        artifact="validation/phase1/algorithm/FDA_HVD_RSABE_CRITERION_001.json",
    ),
    EvidenceRecord(
        evidence_id="FDA-NTI-CRITERIA-001",
        capabilities=(
            "FDA_NTI_RSABE",
            "FDA_NTI_REFERENCE_SCALED_CRITERION",
            "FDA_NTI_VARIABILITY_RATIO",
            "FDA_NTI_UNSCALED_ABE",
        ),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="FDA",
        scenario=(
            "All three Appendix F criteria and every combination of their "
            "outcomes, including the ones where a single criterion decides "
            "the study."
        ),
        dataset="Enumerated criterion combinations over the three criteria.",
        software_environment="None.",
        expected=(
            "The endpoint passes only when all three hold. Any criterion "
            "that is not estimable makes the endpoint NOT DECIDED rather "
            "than failed."
        ),
        observed="Conforms across the enumerated combinations.",
        tolerance="Exact on the conjunction and on the decided/not-decided split.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_nti_criterion_combinations.py",
        artifact="validation/nti/cases/criterion_combinations.json",
    ),
    EvidenceRecord(
        evidence_id="FDA-HVD-TREATMENT-CONTRAST",
        capabilities=("FDA_HVD_TREATMENT_CONTRAST",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="FDA",
        scenario=(
            "That mu_T - mu_R is the equally weighted mean of the SEQUENCE "
            "means of Iij, with the design's own degrees of freedom - and not "
            "the simple mean over subjects, which differs whenever the "
            "sequences are unbalanced."
        ),
        dataset="Constructed replicate datasets, balanced and unbalanced.",
        software_environment="be-stats only.",
        expected=(
            "The Appendix G contrast, which absorbs period within a subject "
            "and estimates no period effect."
        ),
        observed="Conforms, and excluded subjects are reported rather than silent.",
        tolerance="1e-12 on the arithmetic; exact on the subject accounting.",
        status=EvidenceStatus.PASSED,
        established_by="tests/unit/test_treatment_contrast.py",
        note=(
            "Tier 1A. No FDA-published dataset exercises this contrast, which "
            "is why the capability cannot rise above IMPLEMENTED_UNVALIDATED."
        ),
    ),
    EvidenceRecord(
        evidence_id="EMA-ABEL-PE-CONSTRAINT",
        capabilities=("EMA_ABEL_PE_CONSTRAINT",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="EMA",
        scenario=(
            "That the GMR constraint is required IN ADDITION to the widened "
            "interval, and that a study inside the widened limits with a GMR "
            "outside 80.00-125.00% fails."
        ),
        dataset="Constructed endpoint cases either side of both criteria.",
        software_environment="be-stats only.",
        expected=(
            "4.1.10: 'The geometric mean ratio (GMR) should lie within the "
            "conventional acceptance range 80.00-125.00%.'"
        ),
        observed="Both criteria are required; neither alone decides.",
        tolerance="Exact on the conjunction.",
        status=EvidenceStatus.PASSED,
        established_by="tests/unit/test_ema_abel.py",
        note=(
            "No EMA-published example exercises the constraint on its own, "
            "which is why it stays unvalidated while the limits either side "
            "of it are validated."
        ),
    ),
    EvidenceRecord(
        evidence_id="EMA-HVD-ENDPOINT-DECISION",
        capabilities=("EMA_HVD_ENDPOINT_DECISION",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="EMA",
        scenario=(
            "The whole endpoint decision: eligibility, widened limits, the "
            "Method A interval and the GMR constraint, combined into one "
            "verdict - including the paths that produce no verdict."
        ),
        dataset="Constructed endpoint cases across the eligibility boundary.",
        software_environment="be-stats only.",
        expected=(
            "A PASS only when both criteria hold; AUC never widened; CVwR at "
            "or below 30% analysed under the ordinary limits rather than "
            "failed."
        ),
        observed="Conforms.",
        tolerance="Exact on the decision; 1e-12 on the limits.",
        status=EvidenceStatus.PASSED,
        established_by="tests/integration/test_hvd_endpoint_decision.py",
        note=(
            "THE WIRING, and the reason this capability is deliberately NOT "
            "validated: every part below it has tier-1B evidence and no EMA "
            "publication carries one end-to-end example through to a stated "
            "verdict. Validated components assembled by unvalidated wiring is "
            "exactly what the ladder exists to make visible."
        ),
    ),
    EvidenceRecord(
        evidence_id="EMA-NTI-NARROWED-INTERVAL",
        capabilities=("EMA_NTI_NARROW_ABE",),
        tier=EvidenceTier.TIER_1A,
        source_type=SourceType.REGULATORY_ALGORITHM,
        source_authority="EMA",
        scenario=(
            "That an NTI drug under EMA routes to the NARROWED interval for "
            "AUC, that Cmax refuses pending product-specific guidance, and "
            "that a product override replaces the limits rather than widening "
            "them back."
        ),
        dataset="The routing cases, including a ciclosporin- and a colchicine-shaped override.",
        software_environment="None - the limits are stated in the guideline.",
        expected=(
            "90.00-111.11% for AUC. NOT 80.00-125.00%, and not FDA's "
            "additional-criteria construction, which is a different procedure."
        ),
        observed="The narrowed interval is selected, and Cmax raises.",
        tolerance="Exact on both limits; the guideline states them to two decimals.",
        status=EvidenceStatus.PASSED,
        established_by="tests/integration/test_spec_routing.py",
        note=(
            "Tier 1A and not 1B: EMA states the interval and publishes no "
            "worked example of a study decided under it."
        ),
    ),
    # ------------------------------------------------------------ tier 1B ---
    EvidenceRecord(
        evidence_id="EMA-PKWP-METHOD-A-DATASET-I",
        capabilities=("EMA_REPLICATE_METHOD_A",),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="EMA",
        scenario=(
            "Method A on EMA's Data set I - a four-period fully replicate "
            "design, UNBALANCED, with eight incomplete subjects that must be "
            "retained for the published result to come out."
        ),
        dataset=(
            "EMA/618604/2008 Rev. 13 annex, Data set I, transcribed to "
            "validation/ema/cases/ema_pkwp_qa_datasets.json."
        ),
        software_environment="EMA published the output from SAS 9.1.",
        expected="Point estimate 115.66%, 90% CI 107.11-124.89%.",
        observed=(
            "Reproduced to the two decimals EMA printed, on the unbalanced "
            "set with all 77 subjects retained."
        ),
        tolerance=(
            "abs 0.005 on each figure - a ROUNDING bound derived from EMA "
            "printing two decimals, not a fitted one."
        ),
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_ema_tier1b.py",
        artifact="validation/ema/cases/ema_pkwp_qa_datasets.json",
    ),
    EvidenceRecord(
        evidence_id="EMA-PKWP-METHOD-A-DATASET-II",
        capabilities=("EMA_REPLICATE_METHOD_A",),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="EMA",
        scenario="Method A on EMA's Data set II.",
        dataset="EMA/618604/2008 Rev. 13 annex, Data set II.",
        software_environment="EMA published the output from SAS 9.1.",
        expected="Point estimate 102.26%, 90% CI 97.32-107.46%.",
        observed="Reproduced to the two decimals printed.",
        tolerance="abs 0.005, as above.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_ema_tier1b.py",
        artifact="validation/ema/cases/ema_pkwp_qa_datasets.json",
    ),
    EvidenceRecord(
        evidence_id="EMA-PKWP-CVWR",
        capabilities=("EMA_HVD_REFERENCE_VARIABILITY",),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="EMA",
        scenario=(
            "The reference-only model for CVwR, on both annexed data sets."
        ),
        dataset="EMA/618604/2008 Rev. 13 annex, Data sets I and II.",
        software_environment="EMA published the output from SAS 9.1.",
        expected="CVwR 47.0% and 11.2% under the Model A/B column.",
        observed="46.96% and 11.17%.",
        tolerance=(
            "abs 0.05 percentage points - EMA printed one decimal, so this "
            "is the rounding bound."
        ),
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_ema_tier1b.py",
        artifact="validation/ema/cases/ema_pkwp_qa_datasets.json",
    ),
    EvidenceRecord(
        evidence_id="EMA-ABEL-LIMITS-TABLE",
        capabilities=("EMA_ABEL_LIMIT_CALCULATION",),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="EMA",
        scenario=(
            "The guideline's own table of widened limits at CVwR 30, 35, 40, "
            "45 and >=50 percent, including the row where the cap binds."
        ),
        dataset="CPMP/EWP/QWP/1401/98 Rev. 1, section 4.1.10, printed table.",
        software_environment="None - the table is published in the guideline.",
        expected=(
            "Five rows, ending at the stated cap 69.84-143.19%, which is "
            "applied AS STATED rather than recomputed."
        ),
        observed="All five rows reproduce to the two decimals published.",
        tolerance="abs 0.005 - the printed precision.",
        status=EvidenceStatus.PASSED_WITH_FINDING,
        established_by="tests/validation/test_ema_tier1b.py",
        findings=("VAL-EMA-ABEL-002",),
        note=(
            "PASSED_WITH_FINDING, not PASSED: PowerTOST recomputes the cap "
            "and gets a fractionally wider pair. be-stats follows the "
            "regulator, and a reader of this row must see that difference."
        ),
    ),
    EvidenceRecord(
        evidence_id="APPENDIX-C-EMA-SAS-METHOD-C",
        capabilities=(
            "FDA_REPLICATE_STANDARD_ABE_FULL",
            "FDA_HVD_UNSCALED_BRANCH",
            "FDA_NTI_UNSCALED_ABE",
        ),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority=(
            "EMA - publishing output for a model EMA transcribes and "
            "attributes to FDA by name. NOT FDA."
        ),
        scenario=(
            "FDA's Appendix C mixed model fitted to EMA Data set I, compared "
            "against EMA's published SAS 9.1 Method C output."
        ),
        dataset="EMA/618604/2008 Rev. 13 annex, Data set I, unbalanced.",
        software_environment="SAS 9.1, as EMA reports it.",
        expected=(
            "Point estimate 115.66, interval 107.10-124.89, within-subject "
            "CVs 47.3% and 35.3%."
        ),
        observed="All five reproduce to the decimals EMA printed.",
        tolerance="The printed precision on each figure.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_appendix_c_full_replicate.py",
        findings=("VAL-FDA-APPENDIX-C-004",),
        note=(
            "The strongest evidence in this package, and it does NOT promote "
            "the capability: the model is FDA's, the numbers are EMA's, and "
            "one regulator's authority is not the other's."
        ),
    ),
    # ------------------------------------------------------------- tier 2 ---
    EvidenceRecord(
        evidence_id="TIER-2-PUBLISHED-REFERENCE",
        capabilities=(),
        tier=EvidenceTier.TIER_2,
        source_type=SourceType.PUBLISHED_REFERENCE,
        source_authority="-",
        scenario=(
            "No textbook or peer-reviewed reference dataset is currently used "
            "by this package."
        ),
        dataset="-",
        software_environment="-",
        expected="-",
        observed="-",
        tolerance="-",
        status=EvidenceStatus.NOT_AVAILABLE,
        established_by="tests/validation/test_dossier_evidence.py",
        note=(
            "Present so the tier is visibly empty rather than absent. An "
            "absent row and an empty one look identical in a report, and only "
            "one of them means somebody checked."
        ),
    ),
    # ------------------------------------------------------------- tier 3 ---
    EvidenceRecord(
        evidence_id="POWERTOST-CROSS-CHECK",
        capabilities=("AVERAGE_BE_2X2", "FDA_HVD_RSABE", "EMA_HVD_ABEL", "FDA_NTI_RSABE"),
        tier=EvidenceTier.TIER_3,
        source_type=SourceType.INDEPENDENT_IMPLEMENTATION,
        source_authority="PowerTOST (R)",
        scenario=(
            "Twelve Monte Carlo cases across ABE, RSABE, ABEL and NTI, "
            "simulating 20,000 studies through the be-stats pipeline against "
            "100,000 per case on the PowerTOST side."
        ),
        dataset="validation/external/cases/*.json",
        software_environment=(
            "A pinned Docker image; versions frozen in "
            "validation/external/environment.lock.json."
        ),
        expected="PowerTOST's power and type-I error estimates.",
        observed=(
            "Agreement within the declared tolerance on every case. Two "
            "methods carry a permanent qualification."
        ),
        tolerance=(
            "A Monte Carlo bound evaluated at the worst case p = 0.5, with a "
            "four-standard-error gap raising a FINDING rather than tightening "
            "the tolerance after the fact."
        ),
        status=EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE,
        established_by="tests/validation/test_external_harness.py",
        # The pinned versions, which are what make the comparison
        # reproducible and are committed. NOT `report.json`: that is the
        # harness's OUTPUT, `.gitignore` excludes it, and citing it as the
        # artefact claimed evidence a reviewer cannot fetch.
        artifact="validation/external/environment.lock.json",
        run_output="validation/external/report.json",
        findings=("VAL-FDA-HVD-001", "VAL-FDA-HVD-002", "VAL-EMA-ABEL-001", "VAL-EMA-ABEL-002"),
        note=(
            "Declared SKIPPED here because the manifest describes what is "
            "available in an ORDINARY environment, where R is absent. The "
            "validation-r workflow runs it in the pinned container and fails "
            "if anything is skipped there. The status a certification run "
            "reads comes from that job, not from this line."
        ),
    ),
    EvidenceRecord(
        evidence_id="REPLICATEBE-APPENDIX-C-CASES",
        capabilities=("FDA_REPLICATE_STANDARD_ABE_FULL",),
        tier=EvidenceTier.TIER_3,
        source_type=SourceType.INDEPENDENT_IMPLEMENTATION,
        source_authority="ReplicateBE.jl 1.0.15 on Julia 1.10.5",
        scenario=(
            "Nine synthetic fully replicate cases compared on all five "
            "covariance parameters, the standard error and the denominator "
            "degrees of freedom."
        ),
        dataset="validation/appendix_c/cases/full_replicate_cases.json",
        software_environment="The same pinned Docker image.",
        expected="ReplicateBE.jl's fitted parameters and Satterthwaite df.",
        observed=(
            "Seven of nine agree to 1e-6. The other two are negative "
            "subject-by-formulation correlation fits, which the oracle "
            "cannot represent at all, and were adjudicated by an independent "
            "algebraic identity instead."
        ),
        tolerance=(
            "1e-6 on the covariance parameters and the standard error; the "
            "df tolerance is stated in df rather than percent, because the "
            "difference is a boundary effect and a relative tolerance would "
            "hide it at small df."
        ),
        status=EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE,
        established_by="tests/validation/test_appendix_c_case_oracle.py",
        artifact="validation/appendix_c/oracle/replicatebe_cases_frozen.json",
        run_output="validation/appendix_c/oracle/replicatebe_cases_run.json",
        findings=("VAL-FDA-APPENDIX-C-003", "VAL-FDA-APPENDIX-C-004"),
        note=(
            "Gated by its own CI job, which fails if any comparison is "
            "SKIPPED. Locally Julia is absent, and the honest status is this "
            "one rather than PASSED."
        ),
    ),
    # ------------------------------------------------------------- tier 4 ---
    EvidenceRecord(
        evidence_id="APPENDIX-C-SYNTHETIC-STRUCTURE",
        capabilities=("FDA_REPLICATE_STANDARD_ABE_FULL",),
        tier=EvidenceTier.TIER_4,
        source_type=SourceType.INTERNAL_STRUCTURAL,
        source_authority="be-stats",
        scenario=(
            "For a balanced, complete, interior fit the Appendix C model "
            "reduces exactly to the classical subject-level analysis and the "
            "Satterthwaite df is exactly n - 2."
        ),
        dataset="Seven constructed cases meeting those conditions.",
        software_environment="be-stats only.",
        expected="The closed-form subject-level result and n - 2.",
        observed="Agreement to 1e-8.",
        tolerance="1e-8, the floating-point headroom for the identity.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_appendix_c_synthetic_cases.py",
        note=(
            "An algebraic identity sharing no code with the REML "
            "implementation. Structural conformance, and explicitly NOT tier "
            "1A - it establishes what mathematics says, not what FDA says."
        ),
    ),
    EvidenceRecord(
        evidence_id="REFERENCE-VARIANCE-SIMULATION",
        capabilities=("FDA_HVD_REFERENCE_VARIANCE",),
        tier=EvidenceTier.TIER_4,
        source_type=SourceType.INTERNAL_STRUCTURAL,
        source_authority="be-stats",
        scenario="The sWR estimator's behaviour under simulation.",
        dataset="Simulated replicate studies.",
        software_environment="be-stats only.",
        expected="Unbiasedness on the variance scale, and correct df.",
        observed="Within Monte Carlo error.",
        tolerance="A Monte Carlo bound at the simulated count.",
        status=EvidenceStatus.PASSED,
        established_by="tests/validation/test_reference_variance_simulation.py",
    ),
    # ----------------------------------------------------------- pending ---
    EvidenceRecord(
        evidence_id="SAS-APPENDIX-C-PARTIAL-REPLICATE",
        capabilities=("FDA_REPLICATE_STANDARD_ABE_PARTIAL",),
        tier=EvidenceTier.TIER_1B,
        source_type=SourceType.REGULATOR_PUBLISHED_NUMBERS,
        source_authority="Licensed SAS, pending",
        scenario=(
            "FDA's Appendix C statements run in a licensed SAS session on a "
            "partial replicate dataset, reporting the estimate, its standard "
            "error and the Satterthwaite denominator degrees of freedom."
        ),
        dataset=(
            "The generated validation package, identified by its manifest "
            "SHA-256."
        ),
        software_environment="A licensed SAS environment. Not yet run.",
        expected=(
            "NOT STATED. Recording an expected df here would encode a "
            "candidate as the answer, which is the entire failure this "
            "blocker exists to prevent."
        ),
        observed="None. No SAS evidence has been accepted.",
        tolerance=(
            "To be declared at review time, before the SAS output is read - "
            "a tolerance chosen after seeing the result is not a tolerance."
        ),
        status=EvidenceStatus.PENDING,
        established_by="tests/validation/test_dossier_evidence.py",
        findings=("VAL-FDA-APPENDIX-C-PARTIAL-001", "VAL-FDA-APPENDIX-C-002"),
        note=(
            "The one record whose arrival changes a capability's status, and "
            "it changes nothing on arrival: acceptance is a separate, "
            "human-authorised review."
        ),
    ),
)


EVIDENCE: dict[str, EvidenceRecord] = {r.evidence_id: r for r in EVIDENCE_MANIFEST}


#: The id of the record a real SAS result would fill in.
SAS_EVIDENCE_RECORD_ID = "SAS-APPENDIX-C-PARTIAL-REPLICATE"


#: HOW AN ACCEPTED SAS RESULT ENTERS THIS MANIFEST, WRITTEN DOWN NOW.
#:
#: The dossier has to know the shape of evidence it does not yet have, or the
#: day it arrives somebody will invent a route for it under time pressure. So
#: the intake is specified here, before there is anything to intake, and the
#: order is the part that matters: nothing is written until a human has
#: accepted, and acceptance is recorded somewhere this package cannot reach.
#:
#: It is prose rather than code on purpose. A function that "ingests SAS
#: evidence" would be a function somebody could call, and the whole control is
#: that a person has to do it deliberately in a reviewed change.
SAS_EVIDENCE_INTAKE = """\
When a real SAS Appendix C partial-replicate result has been uploaded,
compared and ACCEPTED through the governed human review workflow - not merely
uploaded, and not merely matching - a separate reviewed pull request does the
following, in this order:

  1. Fill in this record's `software_environment` with the SAS version and
     platform from the accepted attestation, and `dataset` with the package
     id and archive SHA-256 the operator actually ran.
  2. Fill in `expected` with the SAS output, and `observed` with what
     be-stats computes on the same dataset. Declare `tolerance` BEFORE
     comparing; a tolerance chosen after seeing the result is not one.
  3. Move `status` from PENDING to PASSED, PASSED_WITH_FINDING, or - if they
     disagree - leave it PENDING and raise a finding. A disagreement is a
     question about the comparison first, be-stats second, SAS third.
  4. Only then consider the capability. Implementing Appendix C for the
     partial replicate design is a SEPARATE change with its own tests, and
     the evidence arriving does not perform it.
  5. Only after that, and only with the transition named in
     `release_gate.REVIEWED_TRANSITIONS`, may a status move.

`blockers.PARTIAL_ORACLE_READY` and `blockers.REAL_SAS_ORACLE_STATUS` are
edited in step 5 and never earlier. Nothing in this package sets either as a
side effect of an upload, and no test fixture may set them at all.
"""


def evidence_for(capability_id: str) -> list[EvidenceRecord]:
    """Every record bearing on one capability."""
    return [r for r in EVIDENCE_MANIFEST if capability_id in r.capabilities]


def best_tier_for(capability_id: str) -> EvidenceTier:
    """The strongest tier of evidence a capability holds.

    Only records that actually established something count. A PENDING or
    SKIPPED record contributes nothing, which is the whole reason those
    statuses exist - and the reason this function cannot be replaced by
    reading the tier column.
    """
    order = [
        EvidenceTier.TIER_1B,
        EvidenceTier.TIER_1A,
        EvidenceTier.TIER_2,
        EvidenceTier.TIER_3,
        EvidenceTier.TIER_4,
    ]
    established = {
        r.tier
        for r in evidence_for(capability_id)
        if r.status in (EvidenceStatus.PASSED, EvidenceStatus.PASSED_WITH_FINDING)
    }
    for tier in order:
        if tier in established:
            return tier
    return EvidenceTier.NONE


def records_by_status(status: EvidenceStatus) -> list[EvidenceRecord]:
    return [r for r in EVIDENCE_MANIFEST if r.status is status]
