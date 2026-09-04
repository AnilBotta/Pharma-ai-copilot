"""What is unresolved, stated as a record rather than remembered.

A BLOCKER IS NOT A TODO

A TODO is work somebody intends to do. A blocker here is a capability that
CANNOT be implemented or promoted until a specific external thing exists, and
the record's job is to make the shape of that thing precise enough that nobody
has to reconstruct the argument. "We need SAS" is a wish. "A licensed SAS
PROC MIXED run of the Appendix C model on a partial replicate dataset,
establishing the Satterthwaite denominator degrees of freedom" is a purchase
order.

THE CANDIDATE IS NOT THE ANSWER

The partial-replicate blocker carries a candidate denominator df of about
19.89, arrived at by independent observed-information calculation and
corroborated against EMA's published interval. It is recorded as a CANDIDATE,
in `candidate_evidence`, and there is no field in this module that could hold
it as a value the engine would use. That is deliberate: a candidate stored
where a constant belongs becomes a constant one refactor later.

`test_no_candidate_df_is_encoded_as_regulator_truth` asserts that no module in
`be_stats` contains the candidate value, and that the blocker remains open.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BlockerStatus(StrEnum):
    #: The external thing does not exist yet. The capability stays as it is.
    OPEN = "open"
    #: The external thing exists and has not yet been reviewed and accepted.
    #: A distinct state from RESOLVED on purpose: evidence arriving is not
    #: evidence accepted, and the gap between them is where an unreviewed
    #: promotion would happen.
    EVIDENCE_RECEIVED_PENDING_REVIEW = "evidence_received_pending_review"
    #: Reviewed, accepted, and the capability moved. Reaching this state is a
    #: governed change, never an automatic consequence of a numerical match.
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    """Something that bears on the blocker without settling it."""

    source: str
    #: What it establishes, stated narrowly.
    establishes: str
    #: Why it is not sufficient on its own. Required - a candidate with no
    #: stated insufficiency is either the answer or has not been thought
    #: about, and neither should be recorded as a candidate.
    insufficient_because: str


@dataclass(frozen=True, slots=True)
class Blocker:
    """One unresolved external dependency."""

    blocker_id: str
    status: BlockerStatus
    #: The capability ids this holds up.
    affected_capabilities: tuple[str, ...]
    #: One sentence naming the missing thing.
    summary: str
    #: What would have to exist, precisely enough to go and get it.
    required_evidence: str
    candidate_evidence: tuple[EvidenceCandidate, ...] = ()
    #: What the engine does in the meantime.
    current_behaviour: str = ""
    reference: str = ""


#: WHETHER A TRUSTWORTHY PARTIAL-REPLICATE ORACLE EXISTS.
#:
#: The canonical flag. False, and it stays false until a licensed SAS run of
#: FDA's Appendix C model on a partial replicate dataset has been produced,
#: reviewed and accepted through the governed workflow - which is a separate,
#: human-authorised change and not a consequence of anything in this release.
#:
#: `test_partial_oracle_ready_matches_the_finding` asserts this agrees with
#: `validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.json`, so the runtime
#: constant and the committed evidence file cannot disagree.
PARTIAL_ORACLE_READY: bool = False


APPENDIX_C_PARTIAL_ORACLE = Blocker(
    blocker_id="APPENDIX-C-PARTIAL-ORACLE",
    status=BlockerStatus.OPEN,
    affected_capabilities=(
        "FDA_REPLICATE_STANDARD_ABE_PARTIAL",
        "FDA_HVD_UNSCALED_BRANCH",
    ),
    summary=(
        "There is no trustworthy oracle for the Satterthwaite denominator "
        "degrees of freedom of FDA's Appendix C model on a PARTIAL replicate "
        "(2x3x3) design, so the capability is not implemented."
    ),
    required_evidence=(
        "A licensed SAS PROC MIXED run of the Appendix C statements - "
        "MODEL Y = SEQ PER TRT / DDFM=SATTERTH; RANDOM TRT / TYPE=FA0(2) "
        "SUB=SUBJ G; REPEATED / GRP=TRT SUB=SUBJ - on a partial replicate "
        "dataset whose inputs are published or supplied, reporting the "
        "estimate, its standard error and the denominator degrees of freedom."
    ),
    candidate_evidence=(
        EvidenceCandidate(
            source="EMA/618604/2008 Rev. 13, published Data set II output",
            establishes=(
                "The point estimate and confidence interval a partial "
                "replicate analysis of that dataset produced under SAS."
            ),
            insufficient_because=(
                "The published output pins down the interval, not the "
                "denominator df directly. Several (SE, df) pairs reproduce the "
                "same printed interval to the decimals published."
            ),
        ),
        EvidenceCandidate(
            source=(
                "Independent observed-information calculation, sharing no "
                "code with the REML implementation"
            ),
            establishes=(
                "A candidate denominator df of approximately 19.89, "
                "compatible with the published interval under the "
                "corroborated standard error."
            ),
            insufficient_because=(
                "It is this package's own arithmetic checking this package's "
                "own arithmetic. Tier 4. It cannot establish what SAS "
                "computes, which is what Appendix C specifies."
            ),
        ),
        EvidenceCandidate(
            source="ReplicateBE.jl 1.0.15",
            establishes=(
                "Exact agreement with EMA's published SAS output on the FULLY "
                "replicate design, and a value of 22.540 on the partial "
                "replicate one."
            ),
            insufficient_because=(
                "22.540 is incompatible with EMA's published interval under "
                "the corroborated standard error, so the oracle that "
                "reproduces SAS exactly on one design does not on the other. "
                "An oracle that disagrees with the published output is not an "
                "oracle for this case."
            ),
        ),
    ),
    current_behaviour=(
        "FDA_REPLICATE_STANDARD_ABE_PARTIAL is NOT_IMPLEMENTED. A partial "
        "replicate study routed to ordinary average BE returns decided=false, "
        "passes=null, with refusal code "
        "APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED. No number is produced."
    ),
    reference="validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.md",
)


FDA_TIER_1B_WORKED_EXAMPLE = Blocker(
    blocker_id="FDA-TIER-1B-WORKED-EXAMPLE",
    status=BlockerStatus.OPEN,
    affected_capabilities=(
        "FDA_HVD_RSABE",
        "FDA_NTI_RSABE",
        "FDA_REPLICATE_STANDARD_ABE_FULL",
        "FDA_HVD_REFERENCE_VARIANCE",
        "FDA_HVD_TREATMENT_CONTRAST",
        "FDA_NTI_REFERENCE_SCALED_CRITERION",
        "FDA_NTI_VARIABILITY_RATIO",
        "FDA_NTI_UNSCALED_ABE",
    ),
    summary=(
        "No FDA capability can reach VALIDATED, because FDA has published no "
        "worked numerical example of any of these procedures."
    ),
    required_evidence=(
        "An FDA-published dataset with published results for the procedure "
        "being claimed, or a licensed SAS run of FDA's own example code on "
        "inputs that are published."
    ),
    candidate_evidence=(
        EvidenceCandidate(
            source=(
                "EMA/618604/2008 Rev. 13 Data set I, SAS 9.1 Method C output"
            ),
            establishes=(
                "That be-stats reproduces a REGULATOR-published SAS result "
                "for the model EMA transcribes and attributes to FDA by name - "
                "point estimate, interval and both within-subject CVs, to the "
                "decimals printed."
            ),
            insufficient_because=(
                "The model is FDA's and the numbers are EMA's. Promoting an "
                "FDA capability on it would inflate one regulator's authority "
                "into another's. This is why FDA_REPLICATE_STANDARD_ABE_FULL "
                "holds tier-1B evidence and remains IMPLEMENTED_UNVALIDATED."
            ),
        ),
        EvidenceCandidate(
            source="PowerTOST, pinned, run in a locked container",
            establishes="Agreement with an independent implementation.",
            insufficient_because=(
                "Tier 3. PowerTOST is an implementation oracle, not a "
                "regulatory authority, and it already diverges from FDA's "
                "stated switching threshold - see VAL-FDA-HVD-002."
            ),
        ),
    ),
    current_behaviour=(
        "Every FDA method and capability that produces a number stands at "
        "IMPLEMENTED_UNVALIDATED. Results are returned with the status and "
        "limitations attached; nothing is withheld and nothing is described "
        "as validated."
    ),
    reference="validation/README.md",
)


MANUAL_SAS_EXECUTION_INTEGRITY = Blocker(
    blocker_id="MANUAL-SAS-EXECUTION-INTEGRITY",
    status=BlockerStatus.OPEN,
    affected_capabilities=("FDA_REPLICATE_STANDARD_ABE_PARTIAL",),
    summary=(
        "In the manual upload workflow, the package hashes and the uploaded "
        "result are verifiable; that the uploaded output was produced by "
        "running THAT program in a licensed SAS session is attested by an "
        "operator, not proven by the system."
    ),
    required_evidence=(
        "A managed or directly connected SAS execution path, where the "
        "platform submits the program and receives the output without a "
        "human-carried step in between."
    ),
    candidate_evidence=(
        EvidenceCandidate(
            source="Package manifest SHA-256 verification on upload",
            establishes=(
                "That the dataset and program uploaded against are byte-"
                "identical to the ones generated, and that the result parses."
            ),
            insufficient_because=(
                "It establishes WHAT was supposed to run, not that it ran. A "
                "result typed by hand from a different session would pass "
                "every hash check."
            ),
        ),
        EvidenceCandidate(
            source="Operator attestation, recorded and append-only",
            establishes=(
                "A named, authorised person's statement of the environment, "
                "the SAS version and the fact of execution."
            ),
            insufficient_because=(
                "An attestation is testimony. It is the right control for "
                "this workflow and it is not machine-verifiable evidence."
            ),
        ),
    ),
    current_behaviour=(
        "Uploads are labelled with their declared evidence origin, and only "
        "MANUAL_EXTERNAL_SAS may be accepted as oracle evidence. A TEST_FIXTURE "
        "origin can never be accepted however complete it is."
    ),
    reference="docs/SAS_FIRST_LIVE_RUN.md",
)


#: The blocker matrix.
BLOCKERS: dict[str, Blocker] = {
    b.blocker_id: b
    for b in (
        APPENDIX_C_PARTIAL_ORACLE,
        FDA_TIER_1B_WORKED_EXAMPLE,
        MANUAL_SAS_EXECUTION_INTEGRITY,
    )
}


#: Whether a real, accepted SAS oracle result exists for the partial replicate
#: design. PENDING until one has been uploaded, reviewed and accepted through
#: the governed workflow. Never set by a test fixture, and never set here as a
#: side effect of an upload arriving.
REAL_SAS_ORACLE_STATUS: str = "PENDING"


def open_blockers() -> list[Blocker]:
    return [b for b in BLOCKERS.values() if b.status is not BlockerStatus.RESOLVED]


def blockers_for(capability_id: str) -> list[Blocker]:
    """Every blocker holding up one capability."""
    return [
        b for b in BLOCKERS.values() if capability_id in b.affected_capabilities
    ]
