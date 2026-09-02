"""The browser must actually reach the backend.

WHY A PYTHON TEST GUARDS A TYPESCRIPT FILE

`manual-validation.tsx` (PR #65) and `statistical-review.tsx` (PR #66) each
carried a private helper:

    fetch(`/api${path}`)

A RELATIVE url, so it resolved against the FRONTEND origin instead of
`NEXT_PUBLIC_API_BASE_URL`, and with no Authorization header. Every SAS control
therefore requested `http://localhost:3000/api/...`, which Next.js answers with
a 404 HTML page because it has no `/api` route handler and no rewrite.

Not one of those controls had ever reached the backend. The symptom reaching a
person was a greyed-out Download button, because the package listing failed and
the component swallowed the failure.

There is no frontend test runner in this repository, so this guard is here -
where the suite that already runs will fail if the pattern returns. Text
matching is crude, but the thing being prevented is textual: a relative fetch
in a component that must not have one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SAS_UI = REPO / "app" / "(app)" / "settings" / "sas-validation"

COMPONENTS = sorted(SAS_UI.glob("*.tsx"))

#: A fetch whose URL starts with a literal /api - the exact defect. An absolute
#: URL built from the shared base is fine and is what `lib/api.ts` does.
RELATIVE_FETCH = re.compile(r"""fetch\(\s*[`'"]/api""")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def code_only(source: str) -> str:
    """Strip comments before matching.

    The first version of this file searched raw source and failed on the
    docstrings that DESCRIBE the bug - `lib/api.ts` explains the defect by
    quoting `fetch(\\`/api${path}\\`)`, and the guard flagged the explanation.

    That is the same blunt-search mistake PR #64 made with "validation_status"
    and PR #69 made with "signed". Prose about a defect is not the defect.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def test_there_are_components_to_check():
    """A glob that silently matched nothing would pass forever."""
    assert COMPONENTS, f"no components found under {SAS_UI}"


@pytest.mark.parametrize("component", COMPONENTS, ids=lambda p: p.name)
def test_no_sas_component_fetches_a_relative_api_url(component: Path):
    """The bug, guarded directly.

    A relative `/api` fetch goes to whatever origin serves the page, which is
    the Next.js dev server, not the backend.
    """
    source = code_only(component.read_text(encoding="utf-8"))
    matches = RELATIVE_FETCH.findall(source)
    assert not matches, (
        f"{component.name} fetches a relative /api url. It will hit the "
        "frontend origin and 404. Use the sasValidation client in lib/api.ts, "
        "which applies NEXT_PUBLIC_API_BASE_URL and the bearer token."
    )


@pytest.mark.parametrize("component", COMPONENTS, ids=lambda p: p.name)
def test_every_sas_component_goes_through_the_shared_client(component: Path):
    """One place knows the base URL and the token, so there is one place to
    change when either moves - and no component can forget the token."""
    source = component.read_text(encoding="utf-8")
    if "fetch(" not in source and "sasValidation" not in source:
        pytest.skip("component makes no requests")
    assert "@/lib/api" in source, (
        f"{component.name} makes requests without importing the shared API "
        "client"
    )


def test_the_shared_client_sends_the_token_and_the_base_url():
    """Both halves of what the component helpers were missing."""
    api = (REPO / "lib" / "api.ts").read_text(encoding="utf-8")

    # Every request goes through BASE_URL, never a bare /api.
    assert "`${BASE_URL}/api${path}`" in api
    assert not RELATIVE_FETCH.search(code_only(api))

    # And carries the bearer token.
    assert "Authorization: `Bearer ${session.access_token}`" in api

    # The multipart variant must NOT set a content type: the browser has to
    # choose the multipart boundary itself.
    assert "authHeadersForForm" in api
    assert 'delete headers["Content-Type"]' in api


def test_the_sas_client_exposes_every_route_the_ui_needs():
    api = (REPO / "lib" / "api.ts").read_text(encoding="utf-8")
    block = api[api.index("export const sasValidation") : api.index("export const pdp")]

    for method in (
        "listPackages",
        "generatePackage",
        "downloadUrl",
        "uploadResult",
        "uploadLog",
        "reviewContext",
        "generateAiReview",
        "recordReview",
    ):
        assert f"{method}:" in block, method


# ------------------------------------------- package recovery is explicit ---


def test_package_recovery_failure_is_never_swallowed():
    """PR #69 shipped a bare `catch {}`.

    A failed lookup then rendered identically to "no package exists": a
    disabled Download button and no explanation. They are completely different
    facts and the user could not tell them apart.
    """
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")

    assert re.search(r"catch\s*\{\s*\n\s*//", source) is None, (
        "a bare catch in the recovery path hides a failed package lookup "
        "behind a disabled button"
    )
    # Four distinct states, not a boolean.
    for state in ("loading", "restored", "none", "error"):
        assert f'"{state}"' in source, state
    assert "RecoveryStatus" in source


def test_a_failed_lookup_is_reported_and_retryable():
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")

    assert "Could not load existing validation packages." in source
    assert "Retry" in source
    assert "void restore()" in source


def test_no_package_and_failed_lookup_say_different_things():
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")

    assert "No validation package exists yet" in source
    assert "Could not load existing validation packages" in source


def test_a_failed_lookup_never_generates_a_replacement():
    """THE MOST IMPORTANT ONE.

    Generating produces a different package id and archive hash. If a failed
    lookup silently generated, an operator could run one package while we hold
    the record of another - and our own provenance checks would then reject
    their result. Recovery must never call generate.
    """
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")

    restore_block = source[
        source.index("const restore = useCallback") : source.index(
            "const generate = useCallback"
        )
    ]
    assert "generatePackage" not in restore_block
    assert "generate(" not in restore_block

    # And the mount effect calls recovery, not generation. Sliced to the
    # effect's own body: a wider window catches the `const generate` that
    # follows it and fails on the wrong thing.
    start = source.index("useEffect(() => {")
    effect = source[start : source.index("}, [restore]);", start)]
    assert "restore()" in effect
    assert "generate" not in effect


def test_the_active_package_is_shown_before_the_controls_that_act_on_it():
    """Which package the buttons operate on must be readable before they are
    pressed, not inferred afterwards from a download."""
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")

    identity = source.index("Active package")
    controls = source.index("Download package")
    assert identity < controls, (
        "the active package id and hash must render above the buttons"
    )
    assert "pkg.package_id" in source
    assert "pkg.archive_sha256" in source


def test_download_uses_the_restored_package_id():
    """Not a regenerated one, and not a hard-coded one."""
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")
    assert "sasValidation.downloadUrl(pkg.package_id)" in source


def test_the_controls_are_gated_on_a_package_not_on_having_generated_one():
    """`pkg` is set by recovery OR by generation, so a restored package enables
    the same controls a freshly generated one does."""
    source = (SAS_UI / "manual-validation.tsx").read_text(encoding="utf-8")
    assert "disabled={!pkg || busy !== null}" in source
