"""be-stats - bioequivalence statistics.

Deliberately free of any web, database or LLM import. The engine computes; the
platform decides what to do with the result. That separation is what lets this
package be versioned and qualified on its own cadence, so a change to the
application it serves is not a change to a validated system.

The entry point is `resolve_be_spec`, not an estimator: which test applies is a
regulatory question that must be settled before any arithmetic happens, and for
several jurisdiction/class combinations the answer changes the procedure rather
than the limits.

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
    NotPowerable,
    PowerResult,
    SampleSizeResult,
    power_abe,
    sample_size_abe,
)
from be_stats.conversions import (
    HVD_CV_THRESHOLD,
    HVD_SWR_THRESHOLD,
    cv_to_log_sd,
    log_sd_to_cv,
)
from be_stats.minimums import DesignFamily, RegulatoryMinimum
from be_stats.provenance import (
    Citation,
    RegulatoryValue,
    ValidationStatus,
    VerificationStatus,
)
from be_stats.spec import (
    IMPLEMENTED,
    VALIDATION,
    NotValidated,
    AcceptanceInterval,
    BeSpec,
    DrugClass,
    Endpoint,
    Jurisdiction,
    Method,
    NotApplicable,
    NotImplementedMethod,
    ProductOverride,
    SpecificationRequired,
    resolve_be_spec,
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
    "Citation",
    "DesignFamily",
    "HVD_CV_THRESHOLD",
    "HVD_SWR_THRESHOLD",
    "NotValidated",
    "RegulatoryMinimum",
    "RegulatoryValue",
    "VALIDATION",
    "ValidationStatus",
    "VerificationStatus",
    "cv_to_log_sd",
    "log_sd_to_cv",
    "AcceptanceInterval",
    "BeSpec",
    "CrossoverObservation",
    "CrossoverStudy",
    "DataError",
    "DrugClass",
    "Endpoint",
    "IMPLEMENTED",
    "Jurisdiction",
    "Method",
    "NotApplicable",
    "NotImplementedMethod",
    "NotPowerable",
    "ParallelStudy",
    "PowerResult",
    "ProductOverride",
    "SampleSizeResult",
    "Sequence",
    "SpecificationRequired",
    "Treatment",
    "__version__",
    "analyse_crossover",
    "analyse_parallel",
    "power_abe",
    "resolve_be_spec",
    "sample_size_abe",
    "tost_p_values",
]