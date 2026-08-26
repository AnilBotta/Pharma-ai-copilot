"""Two adjacent numbers that mean different things, and must stay apart.

FDA's highly-variable-drug procedure involves two figures within 0.0005 of each
other that answer entirely different questions:

    CV >= 30%       does this drug COUNT as highly variable?
    sWR >= 0.294    which ANALYSIS applies to the data actually collected?

The second is not a rounded presentation of the first. It is the regulator's
own criterion, written in the guidance, and applied to an estimate of sWR from
a replicate study rather than to an assumed population CV.

This file exists because the package once got that wrong in the direction that
usually looks like rigour. Having noticed that sqrt(ln(1 + 0.30^2)) = 0.293560,
an earlier version derived the switching threshold from the classification CV,
marked it DERIVED, and added an AST-level test forbidding `0.294` from
appearing in the source at all. The arithmetic was correct; the software
conclusion was not. Substituting a self-computed 0.293560 for FDA's stated
0.294 replaces the regulator's criterion with the package's own, and moves the
method boundary for every study whose estimated sWR lands in between.

So the tests below assert the opposite of what that guard asserted.
"""

from __future__ import annotations

import math

import pytest

from be_stats.conversions import cv_to_log_sd
from be_stats.provenance import VerificationStatus
from be_stats.spec import (
    FDA_HVD_CONSTANTS,
    Method,
    fda_hvd_method_for,
    fda_hvd_theta,
)


def test_the_switching_threshold_is_the_regulators_value():
    swr = FDA_HVD_CONSTANTS["swr_switching_threshold"]
    assert swr.value == 0.294
    assert swr.verification is VerificationStatus.VERIFIED
    assert "Appendix G" in swr.citation.section


def test_the_classification_threshold_is_a_cv_and_a_different_number():
    cv = FDA_HVD_CONSTANTS["classification_cv"]
    assert cv.value == 0.30
    assert cv.verification is VerificationStatus.VERIFIED
    assert cv.citation.section == "III.C"
    assert cv.value != FDA_HVD_CONSTANTS["swr_switching_threshold"].value


def test_the_switching_threshold_is_not_derived_from_the_classification_cv():
    """The correction, asserted rather than described.

    If somebody re-derives the threshold, this fails: the derived value is
    0.293560 and would no longer equal the guidance figure.
    """
    swr = FDA_HVD_CONSTANTS["swr_switching_threshold"]
    assert swr.verification is not VerificationStatus.DERIVED
    derived = cv_to_log_sd(FDA_HVD_CONSTANTS["classification_cv"].value)
    assert swr.value != pytest.approx(derived, abs=1e-6)
    assert derived == pytest.approx(0.293560, abs=5e-7)


def test_every_hvd_constant_carries_a_citation_and_a_verification():
    for name, value in FDA_HVD_CONSTANTS.items():
        assert value.citation.authority == "FDA", name
        assert value.citation.document_version, name
        assert value.verification is VerificationStatus.VERIFIED, name
        # How it was checked is part of the record, not only whether.
        assert value.verified_by, name


def test_the_decision_rule_switches_exactly_at_the_guidance_figure():
    """Below, ordinary ABE. At or above, reference scaling. No third answer.

    0.2939 and 0.2941 straddle the threshold by a ten-thousandth; 0.294 itself
    is the boundary case, and the guidance criterion is `>=`, so it scales.
    """
    assert fda_hvd_method_for(0.2939) is Method.STANDARD_ABE
    assert fda_hvd_method_for(0.294) is Method.FDA_HVD_RSABE
    assert fda_hvd_method_for(0.2941) is Method.FDA_HVD_RSABE


def test_the_derived_value_would_have_moved_that_boundary():
    """Names the studies the earlier mistake would have misrouted.

    An estimated sWR of 0.2937 sits above sqrt(ln(1 + 0.30^2)) and below FDA's
    0.294. Under the guidance it stays on ordinary average BE; under the
    derivation it would have been reference-scaled. Different tests, different
    acceptance criteria, one of them not the regulator's.
    """
    between = 0.2937
    derived = cv_to_log_sd(0.30)
    assert derived < between < FDA_HVD_CONSTANTS["swr_switching_threshold"].value
    assert fda_hvd_method_for(between) is Method.STANDARD_ABE


def test_a_negative_reference_sd_is_refused_rather_than_routed():
    with pytest.raises(ValueError):
        fda_hvd_method_for(-0.01)


def test_theta_follows_from_sigma_w0_and_is_not_stored():
    """The scaling constant genuinely is a derivation, and is marked as one.

    theta = (ln(1.25) / sigma_w0)^2 with sigma_w0 = 0.25. Unlike the switching
    threshold, this one is a formula the guidance states, so computing it is
    reproducing the guidance rather than second-guessing it.
    """
    sigma_w0 = FDA_HVD_CONSTANTS["sigma_w0"].value
    assert sigma_w0 == 0.25
    assert fda_hvd_theta() == pytest.approx((math.log(1.25) / 0.25) ** 2, rel=1e-15)
    assert fda_hvd_theta() == pytest.approx(0.7967, abs=5e-5)


def test_the_point_estimate_constraint_is_carried_alongside_the_scaling():
    """RSABE is not the scaled criterion on its own.

    Reducing FDA's HVD procedure to "expanded limits" drops the requirement
    that the point estimate itself falls within 80.00-125.00%. Both constants
    are present so the Phase 2A implementation cannot quietly omit it.
    """
    assert FDA_HVD_CONSTANTS["point_estimate_lower"].value == 0.8000
    assert FDA_HVD_CONSTANTS["point_estimate_upper"].value == 1.2500
