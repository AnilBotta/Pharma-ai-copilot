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


def test_no_module_has_started_fitting_a_mixed_model():
    """The structural guard against Appendix C arriving by accident.

    A REML objective or a variance-component optimiser appearing anywhere in
    the package would mean this investigation had turned into an
    implementation without the oracle question being settled.
    """
    import ast
    from pathlib import Path

    package = Path(replicate_abe.__file__).parent
    for path in package.glob("*.py"):
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
                f"{path.name} calls {forbidden}; a numerical optimiser in the "
                "package would mean the mixed model had arrived without the "
                "oracle question being answered"
            )
