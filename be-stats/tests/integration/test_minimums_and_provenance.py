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
from be_stats.minimums import Framework, design_family_for, lookup
from be_stats.spec import NotValidated

FDA = resolve_be_spec(jurisdiction=Jurisdiction.FDA)
EMA = resolve_be_spec(jurisdiction=Jurisdiction.EMA)

M13A = Framework.ICH_M13A


# ------------------------------------------------------------- minimums ---


def test_crossover_and_parallel_floors_differ_because_the_rule_differs():
    """The reason the lookup is keyed by design.

    ICH M13A gives 12 evaluable subjects for a crossover but 12 PER GROUP for
    a parallel design. A jurisdiction-only constant would apply 12 to both and
    be wrong by half for every parallel study.
    """
    crossover = lookup("EMA", DesignFamily.CROSSOVER, framework=M13A)
    parallel = lookup("EMA", DesignFamily.PARALLEL, framework=M13A)

    assert crossover.required_total() == 12
    assert crossover.evaluable_total == 12
    assert crossover.evaluable_per_group is None

    assert parallel.required_total() == 24
    assert parallel.evaluable_per_group == 12
    assert parallel.evaluable_total is None


def test_the_crossover_rule_does_not_leak_into_replicate_designs():
    """M13A's core scope does not cover replicate designs, so the lookup must
    not answer for one merely because the jurisdiction matches."""
    assert lookup("EMA", DesignFamily.REPLICATE, framework=M13A) is None
    assert lookup("EMA", DesignFamily.PARTIAL_REPLICATE, framework=M13A) is None


def test_m13a_is_never_reached_without_being_asked_for():
    """The scoping correction, asserted at the lookup.

    M13A governs immediate-release solid oral dosage forms. This package is
    never told the dosage form, so it must not decide that M13A applies. An
    unstated framework resolves against general guidance only - and EMA has no
    general row, so EMA answers nothing at all until a framework is named.
    """
    assert lookup("EMA", DesignFamily.CROSSOVER) is None
    assert lookup("EMA", DesignFamily.PARALLEL) is None
    assert lookup("EMA", DesignFamily.CROSSOVER, framework=M13A) is not None


def test_fda_has_two_different_parallel_floors_and_they_do_not_merge():
    """The specific thing that must not become `FDA_PARALLEL_MIN = 12`.

    Under FDA's general PK BE guidance the floor is twelve evaluable subjects
    for the study. Under M13A - and only for the dosage forms M13A covers - a
    parallel study needs twelve *per group*, which is twenty-four. Both are
    true; neither is "the FDA rule".
    """
    general = lookup("FDA", DesignFamily.PARALLEL, framework=Framework.GENERAL)
    m13a = lookup("FDA", DesignFamily.PARALLEL, framework=M13A)

    assert general.required_total() == 12
    assert general.evaluable_per_group is None
    assert "generally" in general.scope

    assert m13a.required_total() == 24
    assert m13a.evaluable_per_group == 12
    assert "immediate-release solid oral" in m13a.scope

    # An unstated framework must resolve to the general rule, never to M13A.
    assert lookup("FDA", DesignFamily.PARALLEL).required_total() == 12


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
    crossover = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="2x2", framework=M13A
    )
    parallel = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="parallel", framework=M13A
    )

    assert crossover.regulatory_n == 12
    assert parallel.regulatory_n == 24
    assert crossover.recommended_n == 12
    assert parallel.recommended_n == 24
    assert "crossover" in crossover.regulatory_basis
    assert "per treatment group" in parallel.regulatory_basis


def test_an_unstated_framework_gets_no_ema_floor_and_says_so():
    """The cost of the scoping, made visible rather than papered over.

    A caller who does not name a framework gets `None` for EMA, not twelve.
    That is a worse answer for an IR tablet study and the right answer for
    everything else, and the result says which it is.
    """
    result = sample_size_abe(cv_percent=8.0, spec=EMA, design="2x2")
    assert result.regulatory_n is None
    assert result.regulatory_rule is None
    assert "no confirmed regulatory minimum" in result.regulatory_basis
    assert result.recommended_n == result.mathematical_n


def test_fda_parallel_under_m13a_costs_more_subjects_than_under_general():
    """The framework changes the answer, end to end, for the same study."""
    general = sample_size_abe(cv_percent=8.0, spec=FDA, design="parallel")
    m13a = sample_size_abe(
        cv_percent=8.0, spec=FDA, design="parallel", framework=M13A
    )

    assert general.regulatory_n == 12
    assert m13a.regulatory_n == 24
    assert m13a.recommended_n > general.recommended_n
    assert "immediate-release solid oral" in m13a.regulatory_basis


def test_the_rule_travels_with_the_result():
    """A floor without its citation is just another magic number."""
    result = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="2x2", framework=M13A
    )
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
    """FDA's 2001 and 2026 guidances share a title and disagree.

    The guidance's own first page says it "replaces prior FDA guidance for
    industry of the same name issued in February 2001", which is exactly why
    the version is part of the citation.

    The version reads "May 2026" and not "29 May 2026". The precise day was in
    these citations until the document was obtained; its cover gives only the
    month, and no page inside names a day. An over-specific citation is worse
    than a coarse one, because it looks checked.
    """
    hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    text = " ".join(hvd.provenance())
    assert "May 2026" in text
    assert "29 May 2026" not in text, "the day is not in the document"
    assert "2001" not in text


def test_the_fda_constants_say_they_were_read_from_the_document():
    """Chain of custody, not merely verification status.

    These constants were VERIFIED by relay before the guidance was obtained.
    They now record that they were read at the cited section. The distinction
    is the whole reason `verified_by` exists, so it is asserted rather than
    trusted to a docstring.
    """
    from be_stats.provenance import VIA_PRIMARY_DOCUMENT
    from be_stats.spec import FDA_HVD_CONSTANTS, FDA_NTI_CONSTANTS

    for table in (FDA_HVD_CONSTANTS, FDA_NTI_CONSTANTS):
        for name, value in table.items():
            assert value.verified_by == VIA_PRIMARY_DOCUMENT, name


def test_the_m13a_figures_still_say_they_were_relayed():
    """The honest half of the same distinction.

    Obtaining the FDA guidance says nothing about the ICH/FDA M13A Q&A, which
    is a different document and has NOT been obtained. Those minimums must not
    inherit the stronger claim just because they sit in the same registry.
    """
    from be_stats.minimums import DesignFamily, Framework, lookup
    from be_stats.provenance import VerificationStatus

    m13a = lookup("FDA", DesignFamily.PARALLEL, framework=Framework.ICH_M13A)
    assert m13a is not None
    assert "M13A" in m13a.citation.document
    assert m13a.verification is VerificationStatus.VERIFIED

    general = lookup("FDA", DesignFamily.CROSSOVER, framework=Framework.GENERAL)
    assert "Statistical Approaches" in general.citation.document


def test_the_switching_threshold_reaches_the_spec_as_the_regulators_value():
    """The counterpart of `test_fda_hvd_thresholds.py`, at the spec boundary.

    That file checks the constants table; this one checks that a resolved spec
    hands the caller the same number, so a future refactor cannot re-derive it
    on the way out.
    """
    hvd = resolve_be_spec(
        jurisdiction=Jurisdiction.FDA, drug_class=DrugClass.HIGHLY_VARIABLE
    )
    swr = hvd.constants["swr_switching_threshold"]
    assert swr.value == 0.294
    assert swr.verification is VerificationStatus.VERIFIED
    assert "must not be recomputed" in swr.note


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
    assert Method.EMA_HVD_ABEL not in IMPLEMENTED
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
