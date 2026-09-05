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
from be_stats.minimums import (
    Framework,
    MinimumApplicability,
    StudyRole,
    design_family_for,
    lookup,
)

PIVOTAL = StudyRole.PIVOTAL
PILOT = StudyRole.PILOT
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
    crossover = lookup(
        "EMA", DesignFamily.CROSSOVER, framework=M13A, study_role=PIVOTAL
    )
    parallel = lookup(
        "EMA", DesignFamily.PARALLEL, framework=M13A, study_role=PIVOTAL
    )

    assert crossover.required_total() == 12
    assert crossover.rule.evaluable_total == 12
    assert crossover.rule.evaluable_per_group is None

    assert parallel.required_total() == 24
    assert parallel.rule.evaluable_per_group == 12
    assert parallel.rule.evaluable_total is None


def test_the_crossover_rule_does_not_leak_into_replicate_designs():
    """M13A's core scope does not cover replicate designs, so the lookup must
    not answer for one merely because the jurisdiction matches."""
    for design in (DesignFamily.REPLICATE, DesignFamily.PARTIAL_REPLICATE):
        outcome = lookup("EMA", design, framework=M13A, study_role=PIVOTAL)
        assert outcome.applicability is MinimumApplicability.NONE_CONFIRMED
        assert outcome.rule is None
        assert outcome.required_total() is None


def test_m13a_is_never_reached_without_being_asked_for():
    """The scoping correction, asserted at the lookup.

    M13A governs immediate-release solid oral dosage forms. This package is
    never told the dosage form, so it must not decide that M13A applies. An
    unstated framework resolves against general guidance only - and EMA has no
    general row, so EMA answers nothing at all until a framework is named.

    Note the outcome is NONE_CONFIRMED and not ROLE_NOT_STATED even though the
    role is unstated too: there is no EMA general row to have a role
    constraint, so the framework is what is missing. The two reasons are kept
    apart because they are closed by different information.
    """
    for design in (DesignFamily.CROSSOVER, DesignFamily.PARALLEL):
        assert (
            lookup("EMA", design).applicability
            is MinimumApplicability.NONE_CONFIRMED
        )
    assert lookup(
        "EMA", DesignFamily.CROSSOVER, framework=M13A, study_role=PIVOTAL
    ).applies


def test_fda_has_two_different_parallel_floors_and_they_do_not_merge():
    """The specific thing that must not become `FDA_PARALLEL_MIN = 12`.

    Under FDA's general PK BE guidance the floor is twelve evaluable subjects
    for the study. Under M13A - and only for the dosage forms M13A covers - a
    parallel study needs twelve *per group*, which is twenty-four. Both are
    true; neither is "the FDA rule".
    """
    general = lookup("FDA", DesignFamily.PARALLEL, framework=Framework.GENERAL)
    m13a = lookup("FDA", DesignFamily.PARALLEL, framework=M13A, study_role=PIVOTAL)

    assert general.required_total() == 12
    assert general.rule.evaluable_per_group is None
    assert "generally" in general.rule.scope

    assert m13a.required_total() == 24
    assert m13a.rule.evaluable_per_group == 12
    assert "immediate-release solid oral" in m13a.rule.scope

    # An unstated framework must resolve to the general rule, never to M13A.
    assert lookup("FDA", DesignFamily.PARALLEL).required_total() == 12


def test_the_general_fda_floor_is_not_restricted_to_pivotal_studies():
    """§II.A is a DIFFERENT document from M13A, and it does not say "pivotal".

    Verbatim: "The number of evaluable subjects in a PK BE study should not be
    less than 12." A PK BE study, unqualified. Gating this behind the study
    role because it shares the number 12 with M13A's rule would delete a floor
    FDA states unconditionally - which is why the constraint lives per row
    rather than on the lookup.
    """
    for role in (PIVOTAL, PILOT, StudyRole.NOT_STATED):
        for design in (DesignFamily.CROSSOVER, DesignFamily.PARALLEL):
            outcome = lookup(
                "FDA", design, framework=Framework.GENERAL, study_role=role
            )
            assert outcome.applies, (role, design, outcome.reason)
            assert outcome.required_total() == 12
            assert "Statistical Approaches" in outcome.rule.citation.document


def test_highly_variable_products_carry_their_own_floor():
    hvd = lookup("FDA", DesignFamily.REPLICATE, is_highly_variable=True)
    assert hvd.required_total() == 24
    # And it is not reachable by a replicate study that is merely replicate.
    assert (
        lookup(
            "FDA", DesignFamily.REPLICATE, is_highly_variable=False
        ).applicability
        is MinimumApplicability.NONE_CONFIRMED
    )


def test_the_highly_variable_floor_is_not_restricted_to_pivotal_studies():
    """Same source as the general floor, same absence of the qualifier.

    "For highly variable drug products, a minimum of 24 subjects are
    recommended for BE assessment" - Statistical Approaches II.A, one sentence
    after the twelve. Neither is role-scoped.
    """
    for role in (PIVOTAL, PILOT, StudyRole.NOT_STATED):
        outcome = lookup(
            "FDA",
            DesignFamily.REPLICATE,
            is_highly_variable=True,
            study_role=role,
        )
        assert outcome.applies, (role, outcome.reason)
        assert outcome.required_total() == 24


# ------------------------------------------- the study-role behaviour matrix ---
#
# jurisdiction x design x role, stated as data so a gap in the matrix is
# visible rather than inferred from which tests happen to exist.
#
# `None` means no floor is in force. Which is NOT zero and NOT "no rule
# exists" - the applicability column below says which of the three it is.

_M13A_MATRIX = [
    # jurisdiction, design,                  role,        floor, applicability
    ("FDA", DesignFamily.CROSSOVER, PIVOTAL, 12, MinimumApplicability.APPLIES),
    ("FDA", DesignFamily.PARALLEL, PIVOTAL, 24, MinimumApplicability.APPLIES),
    ("EMA", DesignFamily.CROSSOVER, PIVOTAL, 12, MinimumApplicability.APPLIES),
    ("EMA", DesignFamily.PARALLEL, PIVOTAL, 24, MinimumApplicability.APPLIES),
    (
        "FDA",
        DesignFamily.CROSSOVER,
        PILOT,
        None,
        MinimumApplicability.NOT_APPLICABLE_FOR_ROLE,
    ),
    (
        "FDA",
        DesignFamily.PARALLEL,
        PILOT,
        None,
        MinimumApplicability.NOT_APPLICABLE_FOR_ROLE,
    ),
    (
        "EMA",
        DesignFamily.CROSSOVER,
        PILOT,
        None,
        MinimumApplicability.NOT_APPLICABLE_FOR_ROLE,
    ),
    (
        "EMA",
        DesignFamily.PARALLEL,
        PILOT,
        None,
        MinimumApplicability.NOT_APPLICABLE_FOR_ROLE,
    ),
    (
        "FDA",
        DesignFamily.CROSSOVER,
        StudyRole.NOT_STATED,
        None,
        MinimumApplicability.ROLE_NOT_STATED,
    ),
    (
        "FDA",
        DesignFamily.PARALLEL,
        StudyRole.NOT_STATED,
        None,
        MinimumApplicability.ROLE_NOT_STATED,
    ),
    (
        "EMA",
        DesignFamily.CROSSOVER,
        StudyRole.NOT_STATED,
        None,
        MinimumApplicability.ROLE_NOT_STATED,
    ),
    (
        "EMA",
        DesignFamily.PARALLEL,
        StudyRole.NOT_STATED,
        None,
        MinimumApplicability.ROLE_NOT_STATED,
    ),
]


@pytest.mark.parametrize(
    "jurisdiction,design,role,floor,applicability", _M13A_MATRIX
)
def test_the_m13a_floor_applies_only_to_pivotal_studies(
    jurisdiction, design, role, floor, applicability
):
    """DOSSIER-005, as a matrix rather than as four hand-picked examples."""
    outcome = lookup(jurisdiction, design, framework=M13A, study_role=role)

    assert outcome.applicability is applicability
    assert outcome.required_total() == floor
    assert outcome.study_role is role
    assert outcome.reason.strip()

    # The rule is CARRIED even when it does not apply, so a report can name
    # the document it is declining to apply rather than going silent.
    assert outcome.rule is not None
    assert "M13A" in outcome.rule.citation.document


@pytest.mark.parametrize("role", [PILOT, StudyRole.NOT_STATED])
@pytest.mark.parametrize("design", [DesignFamily.CROSSOVER, DesignFamily.PARALLEL])
def test_a_non_pivotal_study_is_never_given_twelve_by_any_route(role, design):
    """The failure this finding is about, asserted as an absence.

    Not "the applicability field says no" - that could be true while the
    number came out at twelve anyway. The FIGURE must be absent.
    """
    outcome = lookup("FDA", design, framework=M13A, study_role=role)
    assert outcome.required_total() is None
    assert not outcome.applies
    # And not zero, which would be a floor, and a false one.
    assert outcome.required_total() != 0


def test_an_unstated_role_refuses_a_sample_size_rather_than_shrinking_it():
    """Fail closed where the number gets acted on.

    `lookup` reports ROLE_NOT_STATED, because "you did not say" is a fair
    answer to a question. `sample_size_abe` returns a number somebody enrols
    against, and quietly dropping the floor would hand back a SMALLER study
    than the previous release through a path the caller never saw. So it
    refuses.
    """
    from be_stats.spec import SpecificationRequired

    with pytest.raises(SpecificationRequired, match="StudyRole.PIVOTAL"):
        sample_size_abe(cv_percent=8.0, spec=EMA, design="2x2", framework=M13A)


def test_a_pilot_study_gets_the_arithmetic_and_says_why_no_floor_applied():
    """§6: not-applicable is reported, not encoded as zero or as missing.

    A pilot still has a mathematically computed sample size. This PR controls
    only whether M13A's pivotal floor is added on top of it.
    """
    pilot = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="2x2", framework=M13A, study_role=PILOT
    )

    assert pilot.regulatory_n is None
    assert pilot.regulatory_n != 0
    assert (
        pilot.minimum_applicability
        is MinimumApplicability.NOT_APPLICABLE_FOR_ROLE
    )
    assert pilot.study_role is PILOT
    assert pilot.recommended_n == pilot.mathematical_n
    assert pilot.binding_constraint == "the power calculation"

    # The reason names the document and the scope, so a reader can check it.
    assert "pivotal" in pilot.regulatory_basis
    assert "M13A" in pilot.regulatory_basis
    # And the rule is still attached, rather than the result going quiet.
    assert pilot.regulatory_rule is not None


def test_the_role_changes_only_the_floor_and_never_the_arithmetic():
    """§9: the mathematics is identical across every role.

    The pre-floor figure is the whole of the sample-size calculation. If it
    moves when the role changes, something in the power path is reading the
    role, which nothing should.
    """
    results = {
        role: sample_size_abe(
            cv_percent=22.0,
            spec=EMA,
            design="2x2",
            framework=M13A,
            study_role=role,
        )
        for role in (PIVOTAL, PILOT)
    }
    maths = {role: r.mathematical_n for role, r in results.items()}
    powers = {role: r.achieved_power for role, r in results.items()}

    assert len(set(maths.values())) == 1, maths
    assert len(set(powers.values())) == 1, powers

    # At CV 22% the arithmetic already exceeds twelve, so the floor is not
    # binding for either - and the recommendation matches too.
    assert results[PIVOTAL].mathematical_n > 12
    assert results[PIVOTAL].recommended_n == results[PILOT].recommended_n


def test_the_pre_floor_arithmetic_matches_the_baseline_taken_from_main():
    """§9, proved against the PREVIOUS REVISION rather than against itself.

    The baseline in `tests/fixtures/` was generated by running this same grid
    under `origin/main` at 779b104 - the merge of PR #77, before any of this
    PR's changes existed - in a separate git worktree. So it is not a snapshot
    of the current code's opinion of itself; it is what the code did before
    the study-role model was introduced.

    96 points: two jurisdictions x two designs x six CVs x two target powers x
    two assumed ratios. Only `mathematical_n` and `achieved_power` are
    recorded, because those are the whole of the power path and the regulatory
    floor cannot reach either. A change to the noncentral-t call, the CV
    transformation, the even-n search or the rounding moves at least one row.
    """
    import json
    import pathlib

    baseline_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "fixtures"
        / "sample_size_pre_floor_baseline.json"
    )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert len(baseline) == 96, "the baseline itself has been trimmed"

    for key, expected in baseline.items():
        jurisdiction, design, cv, power, ratio = key.split("|")
        spec = FDA if jurisdiction == "FDA" else EMA
        result = sample_size_abe(
            cv_percent=float(cv.removeprefix("cv")),
            spec=spec,
            design=design,
            target_power=float(power.removeprefix("p")),
            expected_ratio=float(ratio.removeprefix("r")),
            framework=M13A,
            study_role=PIVOTAL,
        )
        assert result.mathematical_n == expected["mathematical_n"], key
        assert round(result.achieved_power, 12) == expected["achieved_power"], key


def test_an_unknown_design_refuses_rather_than_guessing():
    with pytest.raises(ValueError, match="Guessing"):
        design_family_for("2x2x4")


def test_sample_size_applies_the_floor_for_the_design_it_was_given():
    """End to end: the same CV under two designs picks up two different rules."""
    crossover = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="2x2", framework=M13A, study_role=PIVOTAL
    )
    parallel = sample_size_abe(
        cv_percent=8.0,
        spec=EMA,
        design="parallel",
        framework=M13A,
        study_role=PIVOTAL,
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
    # The enum, not a substring of the sentence. Prose gets reworded; this is
    # the field a caller branches on.
    assert result.minimum_applicability is MinimumApplicability.NONE_CONFIRMED
    assert result.recommended_n == result.mathematical_n


def test_fda_parallel_under_m13a_costs_more_subjects_than_under_general():
    """The framework changes the answer, end to end, for the same study."""
    general = sample_size_abe(cv_percent=8.0, spec=FDA, design="parallel")
    m13a = sample_size_abe(
        cv_percent=8.0,
        spec=FDA,
        design="parallel",
        framework=M13A,
        study_role=PIVOTAL,
    )

    assert general.regulatory_n == 12
    assert m13a.regulatory_n == 24
    assert m13a.recommended_n > general.recommended_n
    assert "immediate-release solid oral" in m13a.regulatory_basis


def test_the_rule_travels_with_the_result():
    """A floor without its citation is just another magic number.

    The authority is asserted as a FIELD rather than as a substring of the
    rendered citation. `"ICH" in str(citation)` used to stand here and would
    now pass for the wrong reason: EMA's adopted Q&A is titled "ICH M13A
    Guideline on bioequivalence...", so the letters survive a change of
    authority that is exactly what this test should notice.
    """
    result = sample_size_abe(
        cv_percent=8.0, spec=EMA, design="2x2", framework=M13A, study_role=PIVOTAL
    )
    assert result.regulatory_rule is not None
    assert result.regulatory_rule.citation.authority == "EMA"
    assert result.study_role is PIVOTAL
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


def test_the_m13a_figures_are_now_read_rather_than_relayed():
    """The honest half of the same distinction, updated when it stopped being true.

    This test was `test_the_m13a_figures_still_say_they_were_relayed`, and its
    docstring said the M13A Q&A "has NOT been obtained". That claim lived only
    in the docstring - the body asserted VERIFIED and a document name, neither
    of which distinguishes a relayed figure from a read one, so the sentence
    could go stale without anything failing.

    All three adoptions have since been obtained and read at Q&A 2.1. What is
    asserted now is the property that would have caught the staleness: the
    citation a minimum travels with must be PINNED, which a relayed figure
    with no issue identified cannot be.
    """
    from be_stats.dossier.citations import is_pinned, why_not_pinned
    from be_stats.minimums import DesignFamily, Framework, lookup
    from be_stats.provenance import VerificationStatus

    m13a = lookup(
        "FDA",
        DesignFamily.PARALLEL,
        framework=Framework.ICH_M13A,
        study_role=PIVOTAL,
    ).rule
    assert m13a is not None
    assert "M13A" in m13a.citation.document
    assert m13a.verification is VerificationStatus.VERIFIED
    assert is_pinned(m13a.citation), why_not_pinned(m13a.citation)
    assert "2.1" in m13a.citation.section

    general = lookup(
        "FDA", DesignFamily.CROSSOVER, framework=Framework.GENERAL
    ).rule
    assert "Statistical Approaches" in general.citation.document
    assert is_pinned(general.citation), why_not_pinned(general.citation)


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
    assert Method.EMA_HVD_ABEL in IMPLEMENTED
    # Every method in the enum is implemented as of the Appendix C
    # release. The set is still DERIVED from VALIDATION rather than
    # maintained beside it, which is what the loop below checks.
    assert Method.FDA_NTI_RSABE in IMPLEMENTED
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
