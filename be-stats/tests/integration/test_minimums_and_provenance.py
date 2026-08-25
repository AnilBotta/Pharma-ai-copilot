"""Regulatory floors keyed by design, and the provenance behind every number.

Integration rather than unit: these are about how the pieces route to one
another - which rule reaches which study, and whether a number can explain
itself - rather than about arithmetic.
"""

from __future__ import annotations

import pytest

from be_stats import (
    DesignFamily,
    DrugClass,
    Endpoint,
    Jurisdiction,
    ValidationStatus,
    VerificationStatus,
    resolve_be_spec,
    sample_size_abe,
)
from be_stats.minimums import design_family_for, lookup
from be_stats.spec import NotValidated

FDA = resolve_be_spec(jurisdiction=Jurisdiction.FDA)
EMA = resolve_be_spec(jurisdiction=Jurisdiction.EMA)


# ------------------------------------------------------------- minimums ---


def test_crossover_and_parallel_floors_differ_because_the_rule_differs():
    """The reason the lookup is keyed by design.

    ICH M13A gives 12 evaluable subjects for a crossover but 12 PER GROUP for
    a parallel design. A jurisdiction-only constant would apply 12 to both and
    be wrong by half for every parallel study.
    """
    crossover = lookup("EMA", DesignFamily.CROSSOVER)
    parallel = lookup("EMA", DesignFamily.PARALLEL)

    assert crossover.required_total() == 12
    assert crossover.evaluable_total == 12
    assert crossover.evaluable_per_group is None

    assert parallel.required_total() == 24
    assert parallel.evaluable_per_group == 12
    assert parallel.evaluable_total is None


def test_the_crossover_rule_does_not_leak_into_replicate_designs():
    """M13A's core scope does not cover replicate designs, so the lookup must
    not answer for one merely because the jurisdiction matches."""
    assert lookup("EMA", DesignFamily.REPLICATE) is None
    assert lookup("EMA", DesignFamily.PARTIAL_REPLICATE) is None


def test_fda_parallel_is_absent_rather_than_assumed():
    """Deliberate gap. The FDA figure cited was "not fewer than 12 evaluable
    subjects"; whether the M13A twelve-per-group rule governs an FDA parallel
    study was flagged unconfirmed, so no row was registered for it."""
    assert lookup("FDA", DesignFamily.CROSSOVER) is not None
    assert lookup("FDA", DesignFamily.PARALLEL) is None


def test_highly_variable_products_carry_their_own_floor():
    hvd = lookup("FDA", DesignFamily.REPLICATE, is_highly_variable=True)
    assert hvd.required_total() == 24
    # And it is not reachable by a replicate study that is merely replicate.
    assert lookup("FDA", DesignFamily.REPLICATE, is_highly_variable=False) is None


def test_an_unknown_design_refuses_rather_than_guessing():
    with pytest.raises(ValueError, match="Guessing"):
        design_family_for("2x2x4")


def test_sample_size_applies_the_floor_for_the_design_it_was_given():
    """End to end: the same CV under two designs picks up two different rules."""
    crossover = sample_size_abe(cv_percent=8.0, spec=EMA, design="2x2")
    parallel = sample_size_abe(cv_percent=8.0, spec=EMA, design="parallel")

    assert crossover.regulatory_n == 12
    assert parallel.regulatory_n == 24
    assert crossover.recommended_n == 12
    assert parallel.recommended_n == 24
    assert "crossover" in crossover.regulatory_basis
    assert "per treatment group" in parallel.regulatory_basis


def test_fda_parallel_gets_no_floor_and_says_so():
    result = sample_size_abe(cv_percent=8.0, spec=FDA, design="parallel")
    assert result.regulatory_n is None
    assert result.regulatory_rule is None
    assert "no confirmed regulatory minimum" in result.regulatory_basis
    assert result.recommended_n == result.mathematical_n


def test_the_rule_travels_with_the_result():
    """A floor without its citation is just another magic number."""
    result = sample_size_abe(cv_percent=8.0, spec=EMA, design="2x2")
    assert result.regulatory_rule is not None
    assert "ICH" in str(result.regulatory_rule.citation)
    assert result.regulatory_rule.verification is VerificationStatus.VERIFIED


# ----------------------------------------------------------- provenance ---


def test_every_acceptance_limit_can_explain_itself():
    """The question this framework exists to answer: why 0.90?"""
    nti = resolve_be_spec(
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoint=Endpoint.AUC,
    )
    lines = nti.provenance()
    assert any("90.0" in line for line in lines)
    assert any("EMA" in line and "Bioequivalence" in line for line in lines)
    assert all("[" in line for line in lines), "each line must carry a status"


def test_the_fda_document_version_is_pinned_not_just_the_authority():
    """FDA's 2001 and 2026 guidances share a title and disagree."""
    hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    text = " ".join(hvd.provenance())
    assert "29 May 2026" in text


def test_the_derived_threshold_is_marked_derived():
    hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    swr = hvd.constants["swr_switching_threshold"]
    assert swr.verification is VerificationStatus.DERIVED
    assert "0.294" in swr.note, "the open question must stay visible"


def test_no_spec_ships_an_unverified_value_silently():
    """A jurisdiction default must be checked. Only a caller-supplied product
    override may be unverified, and then it is the caller's number."""
    for jurisdiction in (Jurisdiction.FDA, Jurisdiction.EMA):
        for drug_class in DrugClass:
            try:
                spec = resolve_be_spec(
                    jurisdiction=jurisdiction,
                    drug_class=drug_class,
                    endpoint=Endpoint.AUC,
                )
            except Exception:
                continue
            assert spec.unverified_values() == [], (
                f"{jurisdiction}/{drug_class} exposes unverified values: "
                f"{spec.unverified_values()}"
            )


# ---------------------------------------------------- validation status ---


def test_implemented_is_derived_from_the_validation_table():
    from be_stats import IMPLEMENTED, VALIDATION
    from be_stats.spec import Method

    assert Method.STANDARD_ABE in IMPLEMENTED
    assert Method.FDA_HVD_RSABE not in IMPLEMENTED
    for method in Method:
        expected = VALIDATION[method] is not ValidationStatus.NOT_IMPLEMENTED
        assert (method in IMPLEMENTED) is expected


def test_a_caller_can_refuse_unvalidated_arithmetic():
    """The opt-in gate a production integration would use."""
    assert FDA.validation_status is ValidationStatus.IMPLEMENTED_UNVALIDATED
    with pytest.raises(NotValidated, match="must not support a submission"):
        FDA.require_validated()


def test_estimators_do_not_silently_enforce_validation():
    """`require_validated` is opt-in on purpose: development use is legitimate
    and must not require a flag buried in the engine."""
    result = sample_size_abe(cv_percent=20.0, spec=FDA)
    assert result.mathematical_n > 0
