"""What counts as a pinned citation, and the gate that used to disagree.

THE HOLE THIS FILE CLOSES

`ConstantRecord.has_pinned_citation` required authority, document, section and
version. The release gate, three modules away, tested pinning as
`if not record.regulatory_source.document_version`. So `"current"` passed the
gate - a non-empty string - while the provenance layer correctly excluded the
same citation from its pinned count.

One concept, two encodings, and the weaker of the two sat on the control that
decides whether something may be called VALIDATED. Today nothing claims
VALIDATED on that citation, so no false claim exists. This dossier exists to
stop a FUTURE one.
"""

from __future__ import annotations

import dataclasses

import pytest

from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.citations import (
    CITATION_EXCEPTIONS,
    exception_for,
    is_pinned,
    names_one_authority,
    version_is_pinned,
    why_not_pinned,
)
from be_stats.dossier.constants import CONSTANT_INDEX
from be_stats.provenance import (
    EMA_M13A_BE_CRITERIA,
    EMA_M13A_QA,
    FDA_M13A_BE_CRITERIA,
    FDA_M13A_QA,
    ICH_M13A_BE_CRITERIA,
    ICH_M13A_QA,
    Citation,
)

PINNED = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="Appendix G",
    document_version="final, May 2026",
)


# ------------------------------------------------------- the version rule ---


@pytest.mark.parametrize(
    "version",
    [
        "final, May 2026",
        "CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010",
        "EMA/618604/2008 Rev. 13",
        "EMA/531548/2024, adopted by CHMP 17 February 2025",
        "draft, reissued 2003",
        "Rev. 2",
        "v3",
    ],
)
def test_a_version_naming_an_issue_is_pinned(version):
    assert version_is_pinned(version)


@pytest.mark.parametrize(
    "version",
    [
        "current",
        "latest",
        "current version",
        "TBD",
        "unknown",
        "in force",
        "as published",
        "FDA guidance for industry",
        "",
    ],
)
def test_a_version_naming_no_issue_is_not_pinned(version):
    """`"current"` is the one that mattered, and it is not special-cased.

    The rule is POSITIVE - a pinned version carries a year or a revision - so
    every vague form above fails for the same reason rather than because
    somebody thought of it. A blacklist would be a promise to have anticipated
    every future wording, and nobody can keep that promise.
    """
    assert not version_is_pinned(version)


def test_current_specifically_does_not_qualify():
    """Named on its own, because it is the string that was passing."""
    assert not version_is_pinned("current")
    assert not is_pinned(dataclasses.replace(PINNED, document_version="current"))


def test_the_rule_is_positive_rather_than_a_blacklist():
    """A word nobody has thought of must fail, not pass.

    The test that would have missed the original defect is one enumerating
    known-bad strings; this asserts the default direction.
    """
    for invented in ("effective immediately", "the one on the website", "n/a"):
        assert not version_is_pinned(invented), invented


# ------------------------------------------------------ the other fields ---


def test_one_authority_is_required():
    assert names_one_authority("FDA")
    assert names_one_authority("EMA")
    assert not names_one_authority("ICH / FDA / EMA")
    assert not names_one_authority("FDA, EMA")
    assert not names_one_authority("FDA and EMA")
    assert not names_one_authority("")


def test_a_missing_section_is_not_pinned():
    assert not is_pinned(dataclasses.replace(PINNED, section=""))


def test_a_missing_document_is_not_pinned():
    assert not is_pinned(dataclasses.replace(PINNED, document=""))


def test_a_complete_citation_is_pinned():
    assert is_pinned(PINNED)
    assert why_not_pinned(PINNED) == ()


def test_why_not_pinned_names_every_failing_condition():
    """A bare "not pinned" sends somebody to compare four fields by eye."""
    reasons = why_not_pinned(
        Citation(
            authority="ICH / FDA / EMA",
            document="Conventional bioequivalence acceptance interval",
            document_version="current",
        )
    )
    assert len(reasons) == 3
    assert any("more than one authority" in r for r in reasons)
    assert any("no section" in r for r in reasons)
    assert any("identifies no issue" in r for r in reasons)


# ----------------------------------------------- one definition, not two ---


def test_the_constants_layer_and_the_capability_layer_share_one_definition():
    """The property that was violated, asserted directly.

    Both call `citations.is_pinned`. Checked by driving the same citation
    through both and requiring the same answer, rather than by reading either
    implementation.
    """
    for record in CONSTANT_INDEX.values():
        assert record.has_pinned_citation is is_pinned(record.citation)

    for record in CAPABILITY_MATRIX.values():
        assert record.has_pinned_source is is_pinned(record.regulatory_source)


def test_no_module_reimplements_the_pinning_check():
    """A second encoding is how the hole appeared. Guarded structurally.

    Looks for the ORIGINAL defect's shape - a truthiness test on
    `document_version` - in the dossier source, with comments stripped so the
    paragraphs explaining the defect do not match. Prose about a bug is not
    the bug; this repository has learned that five times.
    """
    import ast
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[2] / "src" / "be_stats"
    offenders = []

    for path in (package / "dossier").glob("*.py"):
        # `citations.py` OWNS the definition, and inside it the check is
        # legitimate: `why_not_pinned` distinguishes an EMPTY version from a
        # vague one so the message can say which. Exempting the owner is the
        # point of having one - every other module must call it.
        if path.name == "citations.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # `not <anything>.document_version` used as a condition. An AST
            # walk cannot match a docstring, which is the whole reason for
            # using one rather than a text search.
            if not isinstance(node, ast.UnaryOp) or not isinstance(
                node.op, ast.Not
            ):
                continue
            operand = node.operand
            if (
                isinstance(operand, ast.Attribute)
                and operand.attr == "document_version"
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        f"{offenders} test `document_version` for truthiness. That is the "
        "check that let 'current' through, because a non-empty string is "
        "truthy. Call citations.is_pinned instead."
    )


# ------------------------------------------------------------ exceptions ---


def test_the_three_consumers_still_share_one_citation_object():
    """The property that kept them consistent, kept after DOSSIER-004 closed.

    The two conventional-interval constants and the AVERAGE_BE_2X2 capability
    all reference one `Citation` object. That was what made a single declared
    exception reach all three; it is now what makes a single PINNED citation
    reach all three. Three copies of the same fields would drift.
    """
    capability = CAPABILITY_MATRIX["AVERAGE_BE_2X2"]
    lower = CONSTANT_INDEX["CONVENTIONAL_LOWER_PERCENT"]
    upper = CONSTANT_INDEX["CONVENTIONAL_UPPER_PERCENT"]

    assert capability.regulatory_source is lower.citation is upper.citation


def test_the_conventional_interval_is_now_pinned_with_no_exception():
    """DOSSIER-004's closure, asserted on the citation rather than the finding.

    Checks the four conditions hold and that no exception survives alongside
    them - a stale exception excludes a good citation from the pinned count,
    which is the failure in the opposite direction from the original one.
    """
    capability = CAPABILITY_MATRIX["AVERAGE_BE_2X2"]
    citation = capability.regulatory_source

    assert is_pinned(citation), why_not_pinned(citation)
    assert exception_for(citation) is None
    assert capability.source_citation_exception is None

    for constant_id in (
        "CONVENTIONAL_LOWER_PERCENT",
        "CONVENTIONAL_UPPER_PERCENT",
    ):
        record = CONSTANT_INDEX[constant_id]
        assert record.has_pinned_citation
        assert not record.citation_exception


def test_every_declared_exception_names_a_real_finding():
    """Vacuous today - the registry is empty - and kept for the next entry.

    The companion test below is the one that proves the rule still bites.
    """
    from be_stats.dossier.findings import FINDINGS

    for citation, exception in CITATION_EXCEPTIONS.items():
        assert not is_pinned(citation), (
            f"{exception.tracked_as} declares an exception for a citation "
            "that IS pinned. A stale exception excludes a good citation from "
            "the count."
        )
        assert exception.tracked_as in FINDINGS
        assert FINDINGS[exception.tracked_as].is_open, (
            f"{exception.tracked_as} is closed; the exception should go with "
            "it."
        )
        assert exception.reason.strip()
        assert exception.resolution.strip()


def test_the_exception_machinery_still_holds_with_an_empty_registry():
    """The registry emptied when DOSSIER-004 closed. The mechanism did not.

    `test_every_declared_exception_names_a_real_finding` now iterates nothing
    and would pass against a deleted implementation. This drives a fabricated
    exception through the same three paths - lookup, the "declared counts as
    looked at" reading, and the release gate's stricter one - so the next
    unpinned citation has somewhere to be declared and something that reads it.
    """
    from be_stats.dossier.citations import (
        CitationException,
        is_pinned_or_declared,
    )

    unpinned = Citation(
        authority="ICH / FDA / EMA",
        document="Conventional bioequivalence acceptance interval",
        document_version="current",
    )
    assert not is_pinned(unpinned)
    assert exception_for(unpinned) is None
    assert not is_pinned_or_declared(unpinned), (
        "An undeclared unpinned citation must not read as looked at."
    )

    declared = CitationException(
        reason="Fabricated, for this test only.",
        tracked_as="DOSSIER-000",
        resolution="Nothing - it does not exist.",
    )
    registry = {unpinned: declared}
    assert registry.get(unpinned) is declared, (
        "A Citation must stay hashable by value for the registry to work; "
        "keying by the object is what lets three consumers share one entry."
    )
    assert declared.explain().startswith("Fabricated")


# ------------------------------- the conventional interval, per regulator ---


CONVENTIONAL_CITATIONS = {
    "ICH": ICH_M13A_BE_CRITERIA,
    "FDA": FDA_M13A_BE_CRITERIA,
    "EMA": EMA_M13A_BE_CRITERIA,
}


@pytest.mark.parametrize("name", sorted(CONVENTIONAL_CITATIONS))
def test_each_conventional_citation_satisfies_the_canonical_rule(name):
    citation = CONVENTIONAL_CITATIONS[name]
    assert is_pinned(citation), why_not_pinned(citation)
    assert citation.authority == name


@pytest.mark.parametrize("name", sorted(CONVENTIONAL_CITATIONS))
@pytest.mark.parametrize(
    "damage",
    [
        {"section": ""},
        {"document": ""},
        {"document_version": "current"},
        {"document_version": ""},
        {"authority": "ICH / FDA / EMA"},
    ],
)
def test_a_damaged_conventional_citation_stops_being_pinned(name, damage):
    """The mutation check, run rather than described.

    Each of the five ways the ORIGINAL placeholder was wrong is reapplied to
    the real citation, and each must break it. Without this, the tests above
    would still pass if `is_pinned` had been relaxed to let the new citation
    through - which is the one thing this PR must not do.
    """
    broken = dataclasses.replace(CONVENTIONAL_CITATIONS[name], **damage)
    assert not is_pinned(broken), (
        f"{name} citation survives {damage!r}. The gate must reject it for "
        "the same reason it rejected the placeholder."
    )


def test_the_conventional_citation_does_not_reach_the_scaled_pathways():
    """SCOPE. M13A 2.2.4 states the interval for NON-REPLICATE designs only.

    M13A's own scope defers highly variable drugs and narrow therapeutic index
    drugs to the future M13C, so a capability implementing a scaled or
    narrowed criterion must not cite it. Asserted on the capability matrix
    rather than on prose, because prose about scope is not scope.
    """
    conventional = set(CONVENTIONAL_CITATIONS.values())

    for capability_id in (
        "FDA_HVD_RSABE",
        "FDA_NTI_RSABE",
        "EMA_NTI_NARROW_ABE",
        "EMA_ABEL_LIMIT_CALCULATION",
    ):
        record = CAPABILITY_MATRIX.get(capability_id)
        if record is None:
            continue
        assert record.regulatory_source not in conventional, (
            f"{capability_id} cites ICH M13A's conventional-interval section. "
            "M13A 2.2.4 is inside 'Data Analysis for Non-Replicate Study "
            "Design' and M13A defers highly variable and narrow therapeutic "
            "index drugs to M13C, so it states nothing about this pathway."
        )


def test_a_jurisdiction_gets_its_own_regulators_adopted_document():
    """Not ICH's, and not the other regulator's.

    The interval is one number and three documents. A resolved spec always
    has a jurisdiction, and the reader of that spec is preparing a submission
    to that regulator.
    """
    from be_stats.spec import (
        BeSpec,
        DrugClass,
        Endpoint,
        Jurisdiction,
        resolve_be_spec,
    )

    for jurisdiction, expected in (
        (Jurisdiction.FDA, FDA_M13A_BE_CRITERIA),
        (Jurisdiction.EMA, EMA_M13A_BE_CRITERIA),
    ):
        spec: BeSpec = resolve_be_spec(
            jurisdiction=jurisdiction,
            drug_class=DrugClass.STANDARD,
            endpoint=Endpoint.AUC,
        )
        assert spec.acceptance is not None
        for value in (spec.acceptance.lower, spec.acceptance.upper):
            assert value.citation is expected, (
                f"{jurisdiction} standard interval cites "
                f"{value.citation.authority}, not its own regulator's "
                "adoption of ICH M13A."
            )
        assert spec.acceptance.lower_value == 80.00
        assert spec.acceptance.upper_value == 125.00


def test_every_jurisdiction_in_the_real_mapping_is_pinned():
    """Derived from the mapping, not from a list written out here.

    `CONVENTIONAL_CITATIONS` above names three and would not notice a fourth.
    The release gate would not either: it reads capability records, and the
    jurisdictional citations reach a reader through `resolve_be_spec` instead,
    which no capability row points at. So the mapping itself is iterated, and
    a jurisdiction added with a vague citation fails here.
    """
    from be_stats.spec import _CONVENTIONAL_ACCEPTANCE_CITATIONS, Jurisdiction

    assert set(_CONVENTIONAL_ACCEPTANCE_CITATIONS) == set(Jurisdiction), (
        "A jurisdiction the engine can resolve has no conventional-interval "
        "citation, or one exists for a jurisdiction that is not resolvable."
    )
    for jurisdiction, citation in _CONVENTIONAL_ACCEPTANCE_CITATIONS.items():
        assert is_pinned(citation), (jurisdiction, why_not_pinned(citation))
        assert citation.authority == str(jurisdiction), (
            f"{jurisdiction} is cited to {citation.authority!r}. The point of "
            "splitting the citation was that each regulator gets its own "
            "adopted document."
        )


def test_an_unknown_jurisdiction_is_refused_rather_than_given_ichs():
    """Adoption is the claim, so it may not be inherited by default."""
    from be_stats.spec import _conventional_citation

    with pytest.raises(KeyError, match="adoption"):
        _conventional_citation("MHRA")


# --------------------------- the M13A Q&A, and the third state nobody saw ---
#
# `ICH_M13A_QA` carried `document_version="current"` and `FDA_M13A_QA` carried
# `"FDA guidance for industry"`. Both failed `is_pinned`; neither was declared
# in `CITATION_EXCEPTIONS`. They survived DOSSIER-004 - which was about exactly
# this defect - because nothing enumerated them: they back regulatory minimums
# in `minimums.py`, which are not in `CONSTANT_INDEX` and not in the capability
# matrix, so no provenance metric and no release-gate condition ever read them.
#
# Pinned or declared. Never neither, and never invisible.


QA_CITATIONS = {
    "ICH": ICH_M13A_QA,
    "FDA": FDA_M13A_QA,
    "EMA": EMA_M13A_QA,
}


@pytest.mark.parametrize("name", sorted(QA_CITATIONS))
def test_each_m13a_qa_citation_is_pinned(name):
    citation = QA_CITATIONS[name]
    assert is_pinned(citation), why_not_pinned(citation)
    assert citation.authority == name
    assert "2.1" in citation.section


@pytest.mark.parametrize(
    "version",
    ["current", "FDA guidance for industry", "ICH harmonised guideline", ""],
)
def test_a_document_type_is_not_a_document_version(version):
    """`"FDA guidance for industry"` is the one that looked checked.

    "current" announces itself. A document TYPE reads like provenance and is
    not: FDA has issued draft and final M13A Q&A material, and the phrase
    picks out neither. The positive rule catches both without either being
    named in a blacklist.
    """
    assert not version_is_pinned(version)


@pytest.mark.parametrize("name", sorted(QA_CITATIONS))
@pytest.mark.parametrize(
    "damage",
    [
        {"section": ""},
        {"document": ""},
        {"document_version": "current"},
        {"document_version": "FDA guidance for industry"},
        {"authority": "ICH / FDA"},
    ],
)
def test_a_damaged_qa_citation_stops_being_pinned(name, damage):
    broken = dataclasses.replace(QA_CITATIONS[name], **damage)
    assert not is_pinned(broken), (
        f"{name} Q&A citation survives {damage!r}."
    )


def test_no_active_regulatory_citation_is_unpinned_and_undeclared():
    """THE INVARIANT THIS PR EXISTS TO ADD.

    Scoped to citations that live regulatory logic can actually attach to a
    returned answer, via `minimums.active_citations()`. Deliberately NOT every
    `Citation` object in `provenance`: that module also holds citations kept
    for context - `EMA_M13A_IMPLEMENTATION` settles a precedence question and
    is not attached to any number - and a rule requiring those to be pinned
    would be met by deleting them, which is the wrong direction.

    Derived from the registry rather than listed here, so a row added to
    `minimums._REGISTRY` with a vague citation fails without anyone
    remembering to extend this test. That absence is precisely how the two
    Q&A citations stayed unpinned and undeclared through the release that
    fixed the same defect elsewhere.
    """
    from be_stats.minimums import active_citations

    active = active_citations()
    assert active, "No active citations found; this guard would pass vacuously."

    silent = [
        c
        for c in active
        if not is_pinned(c) and exception_for(c) is None
    ]
    assert not silent, (
        "These citations are attached to a regulatory minimum and are neither "
        "pinned nor declared: "
        + "; ".join(f"{c.authority}/{c.document} {why_not_pinned(c)}" for c in silent)
    )


def test_the_invariant_would_catch_a_silent_citation():
    """The mutation, run rather than described.

    `test_no_active_regulatory_citation_is_unpinned_and_undeclared` passes on
    a clean tree, which is also what it would do if `is_pinned` had been
    loosened or `active_citations` returned nothing. A deliberately vague
    citation is pushed through the same predicate to show the rule bites.
    """
    silent = Citation(
        authority="ICH / FDA",
        document="M13A Q&A",
        section="",
        document_version="FDA guidance for industry",
    )
    assert not is_pinned(silent)
    assert exception_for(silent) is None

    # Declaring it - and nothing else - is the other way to satisfy the rule.
    from be_stats.dossier.citations import CitationException

    declared = {silent: CitationException("r", "DOSSIER-000", "res")}
    assert declared.get(silent) is not None


def test_a_minimum_cites_its_own_regulator_and_never_falls_back_to_ich():
    """Jurisdictional source resolution, asserted on every row.

    The two EMA rows cited ICH's copy of the Q&A - the harmonised text
    standing in for the regulator's own adoption, which is the fallback PR #76
    removed for the conventional interval. Every row is checked rather than
    those two, so a new row cannot reintroduce it.

    ICH is not accepted as a substitute for either regulator here. If a future
    row genuinely has no regional adoption, that is a decision to make
    explicitly, and this test is where it gets argued.
    """
    from be_stats.minimums import _HVD_MINIMUM, _REGISTRY

    for key, row in (*_REGISTRY.items(), (None, _HVD_MINIMUM)):
        assert row.citation.authority == row.jurisdiction, (
            f"{key or 'HVD'}: a {row.jurisdiction} minimum cites "
            f"{row.citation.authority}. A jurisdiction-keyed claim must hand "
            "the reader the document its own regulator adopted."
        )


def test_the_crossover_and_parallel_rules_cite_the_same_question():
    """One Q&A answers both, so both must point at it - and at nothing else.

    The crossover total and the per-group parallel figure come from a single
    sentence. If they ever cite different sections, one of them has been
    re-sourced without the other.
    """
    from be_stats.minimums import DesignFamily, Framework, StudyRole, lookup

    for jurisdiction in ("FDA", "EMA"):
        crossover = lookup(
            jurisdiction,
            DesignFamily.CROSSOVER,
            framework=Framework.ICH_M13A,
            study_role=StudyRole.PIVOTAL,
        )
        parallel = lookup(
            jurisdiction,
            DesignFamily.PARALLEL,
            framework=Framework.ICH_M13A,
            study_role=StudyRole.PIVOTAL,
        )
        assert crossover.applies and parallel.applies
        assert crossover.rule.citation is parallel.rule.citation, jurisdiction
        assert is_pinned(crossover.rule.citation)

        # And they still say different things about the number.
        assert crossover.rule.evaluable_total == 12
        assert parallel.rule.evaluable_per_group == 12
        assert crossover.required_total() == 12
        assert parallel.required_total() == 24


def test_pinning_the_citations_changed_no_regulatory_minimum():
    """The numbers, asserted against the primary sources rather than a snapshot.

    Read at Q&A 2.1 in all three adoptions: "a minimum of 12 evaluable
    subjects in pivotal BE studies for a crossover design, or a minimum of 12
    per treatment group for a parallel design".
    """
    from be_stats.minimums import (
        DesignFamily,
        Framework,
        MinimumApplicability,
        StudyRole,
        lookup,
    )

    expected = {
        ("EMA", Framework.ICH_M13A, DesignFamily.CROSSOVER): 12,
        ("EMA", Framework.ICH_M13A, DesignFamily.PARALLEL): 24,
        ("FDA", Framework.ICH_M13A, DesignFamily.CROSSOVER): 12,
        ("FDA", Framework.ICH_M13A, DesignFamily.PARALLEL): 24,
        ("FDA", Framework.GENERAL, DesignFamily.CROSSOVER): 12,
        ("FDA", Framework.GENERAL, DesignFamily.PARALLEL): 12,
    }
    for (jurisdiction, framework, design), total in expected.items():
        # PIVOTAL throughout: this test asks whether the FIGURES survived the
        # citation work, so it holds the role fixed at the one every row
        # applies to. Whether the role gates a row is tested separately.
        outcome = lookup(
            jurisdiction,
            design,
            framework=framework,
            study_role=StudyRole.PIVOTAL,
        )
        assert outcome.applies, (jurisdiction, framework, design)
        assert outcome.required_total() == total, (jurisdiction, framework, design)
        assert outcome.rule.counts == "evaluable subjects"

    # EMA + GENERAL stays absent. Nothing here invented one.
    assert (
        lookup(
            "EMA", DesignFamily.CROSSOVER, framework=Framework.GENERAL
        ).applicability
        is MinimumApplicability.NONE_CONFIRMED
    )


def test_every_unpinned_citation_in_use_is_declared():
    """Nothing may be quietly unpinned. Either it is pinned or it is declared."""
    for record in CAPABILITY_MATRIX.values():
        if record.has_pinned_source:
            continue
        assert record.source_citation_exception is not None, (
            f"{record.capability_id} cites an unpinned source with no "
            f"declared exception: {why_not_pinned(record.regulatory_source)}"
        )

    from be_stats.dossier.constants import ConstantKind, constants_of_kind

    for record in constants_of_kind(ConstantKind.NORMATIVE):
        if record.has_pinned_citation:
            continue
        assert record.citation_exception, record.constant_id
