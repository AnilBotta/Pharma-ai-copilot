"""The deployment manifest must not drift from the backend it deploys.

`api/requirements.txt` is a second copy of the backend's runtime dependencies,
trimmed of test and lint tooling. Second copies drift, and this one drifts
silently in the worst direction: the code imports fine locally, the build
succeeds, and the function dies on its first request with an ImportError that
nobody sees until a user hits it.

These tests turn that into a failure at `pytest -q`, which is where it is cheap.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND_REQS = REPO / "backend" / "requirements.txt"
VERCEL_REQS = REPO / "api" / "requirements.txt"
VERCEL_JSON = REPO / "vercel.json"
ENTRYPOINT = REPO / "api" / "index.py"

#: Deliberately absent from the deployment bundle. Test runners, linters, type
#: checkers and the local dev server are not part of the running application.
DEV_ONLY = {
    "coverage", "iniconfig", "mypy", "mypy-extensions", "pathspec", "pluggy",
    "pygments", "pytest", "pytest-asyncio", "pytest-cov", "respx", "ruff",
    "uvicorn", "watchfiles", "httptools", "websockets",
}


def _packages(path: pathlib.Path) -> dict[str, str]:
    """Package name (normalised) -> pinned version."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*(.+)$", line)
        if match:
            found[match.group(1).lower().replace("_", "-")] = match.group(2)
    return found


def test_no_runtime_dependency_is_missing_from_the_deployment():
    backend = _packages(BACKEND_REQS)
    vercel = _packages(VERCEL_REQS)

    expected = {n for n in backend if n not in DEV_ONLY}
    missing = sorted(expected - set(vercel))

    assert not missing, (
        "These packages are in backend/requirements.txt but not in "
        f"api/requirements.txt, so they will be absent at runtime: {missing}. "
        "Add them there, or add them to DEV_ONLY in this test if they really "
        "are development-only."
    )


def test_deployment_pins_match_the_backend():
    backend = _packages(BACKEND_REQS)
    vercel = _packages(VERCEL_REQS)

    mismatched = sorted(
        f"{name}: backend {backend[name]} vs deployment {version}"
        for name, version in vercel.items()
        if name in backend and backend[name] != version
    )
    assert not mismatched, (
        "The deployment would install different versions from the ones the "
        f"tests run against: {mismatched}"
    )


def test_deployment_ships_no_test_tooling():
    vercel = _packages(VERCEL_REQS)
    strays = sorted(set(vercel) & DEV_ONLY)
    assert not strays, f"Development-only packages in the deployment bundle: {strays}"


# --------------------------------------------------- first-party packages ---
#
# WHAT THE MIRROR CHECK ABOVE CANNOT SEE
#
# It compares two requirements files. `be-stats` is in neither, because it is a
# LOCAL package installed editable into the dev venv - so every local run and
# every test resolved it, and the deployment had no copy at all.
#
# `app.sas_validation.program` imports `be_stats.replicate_abe` at module
# scope and `app.main` imports the sas_validation package, so the miss did not
# degrade one feature: `from app.main import app` raised, the function never
# started, and EVERY /api route returned 500. Production served 27 requests and
# 27 fives before anyone traced it.
#
# Two things must therefore hold, and neither is about pip:
#   1. the source ships    -> includeFiles in vercel.json
#   2. the path is set     -> sys.path in api/index.py
# plus the third-party packages the local package itself imports.

#: Local packages the deployed app imports. Name -> (source root relative to
#: the repository, importable module directory).
FIRST_PARTY = {"be_stats": ("be-stats/src", "be-stats/src/be_stats")}


def test_local_packages_are_on_the_entrypoint_path():
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    for package, (source_root, _) in FIRST_PARTY.items():
        segment = source_root.split("/")[0]
        assert segment in entry, (
            f"{package} is imported by the deployed app but api/index.py never "
            f"puts {source_root} on sys.path, so the function cannot import it."
        )


def test_local_package_sources_are_bundled():
    import json

    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))
    include = config["functions"]["api/index.py"].get("includeFiles", "")

    for package, (_, module_dir) in FIRST_PARTY.items():
        assert module_dir in include, (
            f"{package} is imported by the deployed app but {module_dir} is not "
            f"in includeFiles, so its source never reaches the bundle. Present: "
            f"{include!r}"
        )


def test_local_package_dependencies_reach_the_deployment():
    """be-stats declares scipy and numpy. pip installs neither unless asked.

    Shipping the source without its dependencies swaps one ImportError for
    another, which is a worse outcome than the first: it looks fixed.
    """
    declared = (REPO / "be-stats" / "pyproject.toml").read_text(encoding="utf-8")
    block = declared[declared.index("dependencies = ["):]
    block = block[: block.index("]")]

    required = set(re.findall(r'"([A-Za-z0-9._-]+)\s*[><=]', block))
    assert required, "be-stats declares no dependencies - has this gone stale?"

    vercel = _packages(VERCEL_REQS)
    missing = sorted(
        name for name in required if name.lower().replace("_", "-") not in vercel
    )
    assert not missing, (
        f"be-stats needs {missing}, absent from api/requirements.txt. The "
        "bundle would import be_stats and die on its first transitive import."
    )


def test_the_deployed_entrypoint_actually_imports():
    """The end the other tests only approach.

    Every check above verifies a precondition; this one runs the import the
    serverless function runs. It executes in this repository, so it cannot
    prove the BUNDLE is complete - but it does prove the entrypoint's own path
    setup is coherent, and it fails loudly if someone adds a module-scope
    import of something the deployment has no route to.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_vercel_entry", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "app"), "api/index.py did not expose `app`"


def test_vercel_config_routes_the_api_to_the_python_function():
    import json

    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

    functions = config.get("functions", {})
    assert "api/index.py" in functions, "The Python entrypoint is not configured."

    entry = functions["api/index.py"]

    # Without includeFiles the bundle contains api/index.py and nothing it
    # imports, so the deployment fails on `from app.main import app`.
    assert "backend/app" in entry.get("includeFiles", ""), (
        "backend/app must be bundled with the function or its imports fail."
    )

    # Hobby's ceiling is 300s and cannot be raised. Above that the setting is
    # silently ineffective there, which is worse than a visible error.
    assert entry.get("maxDuration", 0) <= 800, "Above the Pro maximum."

    sources = [r.get("source") for r in config.get("rewrites", [])]
    assert "/api/(.*)" in sources, (
        "Without this rewrite only /api/index reaches FastAPI; every real "
        "route (/api/health, /api/pdp/...) would 404."
    )


def test_vercelignore_cannot_swallow_application_source():
    """A bare name in .vercelignore matches that name at ANY depth.

    This is not hypothetical. The line `supabase`, meant for the top-level
    migrations directory, also matched `lib/supabase/` and deleted the
    frontend's Supabase client from the deployment bundle. The build failed
    with `Module not found: Can't resolve '@/lib/supabase/client'`, which reads
    like a broken import rather than a file that had been removed.

    Anything excluding a directory must therefore be anchored with a leading
    slash. Bare patterns are only allowed for extensions and dot-files, where
    matching at any depth is the intent.
    """
    ignore = REPO / ".vercelignore"
    assert ignore.exists(), "Without .vercelignore, a CLI deploy uploads backend/.env."

    offenders = []
    for raw in ignore.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue

        # Anchored either by a leading slash or, per gitignore rules, by
        # containing a slash anywhere but the end.
        if line.startswith("/") or "/" in line.rstrip("/"):
            continue
        # `*.pyc` and friends are meant to match at any depth.
        if line.startswith("*") or line.startswith("."):
            continue

        offenders.append(line)

    assert not offenders, (
        "These .vercelignore entries are bare names, so they match a directory "
        f"of that name at ANY depth and can delete application source: "
        f"{offenders}. Prefix each with '/' to anchor it to the repo root."
    )


def test_vercelignore_still_excludes_env_files():
    """The reason the file exists at all."""
    lines = {
        line.strip()
        for line in (REPO / ".vercelignore").read_text(encoding="utf-8").splitlines()
    }
    assert "**/.env" in lines, (
        "A `vercel --prod` from a laptop uploads the working directory, which "
        "contains backend/.env with the service role and OpenAI keys."
    )


def test_the_frontend_supabase_client_is_not_excluded():
    """Guard the exact file the bad pattern removed."""
    client = REPO / "lib" / "supabase" / "client.ts"
    assert client.exists(), "lib/supabase/client.ts moved; update this guard."

    for raw in (REPO / ".vercelignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue

        # An anchored entry cannot reach lib/supabase; `/supabase` is fine and
        # is in fact the correction for the bug this guards.
        if line.startswith("/"):
            assert line.rstrip("/") not in {"/lib", "/lib/supabase"}, (
                f"'{line}' excludes the frontend Supabase client."
            )
            continue

        assert line.rstrip("/") not in {"lib", "supabase", "lib/supabase"}, (
            f"'{line}' is unanchored and matches lib/supabase/, which removes "
            "the frontend Supabase client from the bundle. Anchor it: '/{line}'."
        )


def test_middleware_does_not_intercept_the_api():
    """Next.js middleware must not run on /api/*.

    On the deployment `/api/*` is a Python function, not a Next.js route. When
    the middleware matcher covered it, Next intercepted `/api/health`, found no
    Supabase cookie, and redirected to `/login` — so every API call returned
    200 with the sign-in page's HTML. The frontend then reported "Cannot reach
    the API", which sends you looking at the backend when the request never
    left the frontend.

    Cookie-based route protection and bearer-token API auth guard two different
    surfaces. Layering the first over the second breaks it without adding
    anything.
    """
    middleware = (REPO / "middleware.ts").read_text(encoding="utf-8")

    match = re.search(r'matcher:\s*\[(.*?)\]', middleware, re.DOTALL)
    assert match, "Could not find the middleware matcher; this guard needs updating."

    patterns = match.group(1)
    assert "?!api|" in patterns or "?!api/" in patterns, (
        "The middleware matcher does not exclude /api. Next.js will intercept "
        "requests meant for the Python function and answer them with HTML. "
        f"Found: {patterns.strip()[:200]}"
    )


def test_entrypoint_exposes_the_same_app_the_tests_use():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "from app.main import app" in source, (
        "The deployment must serve the same application object as local runs, "
        "not a separately constructed one."
    )
