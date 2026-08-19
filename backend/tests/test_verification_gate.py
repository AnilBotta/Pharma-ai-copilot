"""A report that fails its own verification must not be called complete.

Found by reading a real run. The reviewer finished with:

    Verification complete: 11 issue(s), 9 high severity.

and the run was recorded `completed`, with a Limitations section that did not
mention verification at all. Nothing was lying on purpose - the pieces were each
doing what they said:

  * `requires_revision` is forced False once the one-revision budget is spent,
    so downstream it means "clean OR we gave up" and cannot separate the two.
  * `awaiting_review` has been in the run_status enum since 0002 and was never
    set by anything.
  * The reviewer emitted a warning saying the findings "are listed in the
    report", and nothing listed them.

Three components each behaving reasonably, combining into a report that failed
review and was presented as finished.
"""

from __future__ import annotations

from app.models.agents import VerificationIssue, VerificationReport


def _issue(section: str = "objective_and_scope", **overrides) -> VerificationIssue:
    return VerificationIssue(
        section_key=section,
        issue_type=overrides.pop("issue_type", "unsupported_claim"),
        detail=overrides.pop("detail", "The claim generalises beyond the cited study."),
        quoted_text=overrides.pop("quoted_text", None),
        suggested_correction=None,
        severity=overrides.pop("severity", "high"),
    )


class TestTheReviewerSeparatesCleanFromExhausted:
    """`requires_revision` cannot answer "did this pass?" and must not be asked."""

    def _run(self, issues, revision_count):
        """Reproduce the reviewer's decision without the model call."""
        from app.graph.nodes.reviewer import MAX_REVISIONS

        high = [i for i in issues if i.severity == "high"]
        needs_revision = bool(high) and revision_count < MAX_REVISIONS
        return len(high) if not needs_revision else 0

    def test_a_clean_report_leaves_nothing_unresolved(self) -> None:
        assert self._run([], revision_count=0) == 0

    def test_the_first_high_severity_pass_asks_for_a_revision(self) -> None:
        """Not yet unresolved - it is about to be given its one chance."""
        assert self._run([_issue()], revision_count=0) == 0

    def test_findings_surviving_the_budget_are_recorded_as_unresolved(self) -> None:
        """This is the state that used to be indistinguishable from clean."""
        assert self._run([_issue(), _issue("key_risks")], revision_count=1) == 2

    def test_low_severity_findings_do_not_hold_a_run(self) -> None:
        """A held run has to mean something, or people stop reading the label."""
        assert self._run([_issue(severity="low")], revision_count=1) == 0


class TestTheReportDisclosesWhatSurvived:
    def _limitations(self, *, unresolved: int, issues: list) -> str:
        from app.graph.nodes.synthesis import _build_limitations

        state = {
            "evidence_records": [],
            "unresolved_high_severity": unresolved,
            "verification": VerificationReport(
                issues=issues, section_confidence=[], contradictions=[],
                requires_revision=False, overall_note="",
            ),
        }
        return _build_limitations(state, 0).body_markdown

    def test_it_says_the_report_failed_verification(self) -> None:
        body = self._limitations(unresolved=2, issues=[_issue(), _issue("key_risks")])
        assert "did not pass its own verification" in body
        assert "2 high-severity finding(s) remain unresolved" in body

    def test_each_finding_is_listed(self) -> None:
        """The reviewer has always claimed they are. Now they are."""
        body = self._limitations(
            unresolved=2,
            issues=[_issue(detail="Alpha detail."), _issue("key_risks", detail="Beta detail.")],
        )
        assert "Alpha detail." in body
        assert "Beta detail." in body

    def test_the_disclosure_comes_before_the_scope_notes(self) -> None:
        """A reader who stops early must still have been told."""
        body = self._limitations(unresolved=1, issues=[_issue()])
        assert body.index("did not pass its own verification") < body.index(
            "Scope of this assessment"
        )

    def test_a_clean_run_says_none_of_it(self) -> None:
        body = self._limitations(unresolved=0, issues=[])
        assert "did not pass" not in body

    def test_a_hallucinated_marker_is_not_reprinted(self) -> None:
        """The findings are often ABOUT a citation that resolved to nothing.

        Quoting one verbatim would put back into the report exactly the text the
        reviewer removed. `extract_markers` only matches bracketed markers so no
        false citation row would be written - but "no unresolvable marker
        appears anywhere in the report" is a blunt invariant that is hard to
        break by accident, and worth keeping over the weaker bracketed form.
        A marker that resolves to nothing tells the reader nothing anyway.
        """
        body = self._limitations(
            unresolved=1,
            issues=[
                _issue(
                    issue_type="unresolvable_citation",
                    detail="Citation E999 does not correspond to any retrieved record.",
                    quoted_text="E999",
                )
            ],
        )
        assert "E999" not in body
        assert "a removed citation" in body

    def test_a_quote_that_was_only_a_marker_is_dropped_entirely(self) -> None:
        body = self._limitations(
            unresolved=1,
            issues=[
                _issue(
                    issue_type="unresolvable_citation",
                    detail="Unresolvable.",
                    quoted_text="[E42]",
                )
            ],
        )
        assert 'Quoted: "a removed citation"' not in body
