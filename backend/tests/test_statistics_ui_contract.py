"""The statistics page must not flatten three states into one word.

WHY A PYTHON TEST GUARDS A TYPESCRIPT FILE

Same reason as `sas_validation/test_ui_api_contract.py`: there is no frontend
test runner in this repository, and the property being protected is one a
reader can lose at any layer. The engine keeps `implemented` and `validated`
apart, the API keeps them apart, and the page is where somebody would put a
green tick beside all of it because the design looked cleaner.

TEXT MATCHING, CAREFULLY

Comments are stripped before matching. This repository has made the blunt
-search mistake four times - "validation_status" matching a docstring,
"signed" matching a comment that described the bug, `fetch(\\`/api` matching the
prose explaining it, "alias" matching the sentence that DENIED the alias. Prose
about a claim is not the claim, and the page below explains at length why it
does not say "Available".
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "app" / "(app)" / "statistics" / "page.tsx"
API = REPO / "lib" / "api.ts"
SIDEBAR = REPO / "components" / "layout" / "sidebar.tsx"
SAS_PAGE = (
    REPO / "app" / "(app)" / "settings" / "sas-validation" / "page.tsx"
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def code_only(source: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def test_the_page_exists():
    """A path that stopped matching would make every test below vacuous."""
    assert PAGE.exists(), f"{PAGE} is missing"


def test_the_page_renders_all_three_states():
    source = code_only(PAGE.read_text(encoding="utf-8"))
    for status in (
        "VALIDATED",
        "IMPLEMENTED - VALIDATION PENDING",
        "NOT IMPLEMENTED",
    ):
        assert status in source, f"{status} is not rendered anywhere."


def test_the_page_never_calls_a_method_simply_available():
    """The exact word the brief forbids, checked outside comments.

    A whole-word match, so "availability" and "unavailable" do not trip it -
    the failure is a status badge that says "Available", not any use of the
    root.
    """
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert not re.search(r'"Available"|>Available<|`Available`', source), (
        "The page labels something 'Available'. Implemented and validated are "
        "different claims and one word cannot carry both."
    )


def test_the_three_states_are_visually_distinct():
    """Distinct badge variants, so the difference survives a glance.

    Three identical grey badges would satisfy the text check above and defeat
    its purpose.
    """
    source = code_only(PAGE.read_text(encoding="utf-8"))
    block = source[source.index("STATUS_STYLE") : source.index("const LEGEND")]
    variants = set(re.findall(r'variant:\s*"(\w+)"', block))
    assert len(variants) == 3, (
        f"The three states share badge variants {variants}. A reader "
        "scanning the page would not see the distinction."
    )


def test_each_state_carries_its_qualification_on_the_page():
    """The sentence that makes the badge mean something is not fine print."""
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert "blurb" in source
    assert "entry.qualification" in source, (
        "The per-method qualification from the API must be rendered; the badge "
        "alone does not say what pending validation means for this method."
    )


def test_the_page_shows_what_is_outstanding():
    """A page listing only what works reads as a claim that nothing is not."""
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert "dossier.blockers" in source
    assert "required_evidence" in source


def test_the_page_goes_through_the_shared_api_client():
    """No relative /api fetch, which is how the SAS controls silently 404ed."""
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert "@/lib/api" in source
    assert not re.search(r"""fetch\(\s*[`'"]/api""", source)
    assert "statistics.dossier()" in source


def test_a_load_failure_is_reported_rather_than_rendering_an_empty_list():
    """An empty method list reads as "this engine does nothing"."""
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert "setError" in source
    assert "could not be loaded" in source
    assert "Retry" in source
    assert not re.search(r"catch\s*\{\s*\}", source), "a bare catch swallows the failure"


def test_the_api_client_keeps_both_status_axes():
    source = code_only(API.read_text(encoding="utf-8"))
    block = source[
        source.index("export interface StatisticalCapability") : source.index(
            "export interface StatisticalFinding"
        )
    ]
    for field in ("implementation_status", "validation_status", "display_status"):
        assert field in block, (
            f"{field} is missing from the client type. Dropping one collapses "
            "two questions into one at the last layer that could keep them "
            "apart."
        )


def test_the_page_is_reachable_from_the_navigation():
    """An unreachable status page is one nobody reads."""
    source = code_only(SIDEBAR.read_text(encoding="utf-8"))
    assert '"/statistics"' in source


def test_the_page_states_provenance_per_kind_rather_than_as_one_figure():
    """The overstatement had to be fixed at every layer, this one included.

    The page previously said every regulatory constant carried the document,
    section and version it came from. It was reading a combined total, and the
    combined total was the shape that made the sentence writable.
    """
    source = code_only(PAGE.read_text(encoding="utf-8"))
    assert "provenance.normative_pinned" in source, (
        "The page must show the pinned count against the normative "
        "denominator, not a total over every constant."
    )
    assert "provenance.normative_exceptions" in source, (
        "The unpinned constants must be visible rather than netted off."
    )
    assert "provenance.verified" not in source, (
        "`verified` no longer exists on the wire; a stale read would render "
        "undefined and silently drop the qualification."
    )


def test_the_sas_page_no_longer_claims_the_program_is_verbatim():
    """The correction the runbook received and this page did not.

    `docs/SAS_FIRST_LIVE_RUN.md` was corrected because the executable SAS
    contains documented, allow-listed adaptations required to run. The same
    inaccurate sentence survived in the customer-facing step list, where it
    would have an operator report a discrepancy that is not one.
    """
    source = code_only(SAS_PAGE.read_text(encoding="utf-8"))
    assert "reproduced verbatim from the regulatory source" not in source
    assert "allow-listed adaptations" in source
