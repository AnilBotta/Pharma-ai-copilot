"""Resolving which test applies, before any arithmetic.

These assertions encode the statistical specification agreed at review. They
are about *routing*, not about numbers: which method, which design, and where
the engine must refuse instead of guessing.
"""

from __future__ import annotations

import pytest

from be_stats import (
    DrugClass,
    Endpoint,
    Jurisdiction,
    Method,
    NotImplementedMethod,
    ProductOverride,
    SpecificationRequired,
    resolve_be_spec,
)


def test_standard_is_the_same_interval_in_both_jurisdictions():
    for jur in (Jurisdiction.FDA, Jurisdiction.EMA):
        spec = resolve_be_spec(jurisdiction=jur)
        assert spec.method is Method.STANDARD_ABE
        assert (spec.acceptance.lower_value, spec.acceptance.upper_value) == (80.00, 125.00)
        assert spec.is_implemented


def test_ema_nti_auc_narrows():
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    assert spec.method is Method.EMA_NTI_NARROW_ABE
    assert (spec.acceptance.lower_value, spec.acceptance.upper_value) == (90.00, 111.11)
    assert spec.is_implemented


def test_ema_nti_cmax_refuses_to_guess():
    """The correction that mattered most from statistical review.

    EMA narrows Cmax for an NTI drug only when Cmax is itself important for
    safety or efficacy, and that is decided per product - ciclosporin narrows
    both, colchicine narrows AUC and leaves Cmax at 80.00-125.00. Defaulting
    either way would be right for one of those and wrong for the other, so the
    engine asks.
    """
    with pytest.raises(SpecificationRequired, match="per product"):
        resolve_be_spec(
            jurisdiction=Jurisdiction.EMA,
            drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
            endpoint=Endpoint.CMAX,
        )


def test_product_guidance_supplies_the_cmax_answer_either_way():
    """Both real patterns must be expressible, because both exist."""
    narrowed_both = ProductOverride(
        product="ciclosporin",
        limits={Endpoint.AUC: (90.00, 111.11), Endpoint.CMAX: (90.00, 111.11)},
        citation="EMA Q&A",
    )
    auc_only = ProductOverride(
        product="colchicine",
        limits={Endpoint.AUC: (90.00, 111.11), Endpoint.CMAX: (80.00, 125.00)},
        citation="EMA product-specific guidance",
    )

    a = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.CMAX,
        product=narrowed_both,
    )
    b = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.CMAX,
        product=auc_only,
    )
    assert (a.acceptance.lower_value, a.acceptance.upper_value) == (90.00, 111.11)
    assert (b.acceptance.lower_value, b.acceptance.upper_value) == (80.00, 125.00)
    assert "ciclosporin" in a.acceptance.basis
    assert "colchicine" in b.acceptance.basis


def test_product_guidance_outranks_the_jurisdiction_default():
    override = ProductOverride(
        product="example", limits={Endpoint.AUC: (85.00, 117.65)}
    )
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA, endpoint=Endpoint.AUC, product=override
    )
    assert (spec.acceptance.lower_value, spec.acceptance.upper_value) == (85.00, 117.65)


def test_fda_nti_resolves_to_rsabe_and_refuses_to_run():
    """FDA does not narrow limits for an NTI drug - it changes the test."""
    spec = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
    )
    assert spec.method is Method.FDA_NTI_RSABE
    assert spec.acceptance is None
    assert spec.required_design == "fully replicated crossover"
    assert spec.constants["sigma_w0"].value == 0.10
    assert spec.constants["variance_ratio_upper_limit"].value == 2.5
    assert spec.constants["delta"].value == pytest.approx(1.0 / 0.9)
    assert not spec.is_implemented

    with pytest.raises(NotImplementedMethod, match="fully replicated"):
        spec.require_implemented()


def test_fda_and_ema_take_different_routes_for_highly_variable_drugs():
    """Never a generic HVD method: RSABE and ABEL are different procedures."""
    fda = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    ema = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    assert fda.method is Method.FDA_HVD_RSABE
    assert ema.method is Method.EMA_HVD_ABEL
    assert fda.method is not ema.method
    assert fda.constants["sigma_w0"].value == 0.25
    assert fda.constants["swr_switching_threshold"].value == 0.294

    # Both are implemented now, and the constants they resolve to are what
    # proves they did not converge into one method. EMA carries a regulatory
    # constant k and a cap; FDA carries sigma_w0 and a switching threshold.
    # Neither table contains the other's keys.
    assert ema.constants["regulatory_constant_k"].value == 0.760
    assert ema.constants["cap_upper_percent"].value == 143.19
    assert "sigma_w0" not in ema.constants
    assert "regulatory_constant_k" not in fda.constants

    assert fda.is_implemented
    fda.require_implemented()
    assert ema.is_implemented
    ema.require_implemented()


def test_an_implemented_hvd_method_still_has_no_fixed_acceptance_interval():
    """Implementing RSABE does not give it an interval to contain a CI in.

    The acceptance region moves with the reference variability, so asking a
    highly-variable spec for limits is asking the wrong question - and it stays
    a refusal now that the method runs. `require_implemented` and
    `require_interval` answer different questions and must not be conflated.
    """
    from be_stats.spec import NotApplicable

    fda = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    assert fda.is_implemented
    with pytest.raises(NotApplicable, match="fixed acceptance interval"):
        fda.require_interval()


def test_unimplemented_methods_are_not_in_the_implemented_set():
    from be_stats import IMPLEMENTED

    assert Method.STANDARD_ABE in IMPLEMENTED
    assert Method.EMA_NTI_NARROW_ABE in IMPLEMENTED
    assert Method.FDA_HVD_RSABE in IMPLEMENTED

    assert Method.EMA_HVD_ABEL in IMPLEMENTED

    # FDA's NTI route remains a separate procedure with its own constants and
    # its own criteria, and neither of the highly-variable implementations
    # generalised into it.
    assert Method.FDA_NTI_RSABE not in IMPLEMENTED


def test_implementing_hvd_did_not_turn_nti_into_a_configuration_flag():
    """The scope line for the next release, asserted rather than intended.

    FDA NTI shares the reference-scaling shape and almost nothing else: a
    different scaling constant, a mandatory fully replicate design, an
    additional unscaled criterion, and a variance-ratio comparison. Reaching it
    by flipping a parameter on the highly-variable code would be the same
    over-generalisation that made a single `EMA_MIN_N` wrong.
    """
    from be_stats import VALIDATION, ValidationStatus

    assert VALIDATION[Method.FDA_NTI_RSABE] is ValidationStatus.NOT_IMPLEMENTED

    nti = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    assert nti.method is Method.FDA_NTI_RSABE
    with pytest.raises(NotImplementedMethod):
        nti.require_implemented()
