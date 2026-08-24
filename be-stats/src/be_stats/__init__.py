"""be-stats — bioequivalence statistics.

Deliberately free of any web, database or LLM import. The engine computes; the
platform decides what to do with the result. That separation is what lets this
package be versioned and qualified on its own cadence, so that a change to the
application it serves is not a change to a validated system.

STATUS: development. Not qualified for use in a regulatory submission. See
`validation/README.md` for what would have to be true first.
"""

from be_stats.abe import (
    AbeResult,
    analyse_crossover,
    analyse_parallel,
    tost_p_values,
)
from be_stats.power import (
    PowerResult,
    SampleSizeResult,
    power_abe,
    sample_size_abe,
)
from be_stats.profiles import (
    EMA,
    FDA,
    AcceptanceInterval,
    DrugClass,
    NotApplicable,
    Regulator,
    RegulatoryProfile,
    profile_for,
)
from be_stats.study import (
    CrossoverObservation,
    CrossoverStudy,
    DataError,
    ParallelStudy,
    Sequence,
    Treatment,
)

#: Bumped on any change that can alter a computed result. An analysis record
#: stores this, because "which version produced this number" is the first
#: question asked of a result years later.
__version__ = "0.1.0"

__all__ = [
    "AbeResult",
    "AcceptanceInterval",
    "CrossoverObservation",
    "CrossoverStudy",
    "DataError",
    "DrugClass",
    "EMA",
    "FDA",
    "NotApplicable",
    "ParallelStudy",
    "PowerResult",
    "Regulator",
    "RegulatoryProfile",
    "SampleSizeResult",
    "Sequence",
    "Treatment",
    "__version__",
    "analyse_crossover",
    "analyse_parallel",
    "power_abe",
    "profile_for",
    "sample_size_abe",
    "tost_p_values",
]
