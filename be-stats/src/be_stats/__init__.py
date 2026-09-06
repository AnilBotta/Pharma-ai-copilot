"""be-stats - bioequivalence statistics.

Deliberately free of any web, database or LLM import. The engine computes; the
platform decides what to do with the result. That separation is what lets this
package be versioned and qualified on its own cadence, so a change to the
application it serves is not a change to a validated system.

The entry point is `resolve_be_spec`, not an estimator: which test applies is a
regulatory question that must be settled before any arithmetic happens, and for
several jurisdiction/class combinations the answer changes the procedure rather
than the limits.

Measuring and deciding are also separated. The replicate layer estimates sWR
and CVwR and stops; it cannot see the FDA switching rule, and a test enforces
that. The decision lives in `hvd.py`, which reads the same quantities from the
outside. A quantity should be checkable before anything depends on it.

STATUS: development. Not qualified for use in a regulatory submission. See
`validation/README.md` for what would have to be true first.
"""

from be_stats.abe import (
    AbeResult,
    abe_from_log_contrast,
    analyse_crossover,
    analyse_parallel,
    tost_p_values,
)
from be_stats.appendix_c import (
    AppendixCDataset,
    AppendixCNotSupported,
    AppendixCObservation,
    ReplicateAbeFit,
    ReplicateAbeResult,
    analyse_replicate_abe_full,
    fit_appendix_c,
)

# NOTE: `appendix_c.satterthwaite_df` is deliberately NOT re-exported here.
#
# `treatment_contrast.satterthwaite_df` already occupies that name at package
# level, and the two are DIFFERENT FUNCTIONS for different models: Appendix G's
# collapses a single variance component on the Iij contrast, while Appendix C's
# takes the fitted five-parameter covariance and the REML information matrix.
# Importing both here made the second silently shadow the first.
#
# Two functions called `satterthwaite_df` that compute different things is
# precisely the confusion PR #61 measured the cost of - lmerTest's correct
# Satterthwaite on the wrong model was out by a factor of 1.8. Reach Appendix
# C's through its module: `from be_stats.appendix_c import satterthwaite_df`.
from be_stats.hvd import (
    FdaHvdResult,
    NotDecidable,
    PointEstimateConstraint,
    RsabeResult,
    ScaledCriterion,
    assess_endpoint,
    assess_study,
    point_estimate_constraint,
    scaled_criterion,
)
from be_stats.ema_hvd import (
    AbelLimits,
    EmaHighlyVariableResult,
    EmaObservation,
    EmaReplicateDataset,
    ReferenceVariability,
    TreatmentEffect,
    assess_ema_endpoint,
    assess_ema_study,
    ema_abel_limits,
    ema_design_support,
    estimate_reference_variability,
    estimate_treatment_effect,
)
from be_stats.howe import HoweUpperBound, howe_upper_bound
from be_stats.linear_model import LeastSquaresFit, fit_least_squares
from be_stats.nti import (
    FdaNtiResult,
    NtiDesignError,
    NtiScaledMeanCriterion,
    NtiUnscaledAbeCriterion,
    NtiVariabilityRatioCriterion,
    WithinTestVarianceResult,
    assess_nti_endpoint,
    assess_nti_study,
    estimate_test_variance,
    require_fully_replicate,
    scaled_mean_criterion,
    variability_ratio_criterion,
)
from be_stats.replicate_abe import (
    APPENDIX_C_MODEL,
    ReplicateAbeModelSpecification,
    analyse_replicate_abe,
)
from be_stats.treatment_contrast import (
    FullyReplicateTreatmentContrastEstimator,
    PartialReplicateTreatmentContrastEstimator,
    TreatmentContrastResult,
    contrast_estimator_for,
    estimate_treatment_contrast,
    satterthwaite_df,
    subject_weighted_mean,
)
from be_stats.power import (
    NotPowerable,
    PowerResult,
    SampleSizeResult,
    power_abe,
    sample_size_abe,
)
from be_stats.conversions import (
    cv_to_log_sd,
    log_sd_to_cv,
)
from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.minimums import (
    DesignFamily,
    Framework,
    MinimumApplicability,
    MinimumOutcome,
    RegulatoryMinimum,
    StudyRole,
)
from be_stats.reference_variance import (
    FullyReplicateReferenceVarianceEstimator,
    NotEstimable,
    PartialReplicateReferenceVarianceEstimator,
    ReferenceVarianceResult,
    estimate_reference_variance,
    estimator_for,
    sequence_mean_differences,
)
from be_stats.replicate import (
    ReplicateDataset,
    ReplicateDesign,
    ReplicateObservation,
    ReplicateSequence,
    SubjectRecord,
    UnsupportedDesign,
    identify_design,
    parse_sequence,
    parse_treatment,
    reference_differences,
    test_differences,
    treatment_contrasts,
)
from be_stats.provenance import (
    Citation,
    RegulatoryValue,
    ValidationStatus,
    VerificationStatus,
)
from be_stats.spec import (
    CAPABILITY_VALIDATION,
    EMA_ABEL_SCALABLE_ENDPOINTS,
    EMA_HVD_CONSTANTS,
    FDA_HVD_CONSTANTS,
    FDA_IVPT_NOTE,
    FDA_NTI_CONSTANTS,
    FDA_NTI_SAS_EXAMPLE_DELTA,
    IMPLEMENTED,
    VALIDATION,
    Capability,
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
    ema_abel_cap_computed,
    ema_hvd_scaling_eligible,
    fda_hvd_method_for,
    fda_hvd_theta,
    fda_nti_theta,
    fda_nti_theta_sas_example,
    resolve_be_spec,
    validation_report,
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
__version__ = "0.7.0"

__all__ = [
    "APPENDIX_C_MODEL",
    "AbeResult",
    "AbelLimits",
    "AcceptanceInterval",
    "AppendixCDataset",
    "AppendixCNotSupported",
    "AppendixCObservation",
    "BeSpec",
    "CAPABILITY_VALIDATION",
    "Capability",
    "Citation",
    "CrossoverObservation",
    "CrossoverStudy",
    "DataError",
    "DesignFamily",
    "Diagnostic",
    "DiagnosticCode",
    "DrugClass",
    "EMA_ABEL_SCALABLE_ENDPOINTS",
    "EMA_HVD_CONSTANTS",
    "EmaHighlyVariableResult",
    "EmaObservation",
    "EmaReplicateDataset",
    "Endpoint",
    "FDA_HVD_CONSTANTS",
    "FDA_IVPT_NOTE",
    "FDA_NTI_CONSTANTS",
    "FDA_NTI_SAS_EXAMPLE_DELTA",
    "FdaHvdResult",
    "FdaNtiResult",
    "Framework",
    "FullyReplicateReferenceVarianceEstimator",
    "FullyReplicateTreatmentContrastEstimator",
    "HoweUpperBound",
    "IMPLEMENTED",
    "Jurisdiction",
    "LeastSquaresFit",
    "Method",
    "NotApplicable",
    "NotDecidable",
    "NotEstimable",
    "NotImplementedMethod",
    "NotPowerable",
    "NotValidated",
    "NtiDesignError",
    "NtiScaledMeanCriterion",
    "NtiUnscaledAbeCriterion",
    "NtiVariabilityRatioCriterion",
    "ParallelStudy",
    "PartialReplicateReferenceVarianceEstimator",
    "PartialReplicateTreatmentContrastEstimator",
    "PointEstimateConstraint",
    "PowerResult",
    "ProductOverride",
    "ReferenceVariability",
    "ReferenceVarianceResult",
    "MinimumApplicability",
    "MinimumOutcome",
    "RegulatoryMinimum",
    "StudyRole",
    "RegulatoryValue",
    "ReplicateAbeFit",
    "ReplicateAbeModelSpecification",
    "ReplicateAbeResult",
    "ReplicateDataset",
    "ReplicateDesign",
    "ReplicateObservation",
    "ReplicateSequence",
    "RsabeResult",
    "SampleSizeResult",
    "ScaledCriterion",
    "Sequence",
    "Severity",
    "SpecificationRequired",
    "SubjectRecord",
    "Treatment",
    "TreatmentContrastResult",
    "TreatmentEffect",
    "UnsupportedDesign",
    "VALIDATION",
    "ValidationStatus",
    "VerificationStatus",
    "WithinTestVarianceResult",
    "__version__",
    "abe_from_log_contrast",
    "analyse_crossover",
    "analyse_parallel",
    "analyse_replicate_abe",
    "analyse_replicate_abe_full",
    "assess_ema_endpoint",
    "assess_ema_study",
    "assess_endpoint",
    "assess_nti_endpoint",
    "assess_nti_study",
    "assess_study",
    "contrast_estimator_for",
    "cv_to_log_sd",
    "ema_abel_cap_computed",
    "ema_abel_limits",
    "ema_design_support",
    "ema_hvd_scaling_eligible",
    "estimate_reference_variability",
    "estimate_reference_variance",
    "estimate_test_variance",
    "estimate_treatment_contrast",
    "estimate_treatment_effect",
    "estimator_for",
    "fda_hvd_method_for",
    "fda_hvd_theta",
    "fda_nti_theta",
    "fda_nti_theta_sas_example",
    "fit_appendix_c",
    "fit_least_squares",
    "howe_upper_bound",
    "identify_design",
    "log_sd_to_cv",
    "parse_sequence",
    "parse_treatment",
    "point_estimate_constraint",
    "power_abe",
    "reference_differences",
    "require_fully_replicate",
    "resolve_be_spec",
    "sample_size_abe",
    "satterthwaite_df",
    "scaled_criterion",
    "scaled_mean_criterion",
    "sequence_mean_differences",
    "subject_weighted_mean",
    "test_differences",
    "tost_p_values",
    "treatment_contrasts",
    "validation_report",
    "variability_ratio_criterion",
]
