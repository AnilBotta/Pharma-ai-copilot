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
    for spec in (fda, ema):
        assert not spec.is_implemented
        with pytest.raises(NotImplementedMethod):
            spec.require_implemented()


def test_unimplemented_methods_are_not_in_the_implemented_set():
    from be_stats import IMPLEMENTED

    assert Method.STANDARD_ABE in IMPLEMENTED
    assert Method.EMA_NTI_NARROW_ABE in IMPLEMENTED
    for method in (
        Method.FDA_NTI_RSABE,
        Method.FDA_HVD_RSABE,
        Method.EMA_HVD_ABEL,
    ):
        assert method not in IMPLEMENTED
