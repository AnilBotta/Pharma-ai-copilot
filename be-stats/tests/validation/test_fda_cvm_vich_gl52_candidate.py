"""The FDA-published 2x2 example that is NOT tier-1B evidence, and why.

WHAT THIS FILE IS FOR

`AVERAGE_BE_2X2` has no tier-1B evidence, and DOSSIER-003 tracks that. This
file is the record of the one candidate the search turned up that came close:
FDA's Center for Veterinary Medicine published a worked twelve-subject 2x2
crossover analysis, with the subject-level data and the resulting confidence
interval, as a supplement to VICH GL52.

be-stats reproduces it. That is worth knowing and worth keeping runnable, and
it is NOT evidence for the capability - the reasons are recorded in
`dossier.evidence_search` and asserted below so they cannot quietly erode.

WHY REPRODUCE A DOCUMENT WE ARE NOT GOING TO CITE

Two reasons, and neither is sentiment.

First, the verdict in the search registry says "be-stats reproduces the limits
and the df". A verdict nobody can re-run is an assertion, which is the exact
complaint that motivated the registry in the first place.

Second, the reproduction is what establishes that the published table contains
an arithmetic error rather than that be-stats disagrees with FDA. Those two
readings are very different, and only the arithmetic distinguishes them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from be_stats.abe import analyse_crossover
from be_stats.dossier.evidence import EVIDENCE_MANIFEST
from be_stats.dossier.evidence_search import (
    ORDINARY_ABE_TIER_1B_SEARCH,
    SearchVerdict,
)
from be_stats.dossier.statuses import EvidenceTier
from be_stats.spec import Endpoint, Jurisdiction, resolve_be_spec
from be_stats.study import CrossoverObservation, CrossoverStudy, Sequence

CASE = (
    Path(__file__).resolve().parents[2]
    / "validation"
    / "candidates"
    / "fda_cvm_vich_gl52.json"
)


@pytest.fixture(scope="module")
def case() -> dict:
    assert CASE.exists(), f"{CASE} is missing; the committed candidate is gone."
    return json.loads(CASE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observed(case) -> object:
    """Run the case through the PRODUCTION path, not a local reimplementation.

    `analyse_crossover` is the same function the package exposes and the same
    one every other 2x2 caller reaches. A test that recomputed the interval
    here would be checking arithmetic this file invented.
    """
    observations = []
    for row in case["observations"]:
        if row["sequence"] == 1:  # test first
            observations.append(
                CrossoverObservation(
                    subject=str(row["subject"]),
                    sequence=Sequence.TR,
                    period_1=row["test"],
                    period_2=row["reference"],
                )
            )
        else:
            observations.append(
                CrossoverObservation(
                    subject=str(row["subject"]),
                    sequence=Sequence.RT,
                    period_1=row["reference"],
                    period_2=row["test"],
                )
            )
    study = CrossoverStudy(endpoint="AUC", observations=observations)
    spec = resolve_be_spec(jurisdiction=Jurisdiction.FDA, endpoint=Endpoint.AUC)
    return analyse_crossover(study, spec)


# ------------------------------------------------- the reproduction itself ---


def test_be_stats_reproduces_the_published_confidence_limits(case, observed):
    """To the four decimals FDA printed on the log scale.

    The tolerance is a ROUNDING bound derived from the printed precision -
    four decimals means the true value lies within 0.00005 of what is shown -
    and not a number chosen because it makes the comparison pass.
    """
    published = case["published_output"]
    tolerance = 0.00005

    lower_log = math.log(observed.ci_lower / 100.0)
    upper_log = math.log(observed.ci_upper / 100.0)

    assert lower_log == pytest.approx(published["lower_90_limit_log"], abs=tolerance)
    assert upper_log == pytest.approx(published["upper_90_limit_log"], abs=tolerance)


def test_be_stats_reproduces_the_published_ratio_bounds(case, observed):
    """The two-decimal bounds the document derives in its own text."""
    published = case["published_output"]
    tolerance = 0.005

    assert observed.ci_lower / 100.0 == pytest.approx(
        published["lower_bound_ratio_as_printed"], abs=tolerance
    )
    assert observed.ci_upper / 100.0 == pytest.approx(
        published["upper_bound_ratio_as_printed"], abs=tolerance
    )


def test_be_stats_reproduces_the_published_denominator_df(case, observed):
    assert observed.degrees_of_freedom == case["published_output"]["denominator_df"]


def test_the_published_difference_column_is_internally_inconsistent(case):
    """The error, demonstrated from the document's own numbers alone.

    No be-stats output is used here. The published limits and the published
    standard error are compared against each other, so the conclusion holds
    whatever this package computes - which is what makes it a statement about
    the document rather than a disagreement with it.
    """
    from scipy import stats

    published = case["published_output"]
    lower = published["lower_90_limit_log"]
    upper = published["upper_90_limit_log"]
    printed_difference = published["difference_log_as_printed"]

    assert not lower <= printed_difference <= upper, (
        "The printed difference lies inside the printed limits after all; "
        "this test's premise is wrong and the record must be corrected."
    )

    midpoint = (lower + upper) / 2.0
    t_crit = stats.t.ppf(0.95, published["denominator_df"])
    implied_se = (upper - midpoint) / t_crit

    # The limits and the SE agree with each other to the printed precision.
    assert implied_se == pytest.approx(published["standard_error"], abs=5e-5)
    # And the printed difference is that midpoint with the point moved.
    assert printed_difference == pytest.approx(midpoint * 10.0, abs=5e-4)


# ----------------------------------------- and it is still not tier-1B ---


def _gl52():
    matches = [s for s in ORDINARY_ABE_TIER_1B_SEARCH if "GL52" in s.document]
    assert len(matches) == 1, "The GL52 candidate is no longer in the registry."
    return matches[0]


def test_the_candidate_is_recorded_as_out_of_scope_not_adopted():
    """The verdict, asserted where it is written down."""
    source = _gl52()

    assert source.verdict is SearchVerdict.NUMBERS_OUT_OF_SCOPE
    assert source.rejected_because.strip(), "A rejection must state its reason."
    # The two surviving reasons, each named.
    for reason in ("SCOPE", "0.1958"):
        assert reason in source.rejected_because, reason


def test_the_candidate_is_recorded_as_a_final_dated_fda_guidance():
    """THE REVIEW FINDING THIS TEST EXISTS TO PREVENT REPEATING.

    This record first read "FDA/CVM, undated; supplements VICH GL52 in draft",
    and a rejection ground was built on that. Both were wrong. The PDF's first
    line says "... VICH In Vivo Bioequivalence DRAFT Guidance GL52", which
    names the state GL52 was in when the examples were written; FDA's own
    guidance page carries a status field reading "Final", September 2014,
    docket FDA-2014-D-1352.

    A document's status is read from the issuing page's status field, never
    inferred from a phrase inside its title. That is the same rule the
    citation policy already applies to versions, and this is where it is now
    enforced for this record.
    """
    source = _gl52()

    assert "final" in source.document_version.lower(), source.document_version
    assert "2014" in source.document_version, source.document_version
    assert "GFI #224" in source.document_version or "GFI #224" in source.document

    lowered = source.document_version.lower()
    assert "undated" not in lowered, source.document_version
    assert "draft" not in lowered, (
        f"{source.document_version!r} calls the supplement a draft. It is a "
        "final FDA guidance; the word 'Draft' in the PDF's title belongs to "
        "GL52, not to this document."
    )


def test_draft_status_is_not_a_rejection_ground_for_this_candidate():
    """The false ground, kept out by assertion rather than by memory.

    Scoped to the sentence that does the rejecting. The record is allowed to
    NAME the error it used to make - and does, deliberately - so a blanket
    ban on the word would either fail on that sentence or be weakened until
    it matched nothing. What must not return is 'draft' as a REASON.
    """
    source = _gl52()
    reason = source.rejected_because

    # The correction is recorded, so the word appears. What must not appear is
    # the claim, and the count of grounds is what carries it.
    assert "Two independent reasons" in reason, (
        "The rejection no longer states two grounds. If a third has been "
        "added, it must be defensible - the last one was not."
    )
    assert "NOT a reason" in reason, (
        "The record no longer says draft status is not a reason. That "
        "sentence is what stops the ground being reinstated by someone "
        "reading the PDF's title."
    )
    assert "is NOT a draft and NOT undated" in reason, reason


def test_the_candidate_never_becomes_evidence_for_a_capability():
    """The structural half, which is what actually protects the gate.

    The reason above is prose and could be reworded. This asserts the thing
    that would let the capability claim tier-1B: an evidence record naming
    this document. There is none, and if one is ever added this fails.
    """
    for record in EVIDENCE_MANIFEST:
        haystack = " ".join(
            (record.evidence_id, record.dataset, record.scenario, record.note)
        )
        assert "GL52" not in haystack and "VICH" not in haystack, (
            f"{record.evidence_id} cites the VICH GL52 candidate. It is a "
            "veterinary draft-guidance supplement with an arithmetic error in "
            "its published table, and it does not establish a human "
            "bioequivalence capability."
        )


def test_average_be_2x2_still_holds_no_tier_1b_evidence():
    """DOSSIER-003's subject, asserted as a fact about the manifest."""
    from be_stats.dossier.evidence import evidence_for

    tier_1b = [
        r for r in evidence_for("AVERAGE_BE_2X2") if r.tier is EvidenceTier.TIER_1B
    ]
    assert not tier_1b, (
        "AVERAGE_BE_2X2 now holds tier-1B evidence. If that is intended, "
        "DOSSIER-003 needs revisiting through the governed route - and this "
        "test is where the claim gets argued, not quietly deleted."
    )
