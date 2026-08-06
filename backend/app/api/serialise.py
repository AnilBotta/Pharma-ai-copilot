"""Row serialisation shared by the research and PDP routers.

asyncpg returns driver-native types - UUID, Decimal, date - that Pydantic and
JSON handle inconsistently. Normalising in one place keeps the two routers from
drifting into different conventions for the same value.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

#: Columns the research module stores as JSON text rather than jsonb, and which
#: therefore arrive as strings. Decoded here so the API shape does not depend on
#: which storage type a column happens to use.
_JSON_TEXT_COLUMNS = frozenset({
    "structured_objective", "research_plan", "contradictions",
    "evidence_gaps", "warnings", "section_confidence", "data",
})


def serialise(row: Any) -> dict:
    """Convert one database row into JSON-friendly Python values."""
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, str) and key in _JSON_TEXT_COLUMNS:
            try:
                result[key] = json.loads(value)
            except (ValueError, TypeError):
                result[key] = value
        else:
            result[key] = value
    return result


def jsonable(value: Any) -> Any:
    """Recursively convert a value for storage in a jsonb audit column.

    Audit payloads are assembled from database rows, so they carry the same
    driver-native types. A UUID or date left in place raises at insert time,
    which would mean losing the audit entry for a change that did happen.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
