"""One regulator's published numbers may not qualify another regulator's capability.

THE DEFECT THIS FILE PINS

`release_gate.check_capability` said a VALIDATED claim needs "a regulator's own
published numbers" and checked `tier is TIER_1B`. `APPENDIX-C-EMA-SAS-METHOD-C`
is EMA's published SAS output, tier 1B, and attached to three FDA capabilities.
For every one of them the tier-1B condition was therefore SATISFIED by EMA's
numbers; what kept them from VALIDATED was whichever blocker or finding happened
to be open. FDA_HVD_UNSCALED_BRANCH was held back by one blocker alone.

WHAT IS AND IS NOT CHANGED

The evidence is not detached from those capabilities. It is good evidence that
the shared Appendix C model computes correctly, and it stays attached, visible
and tier 1B. What changes is that the gate now asks whether a tier-1B record is
QUALIFYING for the capability in front of it - and for an FDA capability, EMA's
numbers are SUPPORTING and never qualifying.

HOW THE GATE IS ISOLATED

Most tests below claim VALIDATED for a capability, name it as reviewed, and
clear the blockers and findings that stand in its way today. Otherwise a
failure could come from a blocker, and the test would prove nothing about the
authority condition. Tests that leave the blockers in place say so.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap

import pytest

import be_stats.dossier.release_gate as release_gate_module
from be_stats.dossier.blockers import PARTIAL_ORACLE_READY, REAL_SAS_ORACLE_STATUS
from be_stats.dossier.capabilities import CAPABILITY_MATRIX, CapabilityRecord
from be_stats.dossier.evidence import (
    EVIDENCE_MANIFEST,
    EvidenceRecord,
    EvidenceStatus,
    SourceType,
    best_tier_for,
    evidence_for,
)
from be_stats.dossier.evidence_search import FDA_NTI_TIER_1B_SEARCH, adopted_sources
from be_stats.dossier.release_gate import (
    REVIEWED_TRANSITIONS,
    Tier1BRelation,
    assess_tier_1b,
    certification_blockers,
    check_capability,
    check_release_gate,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import (
    EMA_BIOEQUIVALENCE_HVD,
    Authority,
    Citation,
    ValidationStatus,
    authority_of,
)
from be_stats.spec import CAPABILITY_VALIDATION, VALIDATION, Jurisdiction, Method

APPENDIX_C = "APPENDIX-C-EMA-SAS-METHOD-C"
SAS_PENDING = "SAS-APPENDIX-C-PARTIAL-REPLICATE"

#: The three FDA capabilities EMA's Appendix C output is attached to.
FDA_APPENDIX_C_CAPABILITIES = (
    "FDA_REPLICATE_STANDARD_ABE_FULL",
    "FDA_HVD_UNSCALED_BRANCH",
    "FDA_NTI_UNSCALED_ABE",
)

#: The three EMA capabilities promoted in the ABEL release, on EMA's numbers.
EMA_VALIDATED = (
    "EMA_HVD_REFERENCE_VARIABILITY",
    "EMA_REPLICATE_METHOD_A",
    "EMA_ABEL_LIMIT_CALCULATION",
)


# ------------------------------------------------------------- helpers ---


def _claim_validated(monkeypatch, capability_id: str) -> None:
    """Make `spec` claim VALIDATED for one capability, as a promotion diff would."""
    key = CAPABILITY_MATRIX[capability_id].source_key
    if isinstance(key, Method):
        patched = dict(VALIDATION)
        patched[key] = ValidationStatus.VALIDATED
        monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)
    else:
        patched = dict(CAPABILITY_VALIDATION)
        patched[key] = ValidationStatus.VALIDATED
        monkeypatch.setattr(
            "be_stats.dossier.capabilities.CAPABILITY_VALIDATION", patched
        )
    assert CAPABILITY_MATRIX[capability_id].validation_status is ValidationStatus.VALIDATED


def _clear_blockers_and_findings(monkeypatch) -> None:
    """Remove the conditions unrelated to authority, so only it can fail."""
    monkeypatch.setattr(release_gate_module, "blockers_for", lambda _cid: [])
    monkeypatch.setattr(release_gate_module, "findings_for", lambda _cid: [])


def _set_manifest(monkeypatch, records) -> None:
    monkeypatch.setattr("be_stats.dossier.evidence.EVIDENCE_MANIFEST", tuple(records))


def _synthetic(
    capability_id: str,
    *,
    authority: Authority | None,
    source_type: SourceType = SourceType.REGULATOR_PUBLISHED_NUMBERS,
    status: EvidenceStatus = EvidenceStatus.PASSED,
    evidence_id: str = "TEST-SYNTHETIC-TIER-1B",
) -> EvidenceRecord:
    """A tier-1B record that exists only inside a test. Never in the manifest."""
    return EvidenceRecord(
        evidence_id=evidence_id,
        capabilities=(capability_id,),
        tier=EvidenceTier.TIER_1B,
        source_type=source_type,
        source_authority="test fixture",
        evidence_authority=authority,
        scenario="Synthetic, for an authority-condition test only.",
        dataset="-",
        software_environment="-",
        expected="-",
        observed="-",
        tolerance="-",
        status=status,
        established_by="tests/validation/test_dossier_tier_1b_authority.py",
    )


def _authority_violations(result) -> list[str]:
    return [v for v in result.violations if "tier-1B" in v]


def _patch_citation(monkeypatch, capability_id: str, citation: Citation) -> None:
    patched = dict(CAPABILITY_MATRIX)
    patched[capability_id] = dataclasses.replace(
        CAPABILITY_MATRIX[capability_id], regulatory_source=citation
    )
    monkeypatch.setattr(release_gate_module, "CAPABILITY_MATRIX", patched)


# -------------------------------------------------- the authority model ---


def test_every_jurisdiction_is_an_authority():
    """`Authority` extends `Jurisdiction` by ICH and may never contradict it."""
    for jurisdiction in Jurisdiction:
        assert Authority(jurisdiction.value).value == jurisdiction.value


@pytest.mark.parametrize(
    ("written", "resolved"),
    [
        ("FDA", Authority.FDA),
        ("EMA", Authority.EMA),
        ("ICH", Authority.ICH),
        ("ICH / FDA / EMA", None),
        ("fda", None),
        ("FDA ", None),
        ("be-stats", None),
        ("Licensed SAS, pending", None),
        # The sentence that made substring matching dangerous.
        (
            (
                "EMA - publishing output for a model EMA transcribes and "
                "attributes to FDA by name. NOT FDA."
            ),
            None,
        ),
    ],
)
def test_authority_of_is_an_exact_lookup(written, resolved):
    citation = Citation(authority=written, document="d", section="s", document_version="2026")
    assert authority_of(citation) is resolved


def test_every_capability_resolves_its_governing_authority_from_its_citation():
    """Exhaustive over the matrix, and fail-closed: none may be unresolvable today."""
    for capability_id, record in CAPABILITY_MATRIX.items():
        assert record.governing_authority is authority_of(record.regulatory_source)
        assert record.governing_authority is not None, (
            f"{capability_id}'s citation names {record.regulatory_source.authority!r}, "
            "which is no canonical authority. No tier-1B evidence could qualify it."
        )


def test_governing_authority_agrees_with_the_declared_jurisdiction():
    """Two fields about one fact; they may not disagree."""
    for capability_id, record in CAPABILITY_MATRIX.items():
        if record.jurisdiction is not None:
            assert record.governing_authority.value == record.jurisdiction.value, capability_id


def test_average_be_2x2_is_governed_by_ich_which_no_name_prefix_could_say():
    record = CAPABILITY_MATRIX["AVERAGE_BE_2X2"]
    assert record.jurisdiction is None
    assert record.governing_authority is Authority.ICH


def test_governing_authority_reads_nothing_but_the_citation():
    """Structural: the property body touches `regulatory_source` and no other field.

    The mutation this stops is a prefix rule - `FDA` if the id starts with
    "FDA" - which gets every current row right and ICH wrong.
    """
    source = textwrap.dedent(inspect.getsource(CapabilityRecord.governing_authority.fget))
    attributes = {
        node.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Attribute)
    }
    assert "regulatory_source" in attributes
    for forbidden in ("capability_id", "jurisdiction", "title", "note", "method", "source_key"):
        assert forbidden not in attributes, forbidden


def test_the_release_gate_never_compares_free_text_authority():
    """The gate may not read `source_authority`, nor test any string's prefix.

    `source_authority` is for people. A gate that reads it can only compare it
    by substring, and the Appendix C record's text contains "FDA".
    """
    tree = ast.parse(inspect.getsource(release_gate_module))
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "source_authority" not in attributes
    assert "startswith" not in attributes
    assert "endswith" not in attributes
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, ast.Attribute):
                    assert "authority" not in right.attr, ast.unparse(node)


# ------------------------------------------------- the manifest migration ---


#: Every record in the manifest and the canonical authority it carries.
#: Pinned in full so a record added, dropped or re-attributed fails here.
EXPECTED_AUTHORITY: dict[str, Authority | None] = {
    "FDA-HVD-SWITCH-001": Authority.FDA,
    "FDA-HVD-SWR-FORMULA-001": Authority.FDA,
    "FDA-HVD-RSABE-CRITERION-001": Authority.FDA,
    "FDA-NTI-CRITERIA-001": Authority.FDA,
    "FDA-NTI-APPLICABILITY-001": Authority.FDA,
    "FDA-HVD-TREATMENT-CONTRAST": Authority.FDA,
    "EMA-ABEL-PE-CONSTRAINT": Authority.EMA,
    "EMA-HVD-ENDPOINT-DECISION": Authority.EMA,
    "EMA-NTI-NARROWED-INTERVAL": Authority.EMA,
    "EMA-ABEL-WIDENING-BASIS-001": Authority.EMA,
    "EMA-NTI-APPLICABILITY-001": Authority.EMA,
    "EMA-NTI-CMAX-IMPORTANCE-001": Authority.EMA,
    "EMA-PKWP-METHOD-A-DATASET-I": Authority.EMA,
    "EMA-PKWP-METHOD-A-DATASET-II": Authority.EMA,
    "EMA-PKWP-CVWR": Authority.EMA,
    "EMA-ABEL-LIMITS-TABLE": Authority.EMA,
    APPENDIX_C: Authority.EMA,
    "TIER-2-PUBLISHED-REFERENCE": None,
    "POWERTOST-CROSS-CHECK": None,
    "REPLICATEBE-APPENDIX-C-CASES": None,
    "APPENDIX-C-SYNTHETIC-STRUCTURE": None,
    "REFERENCE-VARIANCE-SIMULATION": None,
    SAS_PENDING: None,
}


def test_evidence_authority_is_required_with_no_default():
    (field,) = [f for f in dataclasses.fields(EvidenceRecord) if f.name == "evidence_authority"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING


def test_every_manifest_record_is_migrated_and_none_is_omitted():
    ids = [r.evidence_id for r in EVIDENCE_MANIFEST]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(EXPECTED_AUTHORITY), sorted(set(ids) ^ set(EXPECTED_AUTHORITY))
    for record in EVIDENCE_MANIFEST:
        assert record.evidence_authority is EXPECTED_AUTHORITY[record.evidence_id], (
            record.evidence_id
        )


def test_every_tier_1b_record_is_labelled_regulator_published_numbers():
    for record in EVIDENCE_MANIFEST:
        if record.tier is EvidenceTier.TIER_1B:
            assert record.source_type is SourceType.REGULATOR_PUBLISHED_NUMBERS, (
                record.evidence_id
            )


def test_regulator_sourced_records_name_a_canonical_authority():
    """With one named, pending exception - which must stay pending to stay excused.

    The partial-replicate SAS record is typed REGULATOR_PUBLISHED_NUMBERS and
    has no regulator: a licensed SAS session is not FDA publishing numbers.
    That typing predates this change and belongs to the SAS closure review.
    `None` means it can qualify nothing, and if it ever leaves PENDING with
    `None` still in place, this test fails and forces the decision.
    """
    regulator_sourced = (SourceType.REGULATORY_ALGORITHM, SourceType.REGULATOR_PUBLISHED_NUMBERS)
    for record in EVIDENCE_MANIFEST:
        if record.source_type not in regulator_sourced:
            continue
        if record.evidence_id == SAS_PENDING:
            assert record.status is EvidenceStatus.PENDING
            assert record.evidence_authority is None
            continue
        assert record.evidence_authority is not None, record.evidence_id


def test_non_regulator_records_carry_no_authority():
    for record in EVIDENCE_MANIFEST:
        if record.source_type in (
            SourceType.INDEPENDENT_IMPLEMENTATION,
            SourceType.INTERNAL_STRUCTURAL,
            SourceType.PUBLISHED_REFERENCE,
        ):
            assert record.evidence_authority is None, record.evidence_id


def test_the_appendix_c_evidence_is_kept_on_all_three_fda_capabilities():
    """Hardening the gate by detaching the evidence would be the wrong fix."""
    (record,) = [r for r in EVIDENCE_MANIFEST if r.evidence_id == APPENDIX_C]
    assert record.capabilities == FDA_APPENDIX_C_CAPABILITIES
    assert record.tier is EvidenceTier.TIER_1B
    assert record.source_type is SourceType.REGULATOR_PUBLISHED_NUMBERS
    assert record.status is EvidenceStatus.PASSED
    assert record.evidence_authority is Authority.EMA
    for capability_id in FDA_APPENDIX_C_CAPABILITIES:
        assert record in evidence_for(capability_id)


def test_tier_describes_the_source_not_what_it_is_attached_to():
    """EMA's numbers stay tier 1B beside an FDA capability; they just do not qualify it."""
    for capability_id in FDA_APPENDIX_C_CAPABILITIES:
        assert best_tier_for(capability_id) is EvidenceTier.TIER_1B
        (assessment,) = assess_tier_1b(capability_id)
        assert assessment.relation is Tier1BRelation.SUPPORTING_CROSS_AUTHORITY


# ----------------------------------------------- the qualification table ---


#: Every (tier-1B record, capability) pair in the manifest, and its relation.
EXPECTED_RELATIONS: dict[tuple[str, str], Tier1BRelation] = {
    ("EMA-PKWP-METHOD-A-DATASET-I", "EMA_REPLICATE_METHOD_A"): Tier1BRelation.QUALIFYING,
    ("EMA-PKWP-METHOD-A-DATASET-II", "EMA_REPLICATE_METHOD_A"): Tier1BRelation.QUALIFYING,
    ("EMA-PKWP-CVWR", "EMA_HVD_REFERENCE_VARIABILITY"): Tier1BRelation.QUALIFYING,
    ("EMA-ABEL-LIMITS-TABLE", "EMA_ABEL_LIMIT_CALCULATION"): Tier1BRelation.QUALIFYING,
    (APPENDIX_C, "FDA_REPLICATE_STANDARD_ABE_FULL"): Tier1BRelation.SUPPORTING_CROSS_AUTHORITY,
    (APPENDIX_C, "FDA_HVD_UNSCALED_BRANCH"): Tier1BRelation.SUPPORTING_CROSS_AUTHORITY,
    (APPENDIX_C, "FDA_NTI_UNSCALED_ABE"): Tier1BRelation.SUPPORTING_CROSS_AUTHORITY,
    (SAS_PENDING, "FDA_REPLICATE_STANDARD_ABE_PARTIAL"): (
        Tier1BRelation.NOT_QUALIFYING_NOT_ESTABLISHED
    ),
}


def test_the_current_tier_1b_relations_are_exactly_these():
    observed = {
        (a.evidence_id, a.capability_id): a.relation
        for capability_id in CAPABILITY_MATRIX
        for a in assess_tier_1b(capability_id)
    }
    assert observed == EXPECTED_RELATIONS


def test_no_tier_1b_attachment_is_silently_omitted_from_assessment():
    pairs = {
        (r.evidence_id, c)
        for r in EVIDENCE_MANIFEST
        if r.tier is EvidenceTier.TIER_1B
        for c in r.capabilities
    }
    assessed = {
        (a.evidence_id, a.capability_id)
        for capability_id in CAPABILITY_MATRIX
        for a in assess_tier_1b(capability_id)
    }
    assert pairs == assessed


def test_no_fda_capability_holds_qualifying_tier_1b_evidence():
    for capability_id, record in CAPABILITY_MATRIX.items():
        if record.governing_authority is Authority.FDA:
            assert not any(a.qualifies for a in assess_tier_1b(capability_id)), capability_id


# ------------------------------------ FDA capabilities on EMA's numbers ---


@pytest.mark.parametrize("capability_id", FDA_APPENDIX_C_CAPABILITIES)
def test_an_fda_capability_cannot_be_validated_on_ema_appendix_c_numbers(
    monkeypatch, capability_id
):
    """The actual failure mode, with every OTHER condition satisfied."""
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    assert not result.passed
    assert len(result.violations) == 1, result.violations
    (violation,) = result.violations
    assert f"capability {capability_id} is governed by FDA." in violation
    assert "Tier 1B evidence exists, but none is from the governing authority FDA." in violation
    assert "no qualifying FDA tier-1B regulator-published numerical evidence" in violation
    assert APPENDIX_C in violation
    # Evidence EXISTS; it is non-qualifying. The two must not read the same.
    assert "without tier-1B evidence." not in violation
    assert result.supporting_evidence == (APPENDIX_C,)


@pytest.mark.parametrize("capability_id", FDA_APPENDIX_C_CAPABILITIES)
def test_the_real_blockers_are_no_longer_the_only_thing_in_the_way(monkeypatch, capability_id):
    """Leave today's blockers and findings in place: the authority failure is still there.

    Closing FDA-TIER-1B-WORKED-EXAMPLE or the partial-replicate blocker for
    some unrelated reason must not open a path to VALIDATED on EMA's numbers.
    """
    _claim_validated(monkeypatch, capability_id)
    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))
    assert not result.passed
    assert len(_authority_violations(result)) == 1


def test_forcing_fda_nti_unscaled_abe_to_validated_fails_the_whole_gate(monkeypatch):
    _claim_validated(monkeypatch, "FDA_NTI_UNSCALED_ABE")
    _clear_blockers_and_findings(monkeypatch)

    report = check_release_gate(
        reviewed_transitions=REVIEWED_TRANSITIONS | {"FDA_NTI_UNSCALED_ABE"}
    )

    assert not report.passed
    assert [f.capability_id for f in report.failures] == ["FDA_NTI_UNSCALED_ABE"]
    assert "none is from the governing authority FDA" in "\n".join(report.to_lines())


def test_forcing_fda_replicate_full_to_validated_on_ema_evidence_fails(monkeypatch):
    _claim_validated(monkeypatch, "FDA_REPLICATE_STANDARD_ABE_FULL")
    _clear_blockers_and_findings(monkeypatch)
    report = check_release_gate(
        reviewed_transitions=REVIEWED_TRANSITIONS | {"FDA_REPLICATE_STANDARD_ABE_FULL"}
    )
    assert [f.capability_id for f in report.failures] == ["FDA_REPLICATE_STANDARD_ABE_FULL"]


# --------------------------------------------- legitimate EMA promotions ---


@pytest.mark.parametrize("capability_id", EMA_VALIDATED)
def test_the_ema_validated_capabilities_still_pass_on_their_own_evidence(capability_id):
    """Positive control. No patching: the real matrix, manifest, blockers and transitions."""
    assert CAPABILITY_MATRIX[capability_id].validation_status is ValidationStatus.VALIDATED
    result = check_capability(capability_id, reviewed_transitions=REVIEWED_TRANSITIONS)
    assert result.passed, result.violations
    assert result.supporting_evidence == ()
    assessments = assess_tier_1b(capability_id)
    assert assessments and all(a.qualifies for a in assessments)
    assert any(s.startswith("governed by EMA; qualifying EMA tier-1B") for s in result.satisfied)


@pytest.mark.parametrize("capability_id", EMA_VALIDATED)
def test_the_same_ema_evidence_reattributed_to_fda_no_longer_qualifies(monkeypatch, capability_id):
    """FDA numbers do not qualify an EMA capability either. Only the authority changes."""
    records = [
        dataclasses.replace(r, evidence_authority=Authority.FDA)
        if capability_id in r.capabilities and r.tier is EvidenceTier.TIER_1B
        else r
        for r in EVIDENCE_MANIFEST
    ]
    _set_manifest(monkeypatch, records)

    result = check_capability(capability_id, reviewed_transitions=REVIEWED_TRANSITIONS)

    assert not result.passed
    (violation,) = result.violations
    assert f"capability {capability_id} is governed by EMA." in violation
    assert "none is from the governing authority EMA" in violation


def test_the_gate_passes_on_the_real_matrix():
    assert check_release_gate().passed


# ---------------------------------------------------- mixed authorities ---


def test_mixed_evidence_counts_only_the_governing_authority(monkeypatch):
    """FDA capability, EMA Appendix C record AND a (synthetic) FDA record."""
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=Authority.FDA)))

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    assert result.passed, result.violations
    assert result.supporting_evidence == (APPENDIX_C,)
    (qualifying,) = [s for s in result.satisfied if s.startswith("governed by FDA")]
    assert qualifying.endswith("TEST-SYNTHETIC-TIER-1B")
    assert APPENDIX_C not in qualifying


def test_mixed_evidence_on_an_ema_capability_ignores_the_fda_record(monkeypatch):
    capability_id = "EMA_REPLICATE_METHOD_A"
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=Authority.FDA)))

    result = check_capability(capability_id, reviewed_transitions=REVIEWED_TRANSITIONS)

    assert result.passed, result.violations
    assert result.supporting_evidence == ("TEST-SYNTHETIC-TIER-1B",)
    relations = {a.evidence_id: a.relation for a in assess_tier_1b(capability_id)}
    assert relations == {
        "EMA-PKWP-METHOD-A-DATASET-I": Tier1BRelation.QUALIFYING,
        "EMA-PKWP-METHOD-A-DATASET-II": Tier1BRelation.QUALIFYING,
        "TEST-SYNTHETIC-TIER-1B": Tier1BRelation.SUPPORTING_CROSS_AUTHORITY,
    }


def test_a_pending_record_from_the_governing_authority_is_not_called_cross_authority(monkeypatch):
    """The message may say "none is from FDA" only when that is true."""
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    pending = _synthetic(capability_id, authority=Authority.FDA, status=EvidenceStatus.PENDING)
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, pending))

    (violation,) = check_capability(
        capability_id, reviewed_transitions=frozenset({capability_id})
    ).violations

    assert "none is from the governing authority" not in violation
    assert "a skipped or pending comparison is not a pass" in violation
    assert "no qualifying FDA tier-1B" in violation


# --------------------------------------------------- the other conditions ---


@pytest.mark.parametrize(
    "source_type",
    [
        SourceType.INTERNAL_STRUCTURAL,
        SourceType.INDEPENDENT_IMPLEMENTATION,
        SourceType.PUBLISHED_REFERENCE,
        SourceType.REGULATORY_ALGORITHM,
    ],
)
def test_a_tier_1b_label_on_the_wrong_source_type_does_not_qualify(monkeypatch, source_type):
    """Governing authority right, status right, tier label right - source type wrong."""
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    wrong = _synthetic(capability_id, authority=Authority.FDA, source_type=source_type)
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, wrong))

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    assert not result.passed
    assert "the tier label alone qualifies nothing" in result.violations[0]
    relations = {a.evidence_id: a.relation for a in assess_tier_1b(capability_id)}
    assert relations["TEST-SYNTHETIC-TIER-1B"] is Tier1BRelation.NOT_QUALIFYING_SOURCE_TYPE


@pytest.mark.parametrize(
    "status",
    [
        EvidenceStatus.PENDING,
        EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE,
        EvidenceStatus.NOT_AVAILABLE,
    ],
)
def test_governing_authority_evidence_that_did_not_run_does_not_qualify(monkeypatch, status):
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _set_manifest(
        monkeypatch,
        (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=Authority.FDA, status=status)),
    )
    assert not check_capability(capability_id, reviewed_transitions=frozenset({capability_id})).passed


def test_passed_with_finding_from_the_governing_authority_does_qualify(monkeypatch):
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    record = _synthetic(
        capability_id, authority=Authority.FDA, status=EvidenceStatus.PASSED_WITH_FINDING
    )
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, record))
    assert check_capability(capability_id, reviewed_transitions=frozenset({capability_id})).passed


def test_evidence_with_no_canonical_authority_fails_closed(monkeypatch):
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=None)))

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    assert not result.passed
    relations = {a.evidence_id: a.relation for a in assess_tier_1b(capability_id)}
    assert relations["TEST-SYNTHETIC-TIER-1B"] is Tier1BRelation.NOT_QUALIFYING_AUTHORITY_UNKNOWN
    assert "an authority that cannot be compared qualifies nothing" in result.violations[0]


def test_a_capability_with_no_resolvable_governing_authority_fails_closed(monkeypatch):
    """Even FDA's own numbers cannot qualify a capability whose citation names three bodies."""
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _patch_citation(
        monkeypatch,
        capability_id,
        Citation(authority="ICH / FDA / EMA", document="d", section="s", document_version="2026"),
    )
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=Authority.FDA)))

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    (violation,) = _authority_violations(result)
    assert f"capability {capability_id} names no canonical governing authority" in violation


def test_the_governing_authority_follows_the_citation_not_the_capability_name(monkeypatch):
    """Re-cite an FDA-named capability to an EMA document: EMA's numbers now qualify it.

    Not a proposal - the capability is FDA's. It is the proof that no rule
    keyed on the "FDA_" prefix is doing the work.
    """
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _patch_citation(monkeypatch, capability_id, EMA_BIOEQUIVALENCE_HVD)

    result = check_capability(capability_id, reviewed_transitions=frozenset({capability_id}))

    assert result.passed, result.violations
    assert result.supporting_evidence == ()


# ---------------------------------------------------------- certification ---


def test_certification_fails_on_a_promotion_resting_on_another_regulators_numbers(monkeypatch):
    _claim_validated(monkeypatch, "FDA_NTI_UNSCALED_ABE")
    _clear_blockers_and_findings(monkeypatch)

    lines = [
        p for p in certification_blockers()
        if p.startswith("FDA_NTI_UNSCALED_ABE: release gate failure")
    ]

    assert len(lines) == 1
    assert "none is from the governing authority FDA" in lines[0]
    assert APPENDIX_C in lines[0]


def test_certification_drops_the_authority_complaint_once_governing_evidence_exists(monkeypatch):
    """The control: same promotion, plus FDA numbers. Only the review condition is left."""
    capability_id = "FDA_NTI_UNSCALED_ABE"
    _claim_validated(monkeypatch, capability_id)
    _clear_blockers_and_findings(monkeypatch)
    _set_manifest(monkeypatch, (*EVIDENCE_MANIFEST, _synthetic(capability_id, authority=Authority.FDA)))

    (line,) = [
        p for p in certification_blockers()
        if p.startswith(f"{capability_id}: release gate failure")
    ]

    assert "governing authority" not in line
    assert "reviewed status transition" in line


def test_certification_raises_nothing_against_the_ema_validated_capabilities():
    for problem in certification_blockers():
        for capability_id in EMA_VALIDATED:
            assert not problem.startswith(f"{capability_id}:"), problem


# ------------------------------------------------- nothing moved, nothing added ---


def test_reviewed_transitions_are_exactly_the_three_ema_capabilities():
    assert REVIEWED_TRANSITIONS == frozenset(EMA_VALIDATED)


def test_no_status_changed():
    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert VALIDATION[Method.FDA_HVD_RSABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    assert VALIDATION[Method.STANDARD_ABE] is ValidationStatus.IMPLEMENTED_UNVALIDATED
    expected = {
        "FDA_NTI_UNSCALED_ABE": ValidationStatus.IMPLEMENTED_UNVALIDATED,
        "FDA_REPLICATE_STANDARD_ABE_FULL": ValidationStatus.IMPLEMENTED_UNVALIDATED,
        "FDA_HVD_UNSCALED_BRANCH": ValidationStatus.IMPLEMENTED_UNVALIDATED,
        "FDA_REPLICATE_STANDARD_ABE_PARTIAL": ValidationStatus.NOT_IMPLEMENTED,
        "EMA_HVD_REFERENCE_VARIABILITY": ValidationStatus.VALIDATED,
        "EMA_REPLICATE_METHOD_A": ValidationStatus.VALIDATED,
        "EMA_ABEL_LIMIT_CALCULATION": ValidationStatus.VALIDATED,
    }
    for capability_id, status in expected.items():
        assert CAPABILITY_MATRIX[capability_id].validation_status is status, capability_id


def test_no_fda_or_ich_governed_capability_is_validated():
    for capability_id, record in CAPABILITY_MATRIX.items():
        if record.governing_authority is not Authority.EMA:
            assert record.validation_status is not ValidationStatus.VALIDATED, capability_id


def test_the_partial_sas_oracle_stays_parked():
    assert PARTIAL_ORACLE_READY is False
    assert REAL_SAS_ORACLE_STATUS == "PENDING"
    (record,) = [r for r in EVIDENCE_MANIFEST if r.evidence_id == SAS_PENDING]
    assert record.status is EvidenceStatus.PENDING


def test_fda_nti_tier_1b_remains_unavailable():
    """PR #83's conclusion, unchanged by the gate now asking for FDA's numbers."""
    assert not adopted_sources(search=FDA_NTI_TIER_1B_SEARCH)
    fda_nti = {
        cid for cid, rec in CAPABILITY_MATRIX.items()
        if rec.method is Method.FDA_NTI_RSABE
    }
    assert fda_nti, "no FDA NTI capability found - this check would be vacuous"
    for record in EVIDENCE_MANIFEST:
        if record.tier is EvidenceTier.TIER_1B and fda_nti & set(record.capabilities):
            assert record.evidence_authority is not Authority.FDA, record.evidence_id


def test_the_dossier_explains_fda_nti_unscaled_abe_as_supporting_evidence():
    from be_stats.dossier.render import render_dossier

    document = render_dossier()
    assert "## Tier 1B qualification by capability" in document
    row = [
        line for line in document.splitlines()
        if line.startswith("| `FDA_NTI_UNSCALED_ABE` |") and APPENDIX_C in line
    ]
    assert len(row) == 1
    assert "supporting_cross_authority" in row[0]
    assert "published by EMA, not FDA" in row[0]
