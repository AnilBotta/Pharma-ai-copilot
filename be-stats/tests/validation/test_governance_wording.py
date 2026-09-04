"""Tier 1B is REQUIRED evidence for a promotion. It does not perform one.

THE CLAIM THIS MODULE GUARDS

    tier 1A   the engine branches where the regulator branches
    tier 1B   the arithmetic lands where the regulator's lands

Tier 1B is the numerical evidence a VALIDATED promotion requires. It is not
sufficient for one, and neither tier on its own establishes VALIDATED status or
submission suitability. `release_gate.check_capability` also requires a pinned
regulatory source, no disqualifying finding, no blocker naming the capability,
and an explicitly reviewed transition - it was written specifically so that one
numerical match cannot promote a method.

Six places in this package said, in prose, that tier 1B "licenses a filing".
Every one of them predated or accompanied the release gate that contradicts it.
None was load-bearing - no code read those sentences - which is exactly why they
survived: a docstring cannot fail a build, and a reviewer under time pressure
reads the docstring.

WHY THIS IS A POSITIVE REQUIREMENT AND NOT A PHRASE BAN

A blacklist of "licenses a filing" would fail on this very module, and on the
finding that records the correction, and on any future text explaining what the
mistake was. This repository has made that blunt-match error five times, and the
fix is always the same: assert where the claim would carry force.

So the rule is conditional rather than prohibitive:

    A PASSAGE THAT CONNECTS TIER 1B TO FILING OR SUBMISSION SUITABILITY MUST
    ALSO CARRY THE QUALIFICATION.

Prose that explains the error passes, because explaining it means saying that
tier 1B alone is not sufficient. A bare new overstatement fails, because it
will not contain the qualification - that is what makes it bare.

The unit is the PARAGRAPH, not the line. Docstrings wrap at 79 characters and
every real sentence here spans several lines; a line-scoped check would split
"neither tier alone establishes VALIDATED status" from the claim it qualifies
and fail on correct text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

SKIP_PARTS = {".venv", "__pycache__", ".ruff_cache", "build"}
SUFFIXES = {".py", ".md"}

#: The passage is talking about the evidence tiers.
#:
#: Both tokens required. "1B" alone appears in data files and case ids; "tier"
#: alone appears wherever the ladder is discussed without a specific rung.
_TIER = re.compile(r"\btiers?\b|\bsubtier\b", re.IGNORECASE)
_ONE_B = re.compile(r"\b1B\b|\btier[-\s]?1b\b", re.IGNORECASE)

#: The passage is claiming something about filing or submission suitability.
_FILING_CLAIM = re.compile(
    r"licen[sc]e[sd]?\s+a\s+filing"
    r"|licen[sc]ing\s+a\s+filing"
    r"|licen[sc]e\s+a\s+filing"
    r"|supports?\s+a\s+filing"
    r"|filing[-\s]?ready"
    r"|submission[-\s](?:suitab\w*|ready)"
    r"|sufficient\s+for\s+(?:a\s+)?(?:filing|submission|VALIDATED)",
    re.IGNORECASE,
)

#: The qualification that makes such a passage correct.
#:
#: Any ONE of these is enough. They are the ways this package actually states
#: the rule, plus the two negations a correction would naturally use.
_QUALIFIED = re.compile(
    r"neither tier alone"
    r"|not sufficient"
    r"|is not sufficient"
    r"|required .{0,60}not sufficient"
    r"|requires? .{0,80}promotion"
    r"|release[- ]gate|release gate"
    r"|do(?:es)? not license"
    r"|do not license"
    r"|previously said",
    re.IGNORECASE | re.DOTALL,
)


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """Blank-line separated blocks, WHITESPACE-NORMALISED, with start lines.

    Normalising is not cosmetic. Docstrings wrap at 79 characters, so the
    qualification "it is not sufficient" routinely arrives as "it is not\\n
    sufficient" - and the first version of this guard, matching a literal
    space, failed on its own correctly-qualified docstring. A phrase that
    happens to straddle a line break is the same phrase.
    """
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start = 1
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not current:
                start = number
            current.append(line)
        elif current:
            blocks.append((start, " ".join(" ".join(current).split())))
            current = []
    if current:
        blocks.append((start, " ".join(" ".join(current).split())))
    return blocks


def _source_files() -> list[Path]:
    """Everything the rule applies to - except this module.

    THIS FILE IS EXCLUDED, AND THAT IS NOT A LOOPHOLE.

    It contains the six overstatements verbatim, as fixtures, so that
    `test_the_guard_would_catch_the_original_wording` can prove the guard
    bites on the sentences that actually shipped. Scanning itself would force
    those fixtures to be written qualified - which is to say, written as
    passing text - and a guard whose counter-examples must pass is a guard
    that has never been shown to catch anything.

    The exclusion is one file, named here, whose entire purpose is stated in
    its module docstring.
    """
    return [
        path
        for path in sorted(PACKAGE_ROOT.rglob("*"))
        if path.is_file()
        and path.suffix in SUFFIXES
        and not SKIP_PARTS & set(path.parts)
        and path.resolve() != Path(__file__).resolve()
    ]


def _offending_passages() -> list[str]:
    offenders: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - no such file today
            continue
        for line_number, block in _paragraphs(text):
            if not (_TIER.search(block) and _ONE_B.search(block)):
                continue
            if not _FILING_CLAIM.search(block):
                continue
            if _QUALIFIED.search(block):
                continue
            offenders.append(
                f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line_number}\n"
                f"    {' '.join(block.split())[:300]}"
            )
    return offenders


def test_there_are_files_to_check():
    """A glob that stopped matching would make everything below vacuous."""
    files = _source_files()
    assert len(files) > 40, f"only {len(files)} files scanned"


def test_the_detector_reaches_real_prose_in_the_package():
    """A sanity check that the scan meets text, not a proof the patterns work.

    `test_the_guard_would_catch_the_original_wording` is the proof: it runs the
    patterns against the six sentences that actually shipped. This one only
    confirms the repository walk arrives somewhere the rule applies, so a
    guard that silently policed an empty set would be visible.

    The threshold is deliberately low. Tying it to today's exact count would
    turn an ordinary rewording into a failure about the detector, which teaches
    people to lower thresholds - and a threshold somebody has learned to lower
    is not a threshold.
    """
    seen = [
        f"{path.name}:{line}"
        for path in _source_files()
        for line, block in _paragraphs(path.read_text(encoding="utf-8"))
        if _TIER.search(block)
        and _ONE_B.search(block)
        and _FILING_CLAIM.search(block)
    ]
    assert len(seen) >= 2, (
        f"the detector matched only {seen}. The package states the tier-1B "
        "rule in several places; matching almost none of them means the "
        "pattern has stopped working."
    )


def test_no_passage_claims_tier_1b_alone_licenses_a_filing():
    """The rule, stated as a requirement rather than a ban.

    A passage may connect tier 1B to filing or submission suitability - it must
    then also carry the qualification that neither tier alone establishes it.
    """
    offenders = _offending_passages()
    assert not offenders, (
        "These passages connect tier 1B to filing or submission suitability "
        "without the qualification that tier 1B is REQUIRED evidence for a "
        "VALIDATED promotion and not sufficient for one:\n\n"
        + "\n\n".join(offenders)
    )


@pytest.mark.parametrize(
    "passage",
    [
        # The exact shape of the six sentences this PR corrected.
        "Tier 1A attests the algorithm and tier 1B reproduces the "
        "regulator's numbers, and only the second licenses a filing.",
        "One regulator-published table is tier 1B; that is the evidence "
        "that licenses a filing.",
        "Reproducing them is the only kind of tier 1B evidence that "
        "supports a filing.",
    ],
)
def test_the_guard_would_catch_the_original_wording(passage: str):
    """Proof the guard bites, on the sentences that actually shipped.

    A guard nobody has seen fail is a guard nobody has evidence works - the
    lesson from the unreachable assertions in `test_algorithm_conformance.py`.
    """
    assert _TIER.search(passage)
    assert _ONE_B.search(passage)
    assert _FILING_CLAIM.search(passage)
    assert not _QUALIFIED.search(passage), (
        "This passage would be treated as qualified, so the guard would let it "
        "through."
    )


@pytest.mark.parametrize(
    "passage",
    [
        # Correct: qualified in the same breath.
        "Tier 1B is the numerical evidence a VALIDATED promotion requires, "
        "and neither tier alone establishes VALIDATED status or submission "
        "suitability.",
        # Correct: prose EXPLAINING the mistake. A phrase ban would fail here,
        # which is the whole reason the rule is conditional.
        "The subtier message previously said tier 1B licenses a filing. That "
        "was wrong: it is required evidence, not sufficient evidence.",
        # Correct: about VALIDATED STATUS, which does license a filing, and
        # which never mentions a tier - so it is not matched at all.
        "Only VALIDATED licenses a filing; three implemented statuses do not.",
    ],
)
def test_the_guard_does_not_fire_on_correct_or_explanatory_prose(passage: str):
    """The false-positive half, which is what makes the guard survivable."""
    matched = (
        _TIER.search(passage)
        and _ONE_B.search(passage)
        and _FILING_CLAIM.search(passage)
    )
    assert not (matched and not _QUALIFIED.search(passage)), (
        "The guard fires on correct prose, so somebody will weaken it."
    )
