"""FDA Appendix C, fully replicate, against both frozen oracles.

TWO KINDS OF EVIDENCE, AND THE DIFFERENCE MATTERS

    EMA/618604/2008 Rev. 13 Data set I - a REGULATOR'S PUBLISHED RESULT, from
    SAS 9.1, for the model EMA itself attributes to the FDA guidance. Note the
    authority precisely: the MODEL is FDA's, the NUMBERS are EMA-published.
    Stronger than a peer-reviewed dataset; weaker than an FDA-published example
    of FDA's own model; never described as the latter.

    ReplicateBE.jl 1.0.15 on Julia 1.10.5 - an INDEPENDENT IMPLEMENTATION
    ORACLE, WITHIN THE COVARIANCE DOMAIN IT CAN REPRESENT, frozen in PR #61
    after being verified to reproduce that same SAS output. It supplies the
    standard error and the denominator df, which EMA did not publish.

    The domain qualifier is load-bearing in general and satisfied here. PR #62
    found that ReplicateBE's correlation link cannot express the negative
    subject-by-formulation covariance FDA's FA0(2) permits, so it is not an
    oracle for such fits - see VAL-FDA-APPENDIX-C-003. Data set I fits rho =
    +1.000, comfortably inside what the oracle represents, so the comparisons
    below are valid on their own terms rather than by exception.

The second is what makes this test worth having. EMA prints two decimals; the
oracle prints full precision, so a 0.02% error in the standard error - which
two-decimal agreement would hide completely - fails here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from scipy import stats

from be_stats.appendix_c import (
    AppendixCDataset,
    analyse_replicate_abe_full,
    fit_appendix_c,
)
from be_stats.replicate import (
    ReplicateObservation,
    Treatment,
    parse_sequence,
    parse_treatment,
)

ROOT = Path(__file__).resolve().parents[2]
DATASETS = json.loads(
    (ROOT / "validation/ema/cases/ema_pkwp_qa_datasets.json").read_text("utf-8")
)
ORACLE = json.loads(
    (ROOT / "validation/appendix_c/oracle/replicatebe_frozen.json").read_text(
        "utf-8"
    )
)

#: Data set I uses letters where A is the TEST and B the reference, so ABAB is
#: TRTR. The opposite reading is the obvious guess and would invert the result.
SEQUENCE_CODES = {
    "ABAB": "TRTR",
    "BABA": "RTRT",
    "1": "TRR",
    "2": "RTR",
    "3": "RRT",
}

#: What EMA printed for Method C.
PUBLISHED_DATA_SET_I = {
    "estimate_percent": 115.66,
    "ci": (107.10, 124.89),
    "cv_wr_percent": 47.3,
    "cv_wt_percent": 35.3,
}


def observations(name: str) -> list[ReplicateObservation]:
    return [
        ReplicateObservation(
            subject_id=str(row["subject"]),
            sequence=parse_sequence(SEQUENCE_CODES[row["sequence"]]),
            period=row["period"],
            treatment=parse_treatment(row["formulation"]),
            endpoint="Cmax",
            value=row["value"],
        )
        for row in DATASETS[name]
    ]


@pytest.fixture(scope="module")
def fit_i():
    return fit_appendix_c(AppendixCDataset.build(observations("data_set_i")))


# ------------------------------------- against the regulator's own numbers ---


def test_the_point_estimate_reproduces_emas_published_method_c(fit_i):
    """Tolerance is half of the last digit EMA printed. A rounding bound, not
    a fitted one: two decimals is the strongest statement the source supports.
    """
    assert 100.0 * math.exp(fit_i.estimate) == pytest.approx(
        PUBLISHED_DATA_SET_I["estimate_percent"], abs=0.005
    )


def test_the_confidence_interval_reproduces_the_published_one(fit_i):
    """The load-bearing comparison.

    The interval depends on the estimate, the standard error AND the
    denominator df together. Reproducing it to the published precision
    therefore checks all three at once - including the Satterthwaite df, which
    EMA did not print and which nothing else in this package could confirm.
    """
    half_width = float(
        stats.t.ppf(0.95, fit_i.degrees_of_freedom)
    ) * fit_i.standard_error
    lower = 100.0 * math.exp(fit_i.estimate - half_width)
    upper = 100.0 * math.exp(fit_i.estimate + half_width)

    assert lower == pytest.approx(PUBLISHED_DATA_SET_I["ci"][0], abs=0.005)
    assert upper == pytest.approx(PUBLISHED_DATA_SET_I["ci"][1], abs=0.005)


def test_both_within_subject_cvs_reproduce(fit_i):
    """Two of the five covariance parameters, published to one decimal.

    These are what distinguish Appendix C from every nearby model: a
    single-residual-variance fit cannot produce two different numbers here at
    all.
    """
    assert fit_i.cv_within_percent(Treatment.REFERENCE) == pytest.approx(
        PUBLISHED_DATA_SET_I["cv_wr_percent"], abs=0.05
    )
    assert fit_i.cv_within_percent(Treatment.TEST) == pytest.approx(
        PUBLISHED_DATA_SET_I["cv_wt_percent"], abs=0.05
    )


# ------------------------------------------- against the frozen tier-3 oracle -


def test_the_estimate_matches_replicatebe_to_full_precision(fit_i):
    oracle = ORACLE["data_set_i"]
    assert 100.0 * math.exp(fit_i.estimate) == pytest.approx(
        oracle["estimate_percent"], abs=1e-4
    )


def test_the_standard_error_matches_replicatebe(fit_i):
    """Where the tier-3 oracle earns its place.

    EMA published no standard error, so this quantity has no regulator-facing
    check at all. Two independent implementations of the same five-parameter
    model agreeing to six decimals is the only evidence available - and it is
    evidence EMA's two printed decimals could never have supplied.
    """
    oracle = ORACLE["data_set_i"]
    assert fit_i.standard_error == pytest.approx(
        oracle["standard_error"], rel=1e-4
    )


def test_the_denominator_df_matches_replicatebe_within_a_stated_tolerance(fit_i):
    """The one quantity that does not agree exactly, with the reason.

    Python gives about 207.74 and the oracle 208.08 - a difference of 0.17%.
    Both compute the same Satterthwaite formula; they differ in how they carry
    the covariance near the boundary. ReplicateBE parameterises the correlation
    through a link, so at rho = 1 its parameter runs to infinity; this package
    parameterises G = LL', so the same point is l22 = 0, an ordinary interior
    value. Two different delicate limits of the same quantity.

    THE TOLERANCE IS DERIVED FROM WHAT df IS FOR, not from the observed gap.
    df sets the interval, so the question is how much interval a df error buys:

        t(0.95, 207.74) = 1.652263      t(0.95, 208.08) = 1.652259

    a relative difference of 2.6e-6 on the half-width, which moves the 90%
    interval by under 1e-4 percentage points. A tolerance of 1.0 df bounds that
    effect at well under a thousandth of a percentage point on the limits -
    smaller than the rounding in every published figure this is checked
    against, and far smaller than any difference that could change a decision.
    """
    oracle = ORACLE["data_set_i"]
    assert fit_i.degrees_of_freedom == pytest.approx(
        oracle["denominator_df"], abs=1.0
    )

    # And the consequence is bounded, not merely asserted to be small.
    ours = float(stats.t.ppf(0.95, fit_i.degrees_of_freedom))
    theirs = float(stats.t.ppf(0.95, oracle["denominator_df"]))
    assert abs(ours - theirs) / theirs < 1e-4


def test_the_covariance_parameters_match_replicatebe_in_its_own_coordinates(fit_i):
    """Same model, different parameterisation, same fitted covariance.

    ReplicateBE stores theta as (s2_WR, s2_WT, s2_BR, s2_BT, rho) in CSH
    coordinates; this package stores a Cholesky factor of G plus log residual
    variances. Mapping one onto the other and finding they agree is what
    demonstrates FA0(2) and CSH are the same model rather than two models that
    happen to give similar answers.
    """
    theta = ORACLE["data_set_i"]["theta"]
    var_wr, var_wt, var_br, var_bt, rho = theta

    assert fit_i.within_subject_variance_reference == pytest.approx(var_wr, rel=1e-5)
    assert fit_i.within_subject_variance_test == pytest.approx(var_wt, rel=1e-5)
    assert fit_i.between_subject_variance_reference == pytest.approx(var_br, rel=1e-4)
    assert fit_i.between_subject_variance_test == pytest.approx(var_bt, rel=1e-4)
    assert fit_i.subject_correlation == pytest.approx(rho, abs=1e-6)


# ------------------------------------------------------------- the boundary ---


def test_the_optimum_sits_on_the_correlation_boundary_and_that_is_fine(fit_i):
    """rho = 1.000 exactly, reached without bounds or clamping.

    This is the property that dictated the parameterisation. In correlation
    coordinates rho = 1 is the edge of the parameter space and an optimiser has
    to be stopped from leaving it. As G = LL' it is l22 = 0, an ordinary
    interior point of R^5 - so the optimiser walks downhill onto it and nothing
    is constrained.

    If this ever starts failing because a bound was added, the bound is the
    bug: the data set that validates this module lives on the boundary.
    """
    assert fit_i.on_correlation_boundary
    assert fit_i.subject_correlation == pytest.approx(1.0, abs=1e-6)
    assert abs(fit_i.theta[2]) < 1e-5, "l22 should have gone to zero"
    assert fit_i.converged


def test_a_boundary_solution_still_yields_a_finite_df_and_interval(fit_i):
    """The Hessian is near-singular there and the df must still exist.

    `satterthwaite_df` uses a pseudo-inverse for exactly this reason. Refusing
    to report a df on the boundary would refuse the one data set that validates
    the module, and SAS and ReplicateBE both report one.
    """
    assert math.isfinite(fit_i.degrees_of_freedom)
    assert fit_i.degrees_of_freedom > 1.0
    assert math.isfinite(fit_i.standard_error)
    assert fit_i.standard_error > 0.0


def test_the_subject_by_formulation_variance_is_derived_not_fitted(fit_i):
    """sigma^2_D = sigma^2_BT + sigma^2_BR - 2 sigma_BTBR, never a sixth
    parameter. On the boundary it collapses to (sd_BT - sd_BR)^2."""
    expected = (
        math.sqrt(fit_i.between_subject_variance_test)
        - math.sqrt(fit_i.between_subject_variance_reference)
    ) ** 2
    assert fit_i.subject_by_formulation_variance == pytest.approx(
        expected, abs=1e-9
    )
    assert len(fit_i.theta) == 5


# --------------------------------------------------------- available case ---


def test_every_incomplete_subject_is_retained(fit_i):
    """FDA section III: PROC MIXED "uses all observed data".

    Data set I has eight subjects with missing periods. Dropping them is what
    Appendix G's sWR requires and what PROC GLM would do, and either would give
    a different answer - so this is the guard that the wrong inclusion rule has
    not leaked in from a neighbouring model.
    """
    dataset = AppendixCDataset.build(observations("data_set_i"))
    assert len(dataset.observations) == 298
    assert len(dataset.subjects) == 77
    assert len(dataset.subjects_received) == 77

    incomplete = [
        d for d in dataset.diagnostics if d.code.value == "MISSING_PERIOD"
    ]
    assert len(incomplete) == 8
    assert all("RETAINED" in d.detail for d in incomplete)


def test_dropping_the_incomplete_subjects_changes_the_answer():
    """The inclusion rule is load-bearing, demonstrated rather than asserted.

    If complete-case deletion gave the same result, the rule would not matter
    and PR #60's finding would have been a curiosity. It gives a different
    interval, which is why FDA names available-case explicitly.
    """
    rows = observations("data_set_i")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.subject_id] = counts.get(r.subject_id, 0) + 1
    complete_only = [r for r in rows if counts[r.subject_id] == 4]

    full = fit_appendix_c(AppendixCDataset.build(rows))
    reduced = fit_appendix_c(AppendixCDataset.build(complete_only))

    assert len(complete_only) < len(rows)
    assert reduced.n_subjects == 69
    assert full.estimate != reduced.estimate


# ------------------------------------------- the partial replicate refusal ---


def test_the_partial_replicate_design_refuses_and_decides_nothing():
    """PR #61's conclusion, enforced.

    ReplicateBE.jl reproduces SAS exactly on the fully replicate design and
    differs by 2.94 denominator df on the partial replicate one - a design its
    own validation claim never covered. The arithmetic here would produce a
    number; there is nothing to check it against.
    """
    result = analyse_replicate_abe_full(observations("data_set_ii"))

    assert result.design_supported is False
    assert result.decided is False
    assert result.passes is None
    assert result.estimate is None
    assert result.degrees_of_freedom is None
    assert result.ci_lower_percent is None

    codes = {d.code.value for d in result.diagnostics}
    assert "APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED" in codes


def test_neither_candidate_df_is_used_as_a_partial_replicate_oracle():
    """Not 19.603, and not 22.540 either.

    The df implied by EMA's published interval and the one ReplicateBE reports
    disagree, and which is right is NOT DETERMINED. Adopting either would be
    inventing an answer. Neither number appears in the package.
    """
    import ast
    from pathlib import Path

    import be_stats.appendix_c as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    for forbidden in (19.603, 22.540, 22.5403):
        assert not any(
            abs(v - forbidden) < 1e-3 for v in literals
        ), f"{forbidden} must not appear as a constant"


def test_the_refusal_explains_itself_and_names_the_finding():
    result = analyse_replicate_abe_full(observations("data_set_ii"))
    reason = " ".join(result.provenance())
    assert "VAL-FDA-APPENDIX-C-002" in reason
    assert "NOT DETERMINED" in reason
    assert "fully replicate" in reason
