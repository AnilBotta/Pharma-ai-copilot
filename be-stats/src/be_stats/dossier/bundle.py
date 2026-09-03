"""The validation bundle: everything a QA reviewer needs, in one artefact.

WHAT IT IS FOR

Somebody outside the engineering team - internal QA, a statistical reviewer, a
customer's auditor - asks "what does this software do and what has been checked
about it". The answer should be one command and one folder, not a conversation.

WHAT IT CONTAINS

The canonical matrix, the routing matrix, the evidence manifest, the provenance
index, the findings register, the blockers, the release gate result, the test
summary, software versions, the git SHA and the environment. Everything is
derived from the same objects the engine reads, so a bundle cannot describe a
different package from the one that produced it.

WHAT IT MUST NOT CONTAIN

Secrets. The environment section is an ALLOW-LIST of variable names, not a dump
with a deny-list applied - a deny-list is a promise to have thought of every
future variable name, and nobody can keep that promise.
`test_the_bundle_contains_no_secrets` checks the rendered JSON against the
patterns that matter, but the allow-list is what actually makes it safe.

WHY THE TEST SUMMARY IS AN INPUT, NOT SOMETHING THIS RUNS

A bundle that runs the tests itself would report on a run nobody watched. The
CLI takes a JUnit XML produced by the run being certified, and records "not
supplied" when it is absent - which is honest, and which the release gate then
treats as it should.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

from be_stats import __version__
from be_stats.dossier.blockers import (
    BLOCKERS,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
)
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.catalogue import method_catalogue
from be_stats.dossier.constants import CONSTANT_INDEX, provenance_coverage
from be_stats.dossier.evidence import EVIDENCE_MANIFEST
from be_stats.dossier.findings import FINDINGS_REGISTER
from be_stats.dossier.refusals import REFUSALS
from be_stats.dossier.release_gate import certification_blockers, check_release_gate
from be_stats.dossier.routing import ROUTING_MATRIX, UNSUPPORTED_COMBINATION

#: Environment variables the bundle may record. An ALLOW-LIST: anything not
#: named here is absent from the bundle, whatever it is called.
ENVIRONMENT_ALLOW_LIST: tuple[str, ...] = (
    "CI",
    "GITHUB_RUN_ID",
    "GITHUB_WORKFLOW",
    "GITHUB_REF_NAME",
    "RUNNER_OS",
)


def _plain(value: Any) -> Any:
    """Dataclasses and enums to JSON-safe primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _git_sha() -> str:
    """The commit this bundle describes, or a stated absence."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unavailable"


def _git_dirty() -> bool | None:
    """Whether the working tree has uncommitted changes.

    Recorded because a bundle built from a dirty tree does not describe the
    commit it names, and a reviewer is entitled to know that before they read
    anything else.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _environment() -> dict[str, Any]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "variables": {
            name: os.environ[name]
            for name in ENVIRONMENT_ALLOW_LIST
            if name in os.environ
        },
        "note": (
            "Environment variables are recorded from an allow-list. Anything "
            "not named in ENVIRONMENT_ALLOW_LIST is absent from this bundle."
        ),
    }


def _software_versions() -> dict[str, str]:
    versions = {"be-stats": __version__, "python": sys.version.split()[0]}
    for name in ("numpy", "scipy"):
        try:
            module = __import__(name)
        except ImportError:  # pragma: no cover - both are hard dependencies
            versions[name] = "not installed"
        else:
            versions[name] = getattr(module, "__version__", "unknown")
    return versions


def _test_summary(junit_xml: str | None) -> dict[str, Any]:
    """Totals from a JUnit report produced by the run being certified.

    Skips are reported and NOT folded into passes. A suite that skipped
    everything exits zero, and a bundle that called that a pass would be the
    most expensive kind of wrong.
    """
    if not junit_xml:
        return {
            "supplied": False,
            "note": (
                "No JUnit report was supplied, so this bundle makes no claim "
                "about the test suite. It does not mean the tests passed."
            ),
        }

    import pathlib
    import xml.etree.ElementTree as ET

    path = pathlib.Path(junit_xml)
    if not path.exists():
        return {"supplied": False, "note": f"{junit_xml} does not exist."}

    root = ET.parse(path).getroot()
    totals = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
    nodes = [root] if root.tag == "testsuite" else list(root)
    for node in nodes:
        for key in totals:
            totals[key] += int(node.get(key) or 0)

    totals["passed"] = (
        totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    )
    totals["supplied"] = True
    totals["source"] = str(path)
    return totals


def build_bundle(*, junit_xml: str | None = None) -> dict[str, Any]:
    """Assemble the bundle. Pure data; writes nothing."""
    gate = check_release_gate()
    return {
        "schema": "be-stats.validation-bundle/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "be_stats_version": __version__,
        "git": {"sha": _git_sha(), "working_tree_dirty": _git_dirty()},
        "software_versions": _software_versions(),
        "environment": _environment(),
        "test_summary": _test_summary(junit_xml),
        "capability_matrix": [
            {
                **_plain(record),
                "implementation_status": str(record.implementation_status),
                "validation_status": str(record.validation_status),
            }
            for record in CAPABILITY_MATRIX.values()
        ],
        "method_catalogue": [_plain(entry) for entry in method_catalogue()],
        "routing_matrix": [
            _plain(route) for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION)
        ],
        "refusal_semantics": [_plain(reason) for reason in REFUSALS.values()],
        "evidence_manifest": [_plain(record) for record in EVIDENCE_MANIFEST],
        "provenance": {
            "coverage": provenance_coverage(),
            "constants": [_plain(record) for record in CONSTANT_INDEX.values()],
        },
        "findings": [_plain(finding) for finding in FINDINGS_REGISTER],
        "blockers": {
            "partial_oracle_ready": PARTIAL_ORACLE_READY,
            "real_sas_oracle_status": REAL_SAS_ORACLE_STATUS,
            "records": [_plain(blocker) for blocker in BLOCKERS.values()],
        },
        "release_gate": {
            "passed": gate.passed,
            "results": [_plain(result) for result in gate.results],
        },
        "certification_blockers": certification_blockers(),
    }
