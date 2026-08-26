"""Appendix C: average bioequivalence for replicate crossover studies.

NOT IMPLEMENTED. THIS MODULE IS THE SPECIFICATION AND THE REFUSAL.

WHY THERE IS A MODULE AT ALL FOR SOMETHING THAT DOES NOT RUN

Two reasons. The refusal needs a precise reason - "not implemented" is not
useful to someone holding a replicate study whose sWR came out at 0.21. And
everything below was read out of the guidance; recording it here means the next
implementer starts from the model rather than from the appendix.

WHAT FDA SPECIFIES

Appendix C gives the average-BE analysis for replicate crossover studies as a
mixed model on the ORIGINAL subject-period observations:

    PROC MIXED;
    CLASSES SEQ SUBJ PER TRT;
    MODEL Y = SEQ PER TRT / DDFM=SATTERTH;
    RANDOM TRT / TYPE=FA0(2) SUB=SUBJ G;
    REPEATED / GRP=TRT SUB=SUBJ;
    ESTIMATE 'T vs. R' TRT 1 -1 / CL ALPHA=0.1;

Read term by term:

    MODEL Y = SEQ PER TRT
        Fixed effects on the log-transformed observation: sequence, period and
        treatment. Note PERIOD - the Appendix G intermediates `Iij` and `Dij`
        absorb period within a subject and never estimate it.

    RANDOM TRT / TYPE=FA0(2) SUB=SUBJ
        Subject-level random effects for T and R with an UNSTRUCTURED 2x2
        covariance, parameterised through its Cholesky factor. Three
        parameters. This is the subject-by-formulation interaction: the
        possibility that a subject's response to T is not simply their response
        to R shifted by a constant.

    REPEATED / GRP=TRT SUB=SUBJ
        SEPARATE residual variances for T and R. Two more parameters. This is
        what lets within-test and within-reference variability differ, which
        for a highly variable drug is the normal case rather than the exception.

    DDFM=SATTERTH
        Satterthwaite denominator degrees of freedom for the T-R contrast,
        computed from FIVE covariance parameters and their estimated
        asymptotic covariance.

    ALPHA=0.1
        A two-sided 90% interval - the two one-sided tests at 5% each.

WHY IT IS NOT IMPLEMENTED HERE

This package depends on scipy and numpy. Fitting the model above means writing,
from scratch: the block-diagonal covariance per subject, a REML objective over
five parameters, an optimiser that respects the boundary behaviour of a
factor-analytic structure, the asymptotic covariance of the variance-component
estimates, and a Satterthwaite calculation from the gradient of the contrast
variance with respect to all five.

That is a substantial numerical component, and - decisively - **there is no
oracle available here to check it against**. No SAS, no R, no statsmodels.
Even statsmodels' `MixedLM` could not do it: it supports neither
group-specific residual variances nor Satterthwaite degrees of freedom.

An unverifiable mixed model does not fail loudly. It converges, and returns a
confidence interval of entirely plausible width, which is then compared against
80.00-125.00% and becomes a bioequivalence verdict. That is the largest version
of the failure this package exists to avoid.

WHAT MUST NOT BE SUBSTITUTED

Appendix G's `Iij` contrast. It is the right quantity for the reference-scaled
construction - FDA forms `x` and `bound_x` from exactly it - and it is a
different model from this one: no period term, one residual variance rather
than two, no subject-by-formulation covariance. Using it for the unscaled
branch means answering FDA's question with someone else's model, and the answer
looks the same either way.

MISSING DATA, WHEN THIS IS IMPLEMENTED

The guidance's missing-data discussion notes that a mixed model can use the
observations actually recorded rather than deleting any subject with an
incomplete period history. So the subject set for this model is NOT required to
match the one used for `Iij`, and an implementation must report the subjects and
observations each model actually used rather than assuming one number covers
both. `Iij` needs a complete subject; this model does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from be_stats.diagnostics import Diagnostic, DiagnosticCode, Severity
from be_stats.provenance import (
    Citation,
    ValidationStatus,
    VIA_PRIMARY_DOCUMENT,
)
from be_stats.replicate import ReplicateDataset

FDA_STATISTICAL_APPROACHES_APPENDIX_C = Citation(
    authority="FDA",
    document="Statistical Approaches to Establishing Bioequivalence",
    section="Appendix C (SAS statements for average BE analysis of replicate crossover studies)",
    document_version="final, May 2026",
    url="https://www.fda.gov/media/163638/download",
)


@dataclass(frozen=True, slots=True)
class ReplicateAbeModelSpecification:
    """What has to be fitted, in a form a reviewer can check against the SAS.

    Data rather than prose so a future implementation can assert it satisfies
    each element, and so a test can assert the specification has not quietly
    been trimmed to whatever got built.
    """

    fixed_effects: tuple[str, ...] = ("sequence", "period", "treatment")
    #: Subject-level random effects for T and R, unstructured 2x2.
    random_effects: str = "TRT / TYPE=FA0(2) SUB=SUBJ"
    #: Treatment-specific residual variances.
    repeated: str = "GRP=TRT SUB=SUBJ"
    denominator_df: str = "Satterthwaite, from all five covariance parameters"
    contrast: str = "TRT 1 -1"
    alpha: float = 0.10
    #: Fitted on the original subject-period observations - NOT on Iij or Dij.
    operates_on: str = "subject-period log observations"
    n_covariance_parameters: int = 5
    citation: Citation = FDA_STATISTICAL_APPROACHES_APPENDIX_C
    verified_by: str = VIA_PRIMARY_DOCUMENT

    def explain(self) -> list[str]:
        return [
            f"fixed effects: {', '.join(self.fixed_effects)}",
            f"random: {self.random_effects}",
            f"repeated: {self.repeated}",
            f"denominator df: {self.denominator_df}",
            f"contrast: {self.contrast} at alpha={self.alpha}",
            f"operates on: {self.operates_on}",
            f"{self.citation} [verified, via {self.verified_by}]",
        ]


APPENDIX_C_MODEL = ReplicateAbeModelSpecification()

#: Tracked so nothing can read this module as merely unfinished plumbing.
VALIDATION_STATUS = ValidationStatus.NOT_IMPLEMENTED

_REASON = (
    "FDA Appendix C specifies the unscaled average BE analysis for a replicate "
    "crossover study as a mixed model on the subject-period observations - "
    "fixed effects for sequence, period and treatment; an unstructured 2x2 "
    "subject-by-formulation covariance (RANDOM TRT/TYPE=FA0(2) SUB=SUBJ); "
    "treatment-specific residual variances (REPEATED/GRP=TRT SUB=SUBJ); and "
    "Satterthwaite denominator degrees of freedom from all five covariance "
    "parameters. This package has scipy and numpy, no mixed-model fitter that "
    "supports group-specific residual variances or Satterthwaite degrees of "
    "freedom, and no independent implementation available to check a "
    "from-scratch REML fit against. Appendix G's Iij contrast is a DIFFERENT "
    "model - no period term, one residual variance, no subject-by-formulation "
    "covariance - and substituting it would answer this question with another "
    "model's arithmetic while looking exactly the same. So this refuses."
)


def replicate_abe_unavailable(dataset: ReplicateDataset) -> Diagnostic:
    """The refusal, as a diagnostic a result can carry."""
    return Diagnostic(
        DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED,
        Severity.FATAL,
        None,
        _REASON,
        {
            "design": str(dataset.design),
            "endpoint": dataset.endpoint,
            "subjects_available": len(dataset.records),
            "required_model": APPENDIX_C_MODEL.explain(),
        },
    )


def analyse_replicate_abe(dataset: ReplicateDataset):
    """Not implemented. Raises, with the model it would have to fit.

    Present so the gap has a name and a call site. When Appendix C is
    implemented, this is where it goes - and it must produce a log contrast, a
    standard error and denominator degrees of freedom, then hand them to
    `abe.abe_from_log_contrast` rather than forming an interval of its own.
    """
    from be_stats.spec import NotImplementedMethod

    raise NotImplementedMethod(_REASON)
