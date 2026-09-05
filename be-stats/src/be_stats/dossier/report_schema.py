"""The report's SHAPE, as a committed fixture that cannot go stale silently.

WHY A SCHEMA SNAPSHOT AND NOT A REPORT SNAPSHOT

A committed example report would be ~70KB that changes whenever any status,
finding or constant changes - which is often, and every one of those changes is
already asserted by a test that says what it means. The diff would be noise,
and noise is what people learn to approve without reading.

What a CONSUMER actually depends on is the shape: which sections exist, which
fields each row carries, and what type each field is. That changes rarely, and
when it changes somebody outside this repository has to be told. So the fixture
is the shape with the values elided, regenerated and compared in CI.

`REPORT_SCHEMA` is the version a consumer branches on. This module is what
makes forgetting to bump it a build failure rather than a support ticket.
"""

from __future__ import annotations

from typing import Any

from be_stats.dossier.report import Audience, build_validation_report

#: A stand-in for any scalar. The fixture records TYPES, not values.
_SCALARS = {
    str: "str",
    bool: "bool",
    int: "int",
    float: "float",
    type(None): "null",
}


def _merge(shapes: list[Any]) -> Any:
    """One shape describing every element of a list.

    Taking the FIRST element's shape looked simpler and was wrong: the first
    capability in the matrix happens to have no blockers, so the fixture
    recorded `"blockers": []` and would not have noticed a change to the
    blocker row's fields. Merging the keys across every element records the
    shape the list can actually hold.
    """
    if not shapes:
        return []
    if all(isinstance(shape, dict) for shape in shapes):
        merged: dict[str, Any] = {}
        for shape in shapes:
            for key, value in shape.items():
                if key not in merged or merged[key] in ([], "null"):
                    merged[key] = value
        return [dict(sorted(merged.items()))]
    if all(isinstance(shape, list) for shape in shapes):
        return [_merge([item for shape in shapes for item in shape])]
    # Mixed or scalar: the distinct type names, so a list that holds two
    # different things says so rather than picking one.
    distinct = sorted({str(shape) for shape in shapes})
    return [distinct[0]] if len(distinct) == 1 else [distinct]


def _shape(node: Any) -> Any:
    """The structure of a value, with every scalar replaced by its type name."""
    if isinstance(node, dict):
        return {key: _shape(value) for key, value in sorted(node.items())}
    if isinstance(node, list):
        return _merge([_shape(item) for item in node])
    return _SCALARS.get(type(node), type(node).__name__)


def report_shape() -> dict[str, Any]:
    """The current report's shape, for comparison against the fixture."""
    report = build_validation_report(
        audience=Audience.REVIEWER,
        git_sha="fixture",
        generated_at="1970-01-01T00:00:00+00:00",
    )
    return _shape(report.to_dict())
