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
from be_stats.provenance import Citation

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


def test_the_declared_exception_is_keyed_by_the_citation():
    """Which is what keeps three consumers consistent for free.

    The two conventional-interval constants and the AVERAGE_BE_2X2 capability
    all reference one `Citation` object. Keying by capability id or constant
    id would need three entries that could drift.
    """
    capability = CAPABILITY_MATRIX["AVERAGE_BE_2X2"]
    lower = CONSTANT_INDEX["CONVENTIONAL_LOWER_PERCENT"]
    upper = CONSTANT_INDEX["CONVENTIONAL_UPPER_PERCENT"]

    assert capability.regulatory_source is lower.citation is upper.citation

    exception = exception_for(capability.regulatory_source)
    assert exception is not None
    assert capability.source_citation_exception is exception
    assert exception.tracked_as in lower.citation_exception
    assert lower.citation_exception == upper.citation_exception


def test_every_declared_exception_names_a_real_finding():
    from be_stats.dossier.findings import FINDINGS

    assert CITATION_EXCEPTIONS, "An empty registry would pass vacuously."
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
