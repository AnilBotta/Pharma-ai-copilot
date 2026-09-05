"""The report may rearrange the dossier. It may not soften it.

WHAT A REPORT CAN GET WRONG THAT A DATA STRUCTURE CANNOT

A capability matrix is read by code, so a wrong status breaks something. A
report is read by a person, so a wrong status is believed. Everything here
guards the gap between what the engine records and what a customer, auditor or
regulatory reviewer takes away from a document with our name on it.

THE RULE EVERYTHING BELOW ENFORCES

Tier 1A is conformance to the regulator's stated algorithm. Tier 1B is
reproduction of a regulator's own published numerical output. Tier 1B is the
numerical evidence a VALIDATED promotion requires, and neither tier alone
establishes VALIDATED status or submission suitability - the release gate
weighs several further conditions.

The failures being prevented, concretely:

  - an IMPLEMENTED_UNVALIDATED method rendering as validated, or as fit to
    file on
  - a NOT_IMPLEMENTED capability rendering as a pass or a fail
  - tier 1A rendering as tier 1B, or tier 3 rendering as regulatory authority
  - a skipped or pending comparison rendering as passed
  - the candidate partial-replicate degrees of freedom reaching a customer
  - the report growing its own copy of a status that can then drift

The wording guard added in PR #74 caught the first draft of this docstring,
which connected tier 1B to submission-readiness without stating the rule
above. It was right to.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from be_stats.dossier.blockers import PARTIAL_ORACLE_READY, REAL_SAS_ORACLE_STATUS
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.constants import provenance_coverage
from be_stats.dossier.evidence import EvidenceStatus
from be_stats.dossier.report import (
    REPORT_SCHEMA,
    Audience,
    ValidationReport,
    build_validation_report,
)
from be_stats.dossier.report_render import (
    render_report_html,
    render_report_markdown,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import ValidationStatus

#: The candidate partial-replicate denominator df live in this range. Any
#: decimal inside it, in a customer-facing artefact, is a leak.
CANDIDATE_RANGE = (19.0, 23.0)


#: A fixed clock. An ISO timestamp ends in `seconds.microseconds`, so a real
#: one eventually lands inside the candidate range these tests scan for - and
#: a leak test that fails four seconds in every minute is a test people learn
#: to re-run rather than read. The first version of this file had exactly that
#: bug and it surfaced as `21.194755`, which is a timestamp, not a df.
FIXED_CLOCK = "2026-01-01T00:00:00+00:00"


@pytest.fixture(scope="module")
def reviewer() -> ValidationReport:
    return build_validation_report(
        audience=Audience.REVIEWER, git_sha="test", generated_at=FIXED_CLOCK
    )


@pytest.fixture(scope="module")
def internal() -> ValidationReport:
    return build_validation_report(
        audience=Audience.INTERNAL, git_sha="test", generated_at=FIXED_CLOCK
    )


def _decimals_in_range(text: str) -> list[str]:
    return sorted(
        {
            n
            for n in re.findall(r"\d+\.\d+", text)
            if CANDIDATE_RANGE[0] <= float(n) <= CANDIDATE_RANGE[1]
        }
    )


# --------------------------------------------- A. canonical consistency ---


def test_every_capability_appears_in_the_report(reviewer):
    ids = {section.capability_id for section in reviewer.capabilities}
    assert ids == set(CAPABILITY_MATRIX), (
        "The report must cover the whole matrix. Omitting components would "
        "hide the limitations that explain the methods' statuses."
    )


def test_report_statuses_follow_the_canonical_matrix(reviewer):
    for section in reviewer.capabilities:
        record = CAPABILITY_MATRIX[section.capability_id]
        assert section.validation_status == str(record.validation_status)
        assert section.implementation_status == str(record.implementation_status)
        assert section.decision_supported is record.decision_supported


def test_the_report_follows_a_mutated_status(monkeypatch):
    """Proof there is no stored copy that could drift.

    Mutating the spec table must move the report. If a section ever stored its
    own status string, this is the test that catches it - the same guard the
    capability matrix carries, one layer further out.
    """
    from be_stats.spec import VALIDATION, Method

    patched = dict(VALIDATION)
    patched[Method.FDA_HVD_RSABE] = ValidationStatus.EXPERIMENTAL
    monkeypatch.setattr("be_stats.dossier.capabilities.VALIDATION", patched)

    report = build_validation_report(audience=Audience.REVIEWER, git_sha="test")
    section = next(
        s for s in report.capabilities if s.capability_id == "FDA_HVD_RSABE"
    )
    assert section.validation_status == "experimental"


def test_the_two_audiences_never_disagree_about_a_status(reviewer, internal):
    """Audience changes what is INCLUDED, never what is TRUE."""
    by_id = {s.capability_id: s for s in internal.capabilities}
    for section in reviewer.capabilities:
        other = by_id[section.capability_id]
        assert section.validation_status == other.validation_status
        assert section.implementation_status == other.implementation_status
        assert section.display_status == other.display_status
        assert section.established_evidence_tier == other.established_evidence_tier
        assert section.submission_ready == other.submission_ready


def test_the_report_declares_its_schema(reviewer):
    assert reviewer.identity.schema == REPORT_SCHEMA
    assert reviewer.to_dict()["schema"] == REPORT_SCHEMA


def test_json_is_byte_identical_when_the_clock_is_held_still():
    """Determinism, asserted without carving an exception into the comparison.

    Injecting the timestamp is better than popping it afterwards: a test that
    deletes the one field known to vary cannot notice a SECOND field starting
    to vary.
    """
    first = build_validation_report(
        audience=Audience.REVIEWER, git_sha="x", generated_at=FIXED_CLOCK
    ).to_dict()
    second = build_validation_report(
        audience=Audience.REVIEWER, git_sha="x", generated_at=FIXED_CLOCK
    ).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_an_unpinned_clock_still_differs_only_in_the_timestamp():
    """And the real path is still deterministic apart from the clock."""
    first = build_validation_report(audience=Audience.REVIEWER, git_sha="x").to_dict()
    second = build_validation_report(audience=Audience.REVIEWER, git_sha="x").to_dict()
    for payload in (first, second):
        payload["identity"] = dict(payload["identity"])
        payload["identity"].pop("generated_at")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_generated_metadata_is_separated_from_evidence(reviewer):
    """A timestamp beside a citation invites a reader to weigh them alike."""
    assert "generated" in reviewer.identity.note.lower()
    assert "not the regulatory evidence" in reviewer.identity.note
    payload = reviewer.to_dict()
    assert "git_sha" in payload["identity"]
    for section in payload["capabilities"]:
        assert "git_sha" not in section
        assert "generated_at" not in section


# ------------------------------------------------- B. evidence semantics ---


def test_tier_1a_never_renders_as_tier_1b(reviewer):
    from be_stats.dossier.evidence import EVIDENCE

    for section in reviewer.capabilities:
        for row in section.evidence:
            assert row["tier"] == str(EVIDENCE[row["evidence_id"]].tier)


def test_every_tier_carries_its_meaning_and_they_are_distinct(reviewer):
    """A tier label with no gloss lets a reader supply their own."""
    meanings = {}
    for section in reviewer.capabilities:
        for row in section.evidence:
            assert row["tier_meaning"].strip()
            meanings.setdefault(row["tier"], set()).add(row["tier_meaning"])
    for tier, seen in meanings.items():
        assert len(seen) == 1, f"{tier} is glossed inconsistently: {seen}"
    assert len(meanings) >= 3


def test_tier_3_is_never_presented_as_regulatory_authority(reviewer):
    rows = [
        row
        for section in reviewer.capabilities
        for row in section.evidence
        if row["tier"] == str(EvidenceTier.TIER_3)
    ]
    assert rows, "No tier-3 rows; this guard would pass vacuously."
    for row in rows:
        assert "not regulatory authority" in row["tier_meaning"]

    notes = reviewer.reading_notes["independent_implementations"]
    assert "not regulatory authority" in notes
    assert "PowerTOST" in notes


def test_skipped_and_pending_never_render_as_passed(reviewer):
    from be_stats.dossier.evidence import EVIDENCE

    withheld = {
        EvidenceStatus.SKIPPED_ENVIRONMENT_UNAVAILABLE,
        EvidenceStatus.PENDING,
        EvidenceStatus.NOT_AVAILABLE,
    }
    seen = 0
    for section in reviewer.capabilities:
        for row in section.evidence:
            record = EVIDENCE[row["evidence_id"]]
            assert row["status"] == str(record.status)
            if record.status in withheld:
                seen += 1
                assert "passed" not in row["status"]
    assert seen, "No withheld evidence rows; this guard would pass vacuously."


def test_an_unestablished_tier_never_raises_a_capability(reviewer):
    """The partial capability has a PENDING tier-1B record and no evidence."""
    section = next(
        s
        for s in reviewer.capabilities
        if s.capability_id == "FDA_REPLICATE_STANDARD_ABE_PARTIAL"
    )
    assert section.established_evidence_tier == str(EvidenceTier.NONE)


def test_evidence_is_grouped_by_tier_and_never_merged(reviewer):
    grouped = reviewer.to_dict()["evidence_by_tier"]
    for tier in (
        EvidenceTier.TIER_1A,
        EvidenceTier.TIER_1B,
        EvidenceTier.TIER_2,
        EvidenceTier.TIER_3,
        EvidenceTier.TIER_4,
    ):
        assert str(tier) in grouped, f"{tier} has no group; absence is not emptiness."


# ------------------------------------------------- C. submission wording ---


def test_only_validated_capabilities_are_submission_ready(reviewer):
    for section in reviewer.capabilities:
        expected = section.validation_status == str(ValidationStatus.VALIDATED)
        assert section.submission_ready is expected, section.capability_id


def test_unvalidated_capabilities_never_display_as_validated(reviewer):
    for section in reviewer.capabilities:
        if section.validation_status == str(ValidationStatus.VALIDATED):
            continue
        assert section.display_status != "VALIDATED", section.capability_id
        assert not section.submission_ready, section.capability_id


def test_every_capability_states_what_it_does_not_establish(reviewer):
    """Including the validated ones, which is where it matters most."""
    for section in reviewer.capabilities:
        assert section.does_not_establish.strip(), section.capability_id

    validated = [
        s
        for s in reviewer.capabilities
        if s.validation_status == str(ValidationStatus.VALIDATED)
    ]
    assert validated, "No validated capabilities; this guard would be vacuous."
    for section in validated:
        assert "does not" in section.does_not_establish.lower()


def test_not_implemented_renders_as_no_decision_rather_than_a_verdict(reviewer):
    sections = [
        s
        for s in reviewer.capabilities
        if s.validation_status == str(ValidationStatus.NOT_IMPLEMENTED)
    ]
    assert sections
    for section in sections:
        assert section.decision_supported is False
        assert "no regulatory decision" in section.does_not_establish.lower()
        assert section.refusal_conditions, (
            f"{section.capability_id} refuses and names no reason"
        )
        assert section.explainability["refusal"] is not None


def test_the_tier_rule_is_stated_and_does_not_overstate_1b(reviewer):
    rule = reviewer.reading_notes["evidence_tiers"]
    assert "requires" in rule
    assert "neither tier alone" in rule
    assert "release gate" in rule
    assert "licenses a filing" not in rule


def test_the_promotion_policy_forbids_automatic_promotion(reviewer):
    policy = reviewer.governance["promotion_policy"]
    assert "named reviewer" in policy
    assert "never approve" in policy or "may never approve" in policy


# ---------------------------------------------------------- D. provenance ---


def test_provenance_coverage_matches_the_canonical_index(reviewer):
    assert reviewer.provenance["coverage"] == provenance_coverage()


def test_the_pinned_count_is_read_from_the_index_rather_than_written_here(
    reviewer,
):
    """This asserted 19/21 while DOSSIER-004 was open. It now asserts neither.

    Replacing the 19 with a 21 would have rebuilt the same trap one release
    later: a literal in a test is a second place the truth is written down,
    and the two drift. The report's job is to print what the index says, so
    that is what is checked - plus the one relationship that must hold however
    the numbers move.
    """
    coverage = reviewer.provenance["coverage"]

    assert coverage == provenance_coverage()
    assert (
        coverage["normative_pinned"] + coverage["normative_exceptions"]
        == coverage["normative"]
    ), "Pinned plus declared must account for every normative constant."


def test_the_citation_gap_list_mirrors_the_index_whatever_is_in_it(reviewer):
    """Empty today, and empty for a reason the report does not decide.

    The list used to hold the two conventional-interval constants. DOSSIER-004
    closed and it emptied on its own, because it is built from
    `unpinned_normative_constants()` rather than maintained. That is the
    property worth testing: it follows the index in both directions, so a
    future gap appears here without anybody remembering to add it.
    """
    from be_stats.dossier.constants import unpinned_normative_constants

    gaps = reviewer.provenance["unresolved_citation_gaps"]
    expected = {r.constant_id for r in unpinned_normative_constants()}

    assert {gap["constant_id"] for gap in gaps} == expected
    assert len(gaps) == coverage_exceptions(reviewer)
    for gap in gaps:
        assert gap["why"].strip(), "A gap with no reason is a gap absorbed."


def coverage_exceptions(reviewer) -> int:
    return reviewer.provenance["coverage"]["normative_exceptions"]


def test_dossier_004_is_no_longer_an_open_limitation(reviewer):
    """It was open, and the report said so. It is resolved, and must not.

    The reviewer report exposes OPEN findings only, so a resolved finding
    leaves the limitations section entirely - which is correct for a section
    headed by what still limits a claim. Its history stays in the findings
    register and in the generated dossier, not here, and no special case is
    added to keep it visible.
    """
    from be_stats.dossier.findings import FINDINGS, FindingStatus

    assert FINDINGS["DOSSIER-004"].status is FindingStatus.RESOLVED

    open_ids = {f["finding_id"] for f in reviewer.limitations["open_findings"]}
    assert "DOSSIER-004" not in open_ids

    # The findings that ARE open still reach the report, so the absence above
    # is a status change and not a section that stopped being populated.
    assert open_ids, "No open findings reported at all - the section is broken."
    assert {"DOSSIER-001", "DOSSIER-002", "DOSSIER-003"} <= open_ids


def test_current_is_still_not_a_pinned_version(reviewer):
    """The string that started this, kept as a rule rather than as data.

    This used to find a row in the report carrying `document_version =
    "current"` and assert it was unpinned. There is no such row any more, and
    a test that needs the defect present to check the rule stops checking the
    moment the defect is fixed.

    So the rule is asserted directly, and the report is checked for the
    property that matters: nothing it prints as pinned may carry a version
    that identifies no issue of a document.
    """
    from be_stats.dossier.citations import version_is_pinned

    assert not version_is_pinned("current")

    for row in reviewer.provenance["normative"]:
        if row["pinned"]:
            assert version_is_pinned(row["document_version"]), (
                f"{row['constant_id']} is reported as pinned with version "
                f"{row['document_version']!r}, which identifies no issue."
            )
            assert row["section"], row["constant_id"]


def test_derived_constants_show_a_derivation_not_a_regulatory_section(reviewer):
    derived = reviewer.provenance["derived"]
    assert derived
    for row in derived:
        assert row["derivation"], row["constant_id"]
        assert row["derived_from"], row["constant_id"]
        assert "section" not in row, (
            f"{row['constant_id']} carries a regulatory section. No regulator "
            "states a derived value."
        )
        assert row["verification"] == "derived"


# ----------------------------------------------------------------- E. SAS ---


def test_partial_appendix_c_renders_as_not_implemented(reviewer):
    section = next(
        s
        for s in reviewer.capabilities
        if s.capability_id == "FDA_REPLICATE_STANDARD_ABE_PARTIAL"
    )
    assert section.validation_status == str(ValidationStatus.NOT_IMPLEMENTED)
    assert section.display_status == "NOT IMPLEMENTED"
    assert section.decision_supported is False
    assert section.qualification == (
        "Not implemented - external SAS oracle evidence pending."
    )


def test_the_governance_section_reports_the_sas_state(reviewer):
    assert reviewer.governance["partial_oracle_ready"] is PARTIAL_ORACLE_READY
    assert reviewer.governance["partial_oracle_ready"] is False
    assert reviewer.governance["real_sas_oracle_status"] == REAL_SAS_ORACLE_STATUS
    assert reviewer.governance["real_sas_oracle_status"] == "PENDING"


def test_pending_sas_evidence_is_never_reported_as_established(reviewer):
    rows = [
        row
        for row in reviewer.limitations["evidence_not_established"]
        if row["evidence_id"] == "SAS-APPENDIX-C-PARTIAL-REPLICATE"
    ]
    assert rows, "The awaited SAS evidence must be listed as outstanding."
    assert rows[0]["status"] == str(EvidenceStatus.PENDING)


@pytest.mark.parametrize("renderer", [render_report_markdown, render_report_html])
def test_no_candidate_df_reaches_a_customer_facing_export(reviewer, renderer):
    """The leak this audience split exists to prevent.

    Checked as a numeric scan rather than a search for one literal, so a
    candidate expressed to different precision is caught too.
    """
    leaked = _decimals_in_range(renderer(reviewer))
    assert not leaked, (
        f"{renderer.__name__} leaked {leaked}, which lie in the range of the "
        "candidate partial-replicate denominator df. Those are a live "
        "statistical question and stay internal."
    )


def test_the_reviewer_json_carries_no_candidate_values(reviewer):
    leaked = _decimals_in_range(json.dumps(reviewer.to_dict()))
    assert not leaked, leaked


def test_the_internal_audience_still_records_the_candidates(internal):
    """The complement: they are not deleted, only kept inside.

    A reviewer of THIS PACKAGE needs to know what has been considered and
    rejected. Removing the candidates entirely would trade one failure for
    another.
    """
    assert _decimals_in_range(json.dumps(internal.to_dict())), (
        "The internal report no longer records the candidate evidence."
    )
    blockers = internal.limitations["open_blockers"]
    partial = next(
        b for b in blockers if b["blocker_id"] == "APPENDIX-C-PARTIAL-ORACLE"
    )
    assert partial["candidate_evidence"]
    for candidate in partial["candidate_evidence"]:
        assert candidate["insufficient_because"].strip()


def test_the_reviewer_audience_omits_candidate_evidence_entirely(reviewer):
    for blocker in reviewer.limitations["open_blockers"]:
        assert "candidate_evidence" not in blocker


# --------------------------------------------------------- F. limitations ---


def test_outstanding_work_is_listed_rather_than_inferred(reviewer):
    limitations = reviewer.limitations
    assert limitations["open_findings"]
    assert limitations["open_blockers"]
    assert limitations["evidence_not_established"]
    assert limitations["certification_blockers"]
    assert "outstanding work" in limitations["note"]


def test_the_partial_oracle_blocker_is_listed_with_what_would_resolve_it(reviewer):
    blocker = next(
        b
        for b in reviewer.limitations["open_blockers"]
        if b["blocker_id"] == "APPENDIX-C-PARTIAL-ORACLE"
    )
    assert "SAS" in blocker["required_evidence"]
    assert blocker["current_behaviour"]


# ------------------------------------------------------------ renderers ---


@pytest.mark.parametrize("renderer", [render_report_markdown, render_report_html])
def test_renderers_state_every_capability_and_its_status(reviewer, renderer):
    document = renderer(reviewer)
    for section in reviewer.capabilities:
        assert section.capability_id in document
        assert section.display_status in document


def test_the_markdown_summary_row_shows_each_capability_its_own_status(reviewer):
    """Parsed per row, not sampled by character window.

    A first version took a fixed-length window from each capability id, which
    ran into the NEXT row of the summary table and failed on a neighbour that
    is legitimately validated. Banning the word outright fails too: the reading
    notes explain what a promotion requires and must say VALIDATED to do it.

    So the assertion is on the cell: the "shown as" column of this
    capability's own row equals its own display status.
    """
    document = render_report_markdown(reviewer)
    lines = document.splitlines()
    for section in reviewer.capabilities:
        prefix = f"| `{section.capability_id}` |"
        row = next((line for line in lines if line.startswith(prefix)), None)
        assert row is not None, f"{section.capability_id} has no summary row"
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[4] == section.display_status, (
            f"{section.capability_id} is {section.validation_status} and its "
            f"summary row shows {cells[4]!r}"
        )


def test_the_html_card_badge_shows_each_capability_its_own_status(reviewer):
    """The badge is what a reader sees first, so it is what gets asserted."""
    document = render_report_html(reviewer)
    # Only the capability cards carry a status badge. The other <h3>s are
    # section headings - evidence tiers, derived values, open findings - and
    # matching those too made a first version count 32 where 23 were meant.
    cards = [
        heading
        for heading in re.findall(r"<h3>(.*?)</h3>", document, re.DOTALL)
        if 'class="status' in heading
    ]
    assert len(cards) == len(reviewer.capabilities)

    by_id = {s.capability_id: s for s in reviewer.capabilities}
    for heading in cards:
        capability_id = heading.split("&mdash;")[0].strip()
        section = by_id[capability_id]
        badge = re.search(r'<span class="status [^"]+">(.*?)</span>', heading)
        assert badge is not None, capability_id
        assert badge.group(1) == section.display_status, (
            f"{capability_id} is {section.validation_status} and its badge "
            f"reads {badge.group(1)!r}"
        )
        if section.validation_status != str(ValidationStatus.VALIDATED):
            assert badge.group(1) != "VALIDATED"


def test_the_html_is_self_contained(reviewer):
    """A document an auditor opens in two years must not need a network.

    No scripts either: a report that can execute is a report that can change
    after review.
    """
    document = render_report_html(reviewer)
    assert "<script" not in document.lower()
    assert "http://" not in document
    assert "https://" not in document
    assert document.startswith("<!doctype html>")


def test_the_html_escapes_content(reviewer):
    """Report text is data. A stray angle bracket must not become markup."""
    document = render_report_html(reviewer)
    assert "<script>" not in document
    # The prose contains ampersands and quotes; they must arrive escaped.
    assert "&amp;" in document or "&#" in document or "&middot;" in document


def test_the_markdown_states_the_tenancy_scope(reviewer):
    document = render_report_markdown(reviewer)
    assert "single-organisation" in document
    assert "no study, subject, or tenant data" in document


# ------------------------------------------------- G. the schema fixture ---


SCHEMA_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "validation"
    / "validation-report-schema.json"
)


def test_the_committed_schema_fixture_matches_the_report():
    """Regenerate and compare, so the fixture cannot go stale silently.

    The fixture records the report's SHAPE - which sections exist, which
    fields each row carries, what type each field is - with values elided. A
    committed example report would be seventy kilobytes changing on every
    status edit, and a diff nobody reads is a diff nobody reads.

    What a consumer branches on is the shape, and this is what makes changing
    it a build failure rather than a support ticket.
    """
    from be_stats.dossier.report_schema import report_shape

    assert SCHEMA_FIXTURE.exists(), (
        f"{SCHEMA_FIXTURE} is missing. Regenerate it with "
        "`be_stats.dossier.report_schema.report_shape`."
    )
    committed = json.loads(SCHEMA_FIXTURE.read_text(encoding="utf-8"))
    assert committed == report_shape(), (
        "The validation report's shape has changed and the committed fixture "
        "has not. Regenerate it, and consider whether REPORT_SCHEMA needs "
        "bumping - a consumer outside this repository branches on it."
    )


def test_the_fixture_records_types_rather_than_values():
    """A fixture holding real values would change with every status edit."""
    committed = json.loads(SCHEMA_FIXTURE.read_text(encoding="utf-8"))
    leaves: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        else:
            leaves.append(node)

    walk(committed)
    assert leaves
    assert set(leaves) <= {"str", "bool", "int", "float", "null"}, (
        f"The fixture contains values, not types: "
        f"{sorted(set(leaves) - {'str', 'bool', 'int', 'float', 'null'})}"
    )


def test_the_fixture_merges_shapes_across_list_elements():
    """A first-element collapse would miss what a later element carries.

    The first capability in the matrix has no blockers. Recording that list's
    shape from the first element alone gave `[]`, which would not have noticed
    a change to a blocker row's fields.
    """
    committed = json.loads(SCHEMA_FIXTURE.read_text(encoding="utf-8"))
    assert committed["capabilities"][0]["blockers"] == ["str"]
    blocker = committed["limitations"]["open_blockers"][0]
    assert "required_evidence" in blocker
    assert "candidate_evidence" not in blocker, (
        "The reviewer fixture must not carry the internal candidate block."
    )


def test_the_report_contains_no_secret_shaped_values(reviewer):
    """No key, token or connection string can reach an exported document.

    The report is built from code, so this should be structurally impossible -
    which is exactly the kind of belief worth checking once.
    """
    payload = json.dumps(reviewer.to_dict()).lower()
    for marker in (
        "sk-",
        "bearer ",
        "postgres://",
        "postgresql://",
        "supabase_service",
        "service_role",
        "api_key",
        "apikey",
        "password",
        "secret",
    ):
        assert marker not in payload, f"{marker!r} appears in the report payload"
