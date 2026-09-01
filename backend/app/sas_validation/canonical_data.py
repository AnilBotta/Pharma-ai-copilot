"""The approved dataset for a predefined validation case, loaded server-side.

WHY THE BROWSER MAY NOT SUPPLY THIS

`FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II` exists to settle a regulatory question
about a SPECIFIC published dataset: EMA/618604/2008 Rev. 13, Data set II. A
package built from anything else answers a different question while carrying
the same case id, and the comparison against EMA's published interval becomes
meaningless.

So the package endpoint takes a case id and nothing else. It does not accept
observations, a dataset file, SAS code, model text, an expected denominator df
or a package hash. The server loads the approved data itself, from the copy
that lives in the be-stats validation corpus and has been in the repository
since PR #60.

That corpus is the same file the statistical work has used throughout, so the
package a customer runs and the analyses already recorded in the findings are
demonstrably about the same numbers.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

#: EMA prints Data set II's sequences as 1/2/3. The letters are what the
#: design actually is, and getting this mapping wrong would silently analyse a
#: different design - so it is written once, here, and not re-derived.
SEQUENCE_CODES = {"1": "TRR", "2": "RTR", "3": "RRT"}

#: Where the approved corpus lives. Resolved relative to this file so it does
#: not depend on the working directory a server happens to start in.
_CORPUS = (
    Path(__file__).resolve().parents[3]
    / "be-stats"
    / "validation"
    / "ema"
    / "cases"
    / "ema_pkwp_qa_datasets.json"
)

#: case id -> key within the corpus.
CANONICAL_DATASETS: dict[str, str] = {
    "FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II": "data_set_ii",
}


class CanonicalDatasetUnavailable(RuntimeError):
    """The approved data could not be loaded.

    Fatal for package generation. Falling back to anything else would produce a
    package that claims to be about EMA Data set II and is not.
    """


@lru_cache(maxsize=4)
def _corpus() -> dict[str, Any]:
    try:
        return json.loads(_CORPUS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CanonicalDatasetUnavailable(
            f"could not read the approved validation corpus at {_CORPUS}: {error}"
        ) from error


def load_canonical_observations(case_id: str) -> list[dict[str, object]]:
    """The approved observations for a predefined case.

    Returns them in the shape `build_package` expects. Nothing here is
    configurable and no argument other than the case id is accepted.
    """
    try:
        key = CANONICAL_DATASETS[case_id]
    except KeyError:
        raise CanonicalDatasetUnavailable(
            f"{case_id!r} has no approved dataset. Packages are only generated "
            f"for predefined cases: {sorted(CANONICAL_DATASETS)}"
        ) from None

    rows = _corpus().get(key)
    if not rows:
        raise CanonicalDatasetUnavailable(
            f"the approved corpus contains no rows under {key!r}"
        )

    observations: list[dict[str, object]] = []
    for row in rows:
        sequence = SEQUENCE_CODES.get(str(row["sequence"]))
        if sequence is None:
            raise CanonicalDatasetUnavailable(
                f"unrecognised sequence code {row['sequence']!r} in {key}"
            )
        observations.append(
            {
                "subject": str(row["subject"]),
                "sequence": sequence,
                "period": int(row["period"]),
                "treatment": str(row["formulation"]).strip().upper(),
                "value": float(row["value"]),
            }
        )
    return observations


__all__ = [
    "CANONICAL_DATASETS",
    "SEQUENCE_CODES",
    "CanonicalDatasetUnavailable",
    "load_canonical_observations",
]
