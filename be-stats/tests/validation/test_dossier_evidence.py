"""The dossier must describe this package, not a remembered version of it.

Every test here is a link between two things that could otherwise drift: the
manifest and the tests it names, the register and the committed finding files,
the generated document and the matrix it came from, the claimed statuses and
the evidence that would have to support them.

Drift is not hypothetical in this repository. `validation/findings/README.md`
carried the line "No finding is currently OPEN" while
`VAL-FDA-APPENDIX-C-002.json` had `status: OPEN`, and listed five findings out
of the nine that existed. Nobody was careless; nothing could fail.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from be_stats.dossier.blockers import (
    BLOCKERS,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
    BlockerStatus,
)
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.evidence import (
    EVIDENCE,
    EVIDENCE_MANIFEST,
    EvidenceStatus,
    best_tier_for,
    evidence_for,
)
from be_stats.dossier.findings import (
    FINDINGS,
    FINDINGS_REGISTER,
    FindingStatus,
)
from be_stats.dossier.release_gate import (
    REVIEWED_TRANSITIONS,
    certification_blockers,
    check_capability,
    check_release_gate,
)
from be_stats.dossier.render import render_dossier
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import ValidationStatus

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2]
FINDINGS_DIR = PACKAGE_ROOT / "validation" / "findings"
GENERATED_DOSSIER = PACKAGE_ROOT / "validation" / "DOSSIER.md"


# ------------------------------------------------------------- manifest ---


def test_every_evidence_record_names_a_real_test():
    """A manifest pointing at a test that does not exist proves nothing."""
    for record in EVIDENCE_MANIFEST:
        path = PACKAGE_ROOT / record.established_by
        assert path.exists(), (
            f"{record.evidence_id} says it is established by "
            f"{record.established_by!r}, which does not exist."
        )


def test_every_evidence_artifact_exists():
    for record in EVIDENCE_MANIFEST:
        if not record.artifact:
            continue
        assert (PACKAGE_ROOT / record.artifact).exists(), (
            f"{record.evidence_id} cites artefact {record.artifact!r}, absent."
        )


def test_every_evidence_record_names_real_capabilities():
    for record in EVIDENCE_MANIFEST:
        for capability_id in record.capabilities:
            assert capability_id in CAPABILITY_MATRIX, (
                f"{record.evidence_id} cites unknown {capability_id!r}"
            )


def test_every_evidence_record_names_real_findings():
    for record in EVIDENCE_MANIFEST:
        for finding_id in record.findings:
            assert finding_id in FINDINGS, (
                f"{record.evidence_id} cites unknown finding {finding_id!r}"
            )


def test_every_evidence_record_states_a_tolerance_and_a_reason():
    """A tolerance with no reason is a number somebody tuned until it passed."""
    for record in EVIDENCE_MANIFEST:
        assert record.tolerance.strip(), record.evidence_id
        assert record.expected.strip(), record.evidence_id
        assert record.observed.strip(), record.evidence_id


def test_a_record_with_a_finding_is_not_reported_as_a_clean_pass():
    """PASSED beside an unmentioned difference is a green tick over a fact."""
    for record in EVIDENCE_MANIFEST:
        if record.findings and record.status is EvidenceStatus.PASSED:
            qualifying = [
                FINDINGS[f]
                for f in record.findings
                if FINDINGS[f].severity.value in ("blocking", "qualifying")
                and FINDINGS[f].status is not FindingStatus.PREEMPTED
            ]
            unresolved = [f for f in qualifying if f.is_open]
            assert not unresolved, (
                f"{record.evidence_id} reads PASSED while "
                f"{[f.finding_id for f in unresolved]} is open against it."
            )


def test_an_unavailable_environment_is_never_reported_as_passed():
    """The rule that makes the whole manifest worth reading.

    A comparison that did not run is indistinguishable from one that would
    have failed, so it may never be spelled the same way as one that passed.
    """
    external = [
        r
        for r in EVIDENCE_MANIFEST
        if r.tier is EvidenceTier.TIER_3
    ]
    assert external, "No tier-3 records; this guard would pass vacuously."
    for record in external:
        assert record.status is not EvidenceStatus.PASSED or "container" not in (
            record.software_environment.lower()
        ), (
            f"{record.evidence_id} claims PASSED for a comparison that needs "
            "an external environment the ordinary suite does not have."
        )


def test_the_pending_sas_record_states_no_expected_value():
    """Writing an expected df would encode a candidate as the answer."""
    record = next(
        r for r in EVIDENCE_MANIFEST if r.evidence_id == "SAS-APPENDIX-C-PARTIAL-REPLICATE"
    )
    assert record.status is EvidenceStatus.PENDING
    assert not re.search(r"\d+\.\d+", record.expected), (
        f"The pending SAS record's expected value contains a number: "
        f"{record.expected!r}"
    )
    assert "NOT STATED" in record.expected


def test_the_sas_intake_path_is_specified_before_the_evidence_exists():
    """The dossier knows the shape of evidence it does not yet have.

    Written down now, because the day a real SAS result arrives is the worst
    possible day to design the route it takes. The order is the control: a
    human accepts, then a reviewed change writes the record, then - separately
    - a status may move.
    """
    from be_stats.dossier.evidence import (
        SAS_EVIDENCE_INTAKE,
        SAS_EVIDENCE_RECORD_ID,
    )

    assert SAS_EVIDENCE_RECORD_ID in EVIDENCE
    assert EVIDENCE[SAS_EVIDENCE_RECORD_ID].status is EvidenceStatus.PENDING

    # The five steps, and the two things that must not happen automatically.
    for step in ("1.", "2.", "3.", "4.", "5."):
        assert step in SAS_EVIDENCE_INTAKE
    # Normalised, because the constant is wrapped for reading and a phrase
    # that straddles a line break would otherwise fail for the wrong reason.
    flat = " ".join(SAS_EVIDENCE_INTAKE.split())
    assert "Declare `tolerance` BEFORE comparing" in flat
    assert "REVIEWED_TRANSITIONS" in flat
    assert "never earlier" in flat
    assert "no test fixture may set them" in flat


def test_no_function_ingests_sas_evidence_automatically():
    """The control is that a person has to do it in a reviewed change.

    Checked on the module's own namespace rather than on its text: a callable
    named for ingestion is a callable somebody can call, and its absence is the
    property worth asserting.
    """
    import be_stats.dossier.evidence as module

    for name in dir(module):
        assert not name.startswith("ingest"), (
            f"be_stats.dossier.evidence.{name} would let SAS evidence enter "
            "the manifest without a reviewed change."
        )
        assert not name.startswith("accept"), name


def test_best_tier_ignores_evidence_that_established_nothing():
    """A skipped or pending record must not raise a capability's tier."""
    assert best_tier_for("FDA_REPLICATE_STANDARD_ABE_PARTIAL") is EvidenceTier.NONE, (
        "The partial capability has a PENDING tier-1B record. If that counted, "
        "an awaited piece of evidence would look like an established one."
    )


def test_every_implemented_capability_has_some_evidence_record():
    for record in CAPABILITY_MATRIX.values():
        if record.validation_status is ValidationStatus.NOT_IMPLEMENTED:
            continue
        if record.validation_status is ValidationStatus.IMPLEMENTED:
            # Structural: the tests are the evidence, and there is no external
            # claim to record. Asserted rather than skipped silently.
            continue
        assert evidence_for(record.capability_id), (
            f"{record.capability_id} is {record.validation_status} with no "
            "evidence record at all."
        )


# ------------------------------------------------------------- findings ---


def _committed_findings() -> dict[str, dict]:
    """The committed JSON records, excluding the raw evidence data files."""
    found = {}
    for path in sorted(FINDINGS_DIR.glob("*.json")):
        if path.stem.endswith("-evidence"):
            continue
        found[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return found


def test_the_register_agrees_with_the_committed_finding_files():
    """Id, status and affected method, checked both ways."""
    committed = _committed_findings()

    for finding in FINDINGS_REGISTER:
        if not finding.evidence_file:
            continue
        stem = pathlib.Path(finding.evidence_file).stem
        assert stem in committed, (
            f"{finding.finding_id} cites {finding.evidence_file}, absent."
        )
        record = committed[stem]
        assert record["finding_id"] == finding.finding_id
        assert record["status"].lower() == finding.status.value, (
            f"{finding.finding_id}: the register says {finding.status} and "
            f"the committed file says {record['status']}."
        )


def test_every_committed_finding_is_in_the_register():
    """The direction that catches a finding nobody carried forward."""
    registered = {
        pathlib.Path(f.evidence_file).stem
        for f in FINDINGS_REGISTER
        if f.evidence_file
    }
    missing = set(_committed_findings()) - registered
    assert not missing, (
        f"Committed findings absent from the register: {sorted(missing)}. A "
        "finding nobody carries forward is one nobody reads."
    )


def test_the_register_carries_the_findings_the_brief_names():
    """Named individually, because "we have a register" is not the ask."""
    ids = set(FINDINGS)
    assert "VAL-FDA-APPENDIX-C-PARTIAL-001" in ids  # partial oracle pending
    assert "DOSSIER-002" in ids  # manual SAS execution integrity
    assert "VAL-FDA-APPENDIX-C-003" in ids  # ReplicateBE negative correlation
    assert "VAL-FDA-APPENDIX-C-004" in ids  # boundary Satterthwaite difference
    assert "DOSSIER-003" in ids  # remaining independent validation gap


def test_every_finding_names_its_resolution_condition():
    """Including the ones nothing closes - which must say so."""
    for finding in FINDINGS_REGISTER:
        assert finding.description.strip(), finding.finding_id
        assert finding.evidence.strip(), finding.finding_id
        assert finding.resolution_condition.strip(), (
            f"{finding.finding_id} does not say what would close it."
        )


def test_every_finding_names_real_capabilities_and_blockers():
    for finding in FINDINGS_REGISTER:
        for capability_id in finding.affected_capabilities:
            assert capability_id in CAPABILITY_MATRIX, (
                f"{finding.finding_id} cites unknown {capability_id!r}"
            )
        if finding.blocker_id:
            assert finding.blocker_id in BLOCKERS, (
                f"{finding.finding_id} cites unknown blocker "
                f"{finding.blocker_id!r}"
            )


# ------------------------------------------------------------- blockers ---


def test_partial_oracle_ready_is_false():
    assert PARTIAL_ORACLE_READY is False


def test_partial_oracle_ready_matches_the_committed_finding():
    """The runtime flag and the committed evidence file cannot disagree."""
    record = json.loads(
        (FINDINGS_DIR / "VAL-FDA-APPENDIX-C-PARTIAL-001.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["partial_oracle_ready"] is PARTIAL_ORACLE_READY


def test_the_real_sas_oracle_status_is_pending():
    assert REAL_SAS_ORACLE_STATUS == "PENDING"


def test_the_partial_replicate_blocker_is_open():
    blocker = BLOCKERS["APPENDIX-C-PARTIAL-ORACLE"]
    assert blocker.status is BlockerStatus.OPEN
    assert "FDA_REPLICATE_STANDARD_ABE_PARTIAL" in blocker.affected_capabilities
    assert "SAS" in blocker.required_evidence


def test_every_blocker_candidate_states_why_it_is_insufficient():
    """A candidate with no stated insufficiency is either the answer or unread.

    This is the structural defence against a candidate becoming a constant:
    every one of them carries, in the same object, the reason it cannot be
    used.
    """
    for blocker in BLOCKERS.values():
        assert blocker.required_evidence.strip(), blocker.blocker_id
        for candidate in blocker.candidate_evidence:
            assert candidate.establishes.strip(), blocker.blocker_id
            assert candidate.insufficient_because.strip(), (
                f"{blocker.blocker_id}: candidate {candidate.source!r} does "
                "not say why it is insufficient."
            )


def test_no_candidate_df_is_encoded_as_regulator_truth():
    """The candidate exists as a candidate and nowhere as a value.

    Deliberately NOT a text search for "19.89" across the package - the
    blocker record discusses it, correctly, and a blunt search would either
    fail on that paragraph or be weakened until it matched nothing. This
    checks the places a value would actually have to live to be used:

      - the provenance index, where constants live
      - the capability matrix's own fields
      - the evidence manifest's expected values
    """
    from be_stats.dossier.constants import CONSTANT_INDEX

    for record in CONSTANT_INDEX.values():
        assert not (19.0 <= record.value <= 23.0), (
            f"{record.constant_id} = {record.value} sits in the range of the "
            "candidate partial-replicate denominator df and is indexed as a "
            "usable constant."
        )

    partial = CAPABILITY_MATRIX["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    assert partial.validation_status is ValidationStatus.NOT_IMPLEMENTED
    assert partial.evidence_tier is EvidenceTier.NONE

    for record in EVIDENCE_MANIFEST:
        if "FDA_REPLICATE_STANDARD_ABE_PARTIAL" not in record.capabilities:
            continue
        assert record.status in (
            EvidenceStatus.PENDING,
            EvidenceStatus.NOT_AVAILABLE,
        ), (
            f"{record.evidence_id} claims established evidence for the "
            "partial replicate capability, which has none."
        )


def test_the_candidate_value_appears_only_where_it_is_qualified():
    """Where the number IS written, it is written beside its insufficiency.

    The complement of the test above: the value is allowed in the blocker's
    candidate records, and asserting that is different from asserting it
    appears nowhere.
    """
    mentions = [
        candidate
        for blocker in BLOCKERS.values()
        for candidate in blocker.candidate_evidence
        if re.search(r"\b(19\.\d+|22\.\d+)\b", candidate.establishes)
    ]
    assert mentions, (
        "The candidate values are no longer recorded anywhere. They should be "
        "- a reviewer needs to know what has been considered and rejected."
    )
    for candidate in mentions:
        assert candidate.insufficient_because.strip()


# --------------------------------------------------------- release gate ---


def test_the_release_gate_passes_on_the_current_matrix():
    report = check_release_gate()
    assert report.passed, "\n".join(report.to_lines())


def test_validated_capabilities_have_the_required_evidence_metadata():
    for record in CAPABILITY_MATRIX.values():
        if record.validation_status is not ValidationStatus.VALIDATED:
            continue
        result = check_capability(
            record.capability_id, reviewed_transitions=REVIEWED_TRANSITIONS
        )
        assert result.passed, (
            f"{record.capability_id} claims VALIDATED: "
            + "; ".join(result.violations)
        )
        assert any("tier-1B" in s for s in result.satisfied)


def test_promotion_without_a_reviewed_transition_is_refused():
    """One numerical match must not be enough. Asserted by removing consent."""
    for capability_id in REVIEWED_TRANSITIONS:
        result = check_capability(capability_id, reviewed_transitions=frozenset())
        assert not result.passed
        assert any("reviewed" in v for v in result.violations)


def test_promoting_an_unevidenced_capability_fails_the_gate(monkeypatch):
    """The gate must actually bite. Claim VALIDATED and watch it refuse."""
    from be_stats.spec import Method

    patched = dict(__import__("be_stats.spec", fromlist=["VALIDATION"]).VALIDATION)
    patched[Method.FDA_HVD_RSABE] = ValidationStatus.VALIDATED
    monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)

    result = check_capability(
        "FDA_HVD_RSABE",
        reviewed_transitions=frozenset({"FDA_HVD_RSABE"}),
    )
    assert not result.passed
    assert any("tier-1B" in v for v in result.violations), (
        "FDA HVD RSABE has tier-1A and tier-3 evidence and no tier-1B. "
        "Promoting it must fail for exactly that reason."
    )


def test_certification_reports_a_missing_environment_as_a_blocker():
    """CI may pass with R absent. Certification may not."""
    problems = certification_blockers()
    assert any("skipped_environment_unavailable" in p for p in problems), (
        "The external oracle comparisons are not runnable in this "
        "environment, and certification must say so rather than inherit a "
        "green CI run."
    )
    assert any("SAS-APPENDIX-C-PARTIAL-REPLICATE" in p for p in problems)


# ------------------------------------------------------ generated docs ---


def test_generated_documentation_matches_the_canonical_matrix():
    """Regenerate and compare. Editing the file by hand fails here.

    This is what makes the document trustworthy: it cannot be wrong without
    the build going red, which is precisely what the hand-maintained findings
    README lacked.
    """
    assert GENERATED_DOSSIER.exists(), (
        f"{GENERATED_DOSSIER} is missing. Regenerate with "
        "`python -m be_stats.dossier.render be-stats/validation/DOSSIER.md`."
    )
    committed = GENERATED_DOSSIER.read_text(encoding="utf-8")
    assert committed == render_dossier(), (
        "The committed dossier no longer matches the canonical source. "
        "Regenerate it; do not edit it."
    )


def test_the_findings_readme_table_matches_the_register():
    """The table that had gone stale in two ways at once.

    It listed five of the nine findings and ended with "No finding is currently
    OPEN" while VAL-FDA-APPENDIX-C-002 was open. It is generated now, and this
    is the failure that would have caught it.
    """
    from be_stats.dossier.render import splice_findings_table

    readme = FINDINGS_DIR / "README.md"
    committed = readme.read_text(encoding="utf-8")
    assert committed == splice_findings_table(committed), (
        "The findings README's generated table no longer matches the "
        "register. Regenerate with `python -m be_stats.dossier.render "
        "be-stats/validation/findings/README.md`."
    )


def test_the_findings_readme_names_every_open_finding():
    """Belt and braces on the specific sentence that was wrong.

    Asserted on the ids rather than by searching for the old sentence: a
    search for "No finding is currently OPEN" would pass the moment somebody
    reworded it, whether or not the list had become correct.
    """
    readme = (FINDINGS_DIR / "README.md").read_text(encoding="utf-8")
    for finding in FINDINGS_REGISTER:
        if finding.is_open:
            assert finding.finding_id in readme, finding.finding_id


def test_the_generated_document_says_it_is_generated():
    assert "GENERATED FILE" in GENERATED_DOSSIER.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "heading",
    [
        "## Capability matrix",
        "## Regulatory decision routing matrix",
        "## Validation evidence manifest",
        "## Source provenance",
        "## Refusal semantics",
        "## Known blockers",
        "## Findings register",
        "## Method catalogue",
        "## Release gate",
    ],
)
def test_the_generated_document_carries_every_section(heading):
    assert heading in GENERATED_DOSSIER.read_text(encoding="utf-8")


def test_the_generated_document_states_the_partial_oracle_flag():
    text = GENERATED_DOSSIER.read_text(encoding="utf-8")
    assert "`partial_oracle_ready` = **false**" in text
    assert "`real_sas_oracle_status` = **PENDING**" in text
