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


def test_entrypoint_exposes_the_same_app_the_tests_use():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "from app.main import app" in source, (
        "The deployment must serve the same application object as local runs, "
        "not a separately constructed one."
    )
