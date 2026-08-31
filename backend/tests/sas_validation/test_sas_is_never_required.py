"""SAS must never be on the path of a normal calculation.

THE PROPERTY THIS PROTECTS

A customer with no SAS - which today is every customer - must be able to use
every supported calculation. SAS validation is a service layered BESIDE the
engine, and the moment any calculation path consults a SAS setting, that stops
being true and nobody notices until someone without an integration gets an
error.

The check is structural rather than behavioural on purpose. A test that called
a few calculations and observed they worked would pass just as well if the code
consulted SAS settings and happened to find a default. Reading the import graph
answers the stronger question: could it?
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
BE_STATS_SRC = BACKEND.parent / "be-stats" / "src" / "be_stats"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_engine_never_imports_the_sas_layer():
    """be-stats is the calculator of record and must not know this exists.

    The dependency runs one way: the product layer imports the engine for the
    qualified Appendix C model statements. If it ever ran the other way, the
    engine could not be versioned and qualified on its own cadence - a change
    to the application would become a change to a validated system.
    """
    offenders = []
    for module in sorted(BE_STATS_SRC.glob("*.py")):
        for imported in imported_modules(module):
            if "sas" in imported.lower() or imported.startswith("app."):
                offenders.append(f"{module.name} imports {imported}")
    assert not offenders, offenders


@pytest.mark.parametrize(
    "module_name",
    [
        "abe.py",
        "hvd.py",
        "nti.py",
        "ema_hvd.py",
        "appendix_c.py",
        "power.py",
        "spec.py",
    ],
)
def test_no_supported_calculation_module_mentions_sas_settings(module_name: str):
    """The calculation modules may mention SAS - they must not consult it.

    `appendix_c.py` and `replicate_abe.py` legitimately quote FDA's SAS
    statements, because that is the model they implement. What none of them may
    do is read an integration, a credential, a mode or a feature flag: that
    would make a regulatory result depend on a customer's procurement.
    """
    source = (BE_STATS_SRC / module_name).read_text(encoding="utf-8")
    forbidden = (
        "sas_validation",
        "SASIntegration",
        "sas_integration",
        "provider_for",
        "validation_package",
    )
    for token in forbidden:
        assert token not in source, f"{module_name} references {token}"


def test_the_sas_layer_does_not_reach_into_calculation():
    """It reads the model SPECIFICATION and computes nothing itself.

    `replicate_abe.APPENDIX_C_MODEL` is a declarative record with a citation.
    Importing an estimator instead would put a second calculation path in the
    product layer, and a validation service that computes its own answer is not
    validating anything.
    """
    allowed = {"be_stats.replicate_abe"}
    package = BACKEND / "app" / "sas_validation"
    for module in sorted(package.glob("*.py")):
        for imported in imported_modules(module):
            if imported.startswith("be_stats"):
                assert imported in allowed, (
                    f"{module.name} imports {imported}; the SAS layer may read "
                    f"the model specification and nothing else. Allowed: {allowed}"
                )


def test_the_engine_still_computes_with_no_integration_present():
    """The behavioural counterpart, kept small.

    Structure says SAS cannot be consulted. This says a real calculation runs
    in a process where the SAS layer was never imported at all.
    """
    import sys

    for name in [n for n in sys.modules if n.startswith("app.sas_validation")]:
        del sys.modules[name]

    from be_stats import (
        CrossoverObservation,
        CrossoverStudy,
        Jurisdiction,
        Sequence,
        analyse_crossover,
        resolve_be_spec,
    )

    study = CrossoverStudy(
        endpoint="AUC",
        observations=[
            CrossoverObservation("A1", Sequence.RT, 100.0, 105.0),
            CrossoverObservation("A2", Sequence.RT, 90.0, 88.0),
            CrossoverObservation("B1", Sequence.TR, 102.0, 98.0),
            CrossoverObservation("B2", Sequence.TR, 115.0, 108.0),
        ],
    )
    result = analyse_crossover(study, resolve_be_spec(jurisdiction=Jurisdiction.FDA))

    assert result.point_estimate > 0
    assert not any(n.startswith("app.sas_validation") for n in sys.modules)
