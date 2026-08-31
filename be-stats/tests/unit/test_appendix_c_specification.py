"""What FDA Appendix C requires, as data — and what remains unimplemented.

This file guards a SPECIFICATION, not an implementation. Appendix C is
`NOT_IMPLEMENTED` and PR #61 deliberately did not change that: the point of
that PR was to find out whether a trustworthy numerical oracle exists before
writing a five-parameter REML fit, on the principle the EMA release
established — implementing a regulator's exact model is worth doing once there
is evidence capable of detecting a plausible-but-wrong version of it.

So the tests here assert two things:

    the specification says what FDA says, including the parts a convenient
    implementation would be tempted to drop;

    nothing has quietly started running.
"""

from __future__ import annotations

import pytest

from be_stats import replicate_abe
from be_stats.provenance import ValidationStatus
from be_stats.replicate_abe import APPENDIX_C_MODEL


# ------------------------------------------------- the five parameters ---


def test_the_covariance_parameters_are_named_not_merely_counted():
    """"Five-parameter covariance model" is a count, not a specification.

    An implementation has to know WHICH five, and a reviewer has to be able to
    check that it fitted those and not five others.
    """
    assert APPENDIX_C_MODEL.n_covariance_parameters == 5
    named = APPENDIX_C_MODEL.covariance_parameters
    assert len(named) == 5

    joined = " ".join(named)
    for parameter in ("sigma2_BT", "sigma2_BR", "sigma_BTBR", "sigma2_WT",
                      "sigma2_WR"):
        assert parameter in joined, parameter

    # Each one says where it comes from in the SAS, so the mapping is checkable
    # against the source rather than trusted.
    assert "G[1,1]" in joined and "G[2,2]" in joined and "G[1,2]" in joined
    assert joined.count("REPEATED") == 2


def test_the_subject_by_formulation_variance_is_derived_not_estimated():
    """It is a function of three of the five, not a sixth parameter.

    EMA/618604/2008 Rev. 13 puts the same point in words: "the last three are
    combined to give the subject x formulation interaction variance
    component". An implementation that estimated it separately would be
    fitting a different model.
    """
    formula = APPENDIX_C_MODEL.subject_by_formulation_variance
    assert formula == "sigma2_D = sigma2_BT + sigma2_BR - 2*sigma_BTBR"


def test_fa0_2_is_recorded_as_a_constrained_structure():
    """FDA writes FA0(2), not UN, and the difference is the constraint.

    G = LL' is positive semi-definite by construction; TYPE=UN is not. FDA's
    permitted alternatives (CSH, UNR) are likewise constrained, which is
    consistent with the constraint being the point rather than an accident of
    which structure someone typed first.
    """
    assert "FA0(2)" in APPENDIX_C_MODEL.random_effects
    joined = " ".join(APPENDIX_C_MODEL.covariance_parameters)
    assert "l11" in joined and "l21" in joined and "l22" in joined


# ----------------------------------------- what FDA itself permits ---


def test_the_permitted_alternatives_are_recorded():
    """FDA names them, so an oracle using CSH or KR2 is not disqualified.

    Recorded because the opposite mistake is easy: treating FA0(2) and
    SATTERTH as the only acceptable choices would wrongly rule out a valid
    oracle, and treating ANY structure as acceptable would wrongly admit one.
    """
    joined = " ".join(APPENDIX_C_MODEL.permitted_alternatives)
    assert "CSH" in joined and "UNR" in joined
    assert "KR2" in joined
    assert "same results are generated" in joined, (
        "the alternative-software sentence is the licence for an external "
        "oracle and also its burden; it must not be dropped"
    )


def test_the_sas_block_is_recorded_verbatim():
    """So the specification can be diffed against the source without the PDF."""
    sas = "\n".join(APPENDIX_C_MODEL.sas)
    for line in (
        "CLASSES SEQ SUBJ PER TRT;",
        "MODEL Y = SEQ PER TRT/ DDFM=SATTERTH;",
        "RANDOM TRT/TYPE=FA0(2) SUB=SUBJ G;",
        "REPEATED/GRP=TRT SUB=SUBJ;",
        "ESTIMATE 'T vs. R' TRT 1 -1/CL ALPHA=0.1;",
    ):
        assert line in sas, line


# ------------------------------------------------------ missing data ---


def test_appendix_c_is_an_available_case_analysis():
    """Answered by the guidance, not inferred from the model.

    FDA section III names PROC MIXED as an available case analysis that "uses
    all observed data", contrasted with PROC GLM which "removes all subjects
    with any missing observations". PR #60 proved regulator-specific inclusion
    rules materially change results, so this one is recorded from the source
    rather than borrowed from a neighbouring model.
    """
    rule = APPENDIX_C_MODEL.missing_data_rule
    assert "available case" in rule
    assert "all observed data" in rule
    assert "prespecified" in rule


def test_the_inclusion_rule_is_not_appendix_g_s_and_not_ema_s():
    """Three models in this package, three different inclusion rules.

    Appendix G drops a subject without both reference replicates, because sWR
    needs them. EMA Method A keeps every observed row. Appendix C is an
    available case analysis and is the most permissive of the three. Sharing
    any of them would be sharing a regulatory opinion.
    """
    rule = APPENDIX_C_MODEL.missing_data_rule
    assert "reference replicate" not in rule
    assert "Method A" not in rule


# ----------------------------------------------- still not implemented ---


def test_the_oracle_verdict_is_recorded_per_design_not_globally():
    """The Julia result split by design, and the record has to keep that split.

    ReplicateBE.jl reproduces EMA's published SAS Method C output exactly on
    the fully replicate design and differs on the partial replicate one. A
    single "verified / not verified" flag would lose the only part of this
    finding a future implementer can act on.
    """
    import json
    from pathlib import Path

    findings = (
        Path(__file__).resolve().parents[2] / "validation" / "findings"
    )
    two = json.loads(
        (findings / "VAL-FDA-APPENDIX-C-002.json").read_text(encoding="utf-8")
    )

    assert two["status"] == "OPEN"
    assert two["data_set_i"]["covered_by_the_packages_own_claim"] is True
    assert two["data_set_ii"]["covered_by_the_packages_own_claim"] is False

    # Fully replicate: every published quantity matched.
    statuses_i = {c["status"] for c in two["data_set_i"]["comparison"]}
    assert statuses_i <= {"MATCH", "NOT_PUBLISHED"}

    # Partial replicate: the interval and the df did not.
    differing = {
        c["quantity"]
        for c in two["data_set_ii"]["comparison"]
        if c["status"] == "DIFFERS"
    }
    assert differing == {"ci_lower_percent", "ci_upper_percent", "denominator_df"}

    # And which of the two is right is explicitly NOT claimed.
    assert two["what_is_not_established"][
        "which_is_right_on_the_partial_replicate"
    ] == "NOT_DETERMINED"


def test_the_boundary_solution_is_recorded_for_a_future_implementer():
    """rho = 1.000 exactly on Data set I.

    The subject-by-formulation correlation sits on the boundary of the
    parameter space for the one data set that otherwise validates everything.
    An implementation assuming an interior optimum, or inverting a Hessian
    without checking, fails precisely there - so it is recorded where whoever
    writes the REML fit will meet it.
    """
    import json
    from pathlib import Path

    findings = (
        Path(__file__).resolve().parents[2] / "validation" / "findings"
    )
    two = json.loads(
        (findings / "VAL-FDA-APPENDIX-C-002.json").read_text(encoding="utf-8")
    )
    boundary = two["data_set_i"]["boundary_solution"]
    assert boundary["subject_by_formulation_correlation"] == 1.0
    assert "boundary of the parameter space" in (
        boundary["consequence_for_a_future_implementation"]
    )


def test_the_capability_split_never_implies_partial_replicate_support():
    """One model, two designs, and the statuses must not blur them.

    A single `FDA_REPLICATE_STANDARD_ABE` reading IMPLEMENTED would tell a
    reader that Appendix C works, full stop - and it does not. It works for the
    design PR #61 found an oracle for. The split is the only way the report can
    be read correctly by someone who does not know that history.
    """
    from be_stats.spec import CAPABILITY_VALIDATION, Capability

    assert CAPABILITY_VALIDATION[
        Capability.FDA_REPLICATE_STANDARD_ABE_FULL
    ] is not ValidationStatus.NOT_IMPLEMENTED
    assert CAPABILITY_VALIDATION[
        Capability.FDA_REPLICATE_STANDARD_ABE_PARTIAL
    ] is ValidationStatus.NOT_IMPLEMENTED

    # The undifferentiated name must not exist: it is exactly the thing that
    # would let a future edit re-merge the two.
    assert not hasattr(Capability, "FDA_REPLICATE_STANDARD_ABE")


def test_the_existing_fda_decisions_are_unchanged_by_the_investigation():
    """Point 16 of the brief, as a regression guard.

    FDA HVD below sWR = 0.294 still returns NOT DECIDED, and FDA NTI criterion
    (b) is still unavailable - both because Appendix C is absent, and an
    investigation that changed either would have stopped being an
    investigation.
    """
    from be_stats.diagnostics import DiagnosticCode
    from be_stats.replicate_abe import replicate_abe_unavailable

    class _Dataset:
        design = "fully_replicate"
        endpoint = "AUC"
        records = ()

    diagnostic = replicate_abe_unavailable(_Dataset())
    assert diagnostic.code is DiagnosticCode.REPLICATE_ABE_MODEL_NOT_IMPLEMENTED
    assert "Appendix G" in diagnostic.detail, (
        "the refusal must keep saying why the nearby Iij model is not a "
        "substitute"
    )


def test_appendix_c_remains_not_implemented_after_the_oracle_investigation():
    """PR #61 investigated; it did not implement, and must not appear to have.

    `oracle_ready` and `implementation_status` are different concepts, and the
    second is the one that governs whether a number may be produced.
    """
    assert replicate_abe.VALIDATION_STATUS is ValidationStatus.NOT_IMPLEMENTED

    from be_stats.spec import NotImplementedMethod

    with pytest.raises(NotImplementedMethod):
        replicate_abe.analyse_replicate_abe(None)


def test_the_refusal_still_explains_the_model_it_would_have_to_fit():
    """A refusal that does not say what is missing is just an error."""
    from be_stats.replicate_abe import _REASON

    for fragment in ("FA0(2)", "GRP=TRT", "Satterthwaite", "five"):
        assert fragment in _REASON, fragment
    assert "Appendix G" in _REASON, (
        "the refusal must say WHY the nearby Iij model is not a substitute"
    )


def test_ema_method_a_is_not_fda_appendix_c():
    """The guard point 6 of the PR #61 brief asks for.

    EMA Method A was VALIDATED in PR #60 against EMA's own published numbers.
    It is a different model from FDA Appendix C, and the temptation to reuse it
    is real precisely because the two produce similar POINT ESTIMATES on
    balanced data - EMA's own annex shows 102.26 from both on Data set II.

    They differ where it decides:

        Method A     all effects FIXED, ONE residual variance, no
                     subject-by-formulation covariance, residual df
        Appendix C   subject-by-formulation RANDOM effects, TWO residual
                     variances, Satterthwaite df

    On EMA's Data set II those give 90% intervals of (97.32, 107.46) and
    (97.05, 107.76) respectively - the second materially wider, from a
    denominator df of about 19.6 against 45. Same estimate, different decision
    at the boundary.
    """
    from be_stats.ema_hvd import TreatmentEffect

    # Method A's model string names its own structure and does NOT claim any
    # of Appendix C's.
    method_a = TreatmentEffect.__dataclass_fields__["model"].default
    assert "Method A" in method_a
    assert "fixed-effects ANOVA" in method_a
    for appendix_c_only in ("FA0(2)", "GRP=TRT", "Satterthwaite", "random"):
        assert appendix_c_only not in method_a, (
            f"EMA Method A must not claim {appendix_c_only!r}, which belongs "
            "to FDA Appendix C"
        )

    # And Appendix C's specification does not describe Method A.
    explained = " ".join(APPENDIX_C_MODEL.explain())
    assert "FA0(2)" in explained
    assert APPENDIX_C_MODEL.n_covariance_parameters == 5
    assert "Method A" not in explained


def test_the_ema_module_cannot_be_reached_from_the_appendix_c_module():
    """Structural, not stylistic.

    If `replicate_abe` ever imported the EMA fitter, Appendix C would be one
    convenient edit away from silently becoming Method A - the exact
    substitution `_REASON` refuses to make with Appendix G.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(replicate_abe.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("ema" in (m or "") for m in imported), imported
    assert not any("linear_model" in (m or "") for m in imported), (
        "the OLS helper fits Method A's model; reaching it from here would "
        "make the wrong model available at the right call site"
    )


def test_the_optimiser_lives_only_where_appendix_c_does():
    """The guard from PR #61, narrowed rather than deleted.

    It used to assert that NO module called an optimiser, because a REML fit
    appearing anywhere would have meant Appendix C had arrived before the
    oracle question was settled. That question is settled for the fully
    replicate design, so `appendix_c.py` now legitimately optimises.

    Everything else still must not. A second module reaching for `minimize`
    would mean a second mixed model had appeared somewhere it could not be
    checked - which is the original hazard, not a historical one.
    """
    import ast
    from pathlib import Path

    package = Path(replicate_abe.__file__).parent
    for path in package.glob("*.py"):
        if path.name == "appendix_c.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for forbidden in ("minimize", "fmin", "least_squares", "nnls"):
            assert forbidden not in called, (
                f"{path.name} calls {forbidden}. Appendix C's REML fit belongs "
                "in appendix_c.py and nowhere else; a second optimiser means a "
                "second model somewhere it cannot be checked"
            )


def test_appendix_c_is_the_only_module_fitting_a_mixed_model():
    """And it is reached from the two call sites, not reimplemented in them."""
    import ast
    from pathlib import Path

    package = Path(replicate_abe.__file__).parent
    for name in ("hvd.py", "nti.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("appendix_c")
            for alias in node.names
        }
        assert "analyse_replicate_abe_full" in imported, (
            f"{name} must reach Appendix C through its public entry point"
        )
