"""Graph routing and the end-to-end research workflow.

The workflow tests run the real compiled graph. Only the network boundary is
faked, so routing, parallel fan-out, evidence allocation, citation validation
and report assembly are all production code under test.
"""

from __future__ import annotations

import pytest
from langgraph.graph import END

from app.graph.context import MemoryEventSink, RunContext
from app.graph.evidence import allocate_markers, marker_block_start, next_marker_index
from app.graph.graph import (
    NODE_SEQUENCE,
    build_graph,
    progress_for,
    route_after_intake,
    route_after_planning,
    route_after_verification,
)
from app.graph.state import ResearchState, evidence_markers, initial_state
from app.models.agents import StructuredObjective, VerificationReport
from tests.fakes import (
    FakeLiteratureProvider,
    FakeModelProvider,
    FakePatentProvider,
    sample_literature,
    sample_patents,
)

QUESTION = (
    "Evaluate the feasibility of a sustained-release depot injection of a "
    "therapeutic peptide using carbon nanotube-based delivery technology."
)


def make_state(**overrides) -> ResearchState:
    state = initial_state(
        run_id="run-1",
        user_id="user-1",
        project_id="project-1",
        original_question=QUESTION,
        max_results=10,
    )
    state.update(overrides)
    return state


def make_context(
    *,
    models: FakeModelProvider | None = None,
    literature: list | None = None,
    patents: list | None = None,
    events: MemoryEventSink | None = None,
) -> RunContext:
    return RunContext(
        models=models or FakeModelProvider(),  # type: ignore[arg-type]
        literature_providers=literature if literature is not None else [FakeLiteratureProvider()],
        patent_providers=patents if patents is not None else [FakePatentProvider()],
        events=events or MemoryEventSink(),
    )


async def run_workflow(context: RunContext, state: ResearchState | None = None) -> dict:
    graph = build_graph(context)
    return await graph.ainvoke(state or make_state())


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


class TestRouting:
    def test_missing_objective_aborts(self) -> None:
        assert route_after_intake(make_state(structured_objective=None)) == "abort"

    def test_fatal_error_aborts_even_with_an_objective(self) -> None:
        state = make_state(
            structured_objective=StructuredObjective(
                restated_objective="x", research_questions=["q"]
            ),
            errors=[{"node": "intake", "provider": None, "error_type": "model_error",
                     "message": "boom", "is_fatal": True}],
        )
        assert route_after_intake(state) == "abort"

    def test_valid_objective_proceeds_to_planning(self) -> None:
        state = make_state(
            structured_objective=StructuredObjective(
                restated_objective="x", research_questions=["q"]
            )
        )
        assert route_after_intake(state) == "plan"

    def test_missing_plan_aborts(self) -> None:
        assert route_after_planning(make_state(research_plan=None)) == [END]

    def test_valid_plan_fans_out_to_every_specialist(self) -> None:
        """Including the document branch, whether or not the project has uploads.

        It is scheduled unconditionally and returns immediately when there is
        nothing to search. A graph whose shape depended on the data would be
        harder to reason about, and would make the fan-in edge conditional.
        """
        from app.models.agents import ResearchPlan

        state = make_state(research_plan=ResearchPlan(approach="x"))
        destinations = route_after_planning(state)
        assert set(destinations) == {
            "research_agent",
            "literature_agent",
            "patent_agent",
            "document_agent",
        }

    def test_verification_failure_requests_revision(self) -> None:
        state = make_state(
            verification=VerificationReport(
                issues=[], section_confidence=[], contradictions=[],
                requires_revision=True, overall_note="",
            )
        )
        assert route_after_verification(state) == "revise"

    def test_clean_verification_finalises(self) -> None:
        state = make_state(
            verification=VerificationReport(
                issues=[], section_confidence=[], contradictions=[],
                requires_revision=False, overall_note="",
            )
        )
        assert route_after_verification(state) == "finalise"

    def test_absent_verification_finalises_rather_than_looping(self) -> None:
        assert route_after_verification(make_state(verification=None)) == "finalise"


class TestProgress:
    def test_progress_derives_from_node_position(self) -> None:
        assert progress_for(NODE_SEQUENCE[0]) < progress_for(NODE_SEQUENCE[-1])
        assert progress_for(NODE_SEQUENCE[-1]) == 100

    def test_unknown_node_is_zero(self) -> None:
        assert progress_for("not_a_node") == 0


class TestMarkerAllocation:
    def test_markers_are_sequential(self) -> None:
        assert allocate_markers(1, 3) == ["E1", "E2", "E3"]

    def test_next_index_continues_after_existing(self) -> None:
        existing = [{"marker": "E1"}, {"marker": "E7"}]
        assert next_marker_index(existing) == 8  # type: ignore[arg-type]

    def test_next_index_starts_at_one_when_empty(self) -> None:
        assert next_marker_index([]) == 1

    def test_concurrent_branches_get_disjoint_blocks(self) -> None:
        # Regression: both branches observe the same pre-fan-out state, so
        # deriving a start index from allocated-so-far returned 1 in each and
        # produced two sets of E1, E2, ...
        lit = allocate_markers(marker_block_start("literature_agent", 50), 50)
        pat = allocate_markers(marker_block_start("patent_agent", 50), 50)
        assert set(lit).isdisjoint(pat)

    def test_block_start_is_stable_for_a_given_agent(self) -> None:
        assert marker_block_start("literature_agent", 50) == marker_block_start(
            "literature_agent", 50
        )

    def test_literature_block_starts_at_one(self) -> None:
        assert marker_block_start("literature_agent", 50) == 1

    def test_unknown_agent_gets_its_own_block(self) -> None:
        known = {
            marker_block_start(a, 10)
            for a in ("literature_agent", "patent_agent", "document_agent")
        }
        assert marker_block_start("some_future_agent", 10) not in known


# --------------------------------------------------------------------------- #
# End-to-end workflow
# --------------------------------------------------------------------------- #


class TestWorkflow:
    async def test_full_run_completes_and_produces_a_report(self) -> None:
        result = await run_workflow(make_context())

        assert result["report"] is not None
        assert result["structured_objective"] is not None
        assert result["research_plan"] is not None
        assert result["development_strategy"] is not None
        assert result["verification"] is not None

    async def test_every_node_runs(self) -> None:
        events = MemoryEventSink()
        await run_workflow(make_context(events=events))
        started = {e["node"] for e in events.of_type("node_started")}
        for node in NODE_SEQUENCE:
            assert node in started, f"{node} did not run"

    async def test_specialist_agents_all_contribute(self) -> None:
        result = await run_workflow(make_context())
        assert result["background_summary"] is not None
        assert result["literature_findings"] is not None
        assert result["patent_findings"] is not None

    async def test_evidence_is_created_from_both_source_types(self) -> None:
        result = await run_workflow(make_context())
        kinds = {e["source_type"] for e in result["evidence_records"]}
        assert kinds == {"literature", "patent"}

    async def test_evidence_markers_are_unique_across_parallel_branches(self) -> None:
        result = await run_workflow(make_context())
        markers = [e["marker"] for e in result["evidence_records"]]
        assert len(markers) == len(set(markers))

    async def test_search_queries_are_recorded(self) -> None:
        result = await run_workflow(make_context())
        providers = {q["provider"] for q in result["search_queries"]}
        assert providers == {"pubmed", "epo_ops"}

    async def test_report_contains_every_required_section(self) -> None:
        from app.models.agents import SECTION_TITLES

        result = await run_workflow(make_context())
        produced = {s.section_key for s in result["report"].sections}
        assert set(SECTION_TITLES) <= produced

    async def test_references_section_is_built_from_stored_evidence(self) -> None:
        result = await run_workflow(make_context())
        references = next(
            s for s in result["report"].sections if s.section_key == "references"
        )
        for entry in result["evidence_records"]:
            assert f"[{entry['marker']}]" in references.body_markdown

    async def test_disclaimers_are_present(self) -> None:
        result = await run_workflow(make_context())
        limitations = next(
            s for s in result["report"].sections if s.section_key == "limitations"
        )
        assert "not a legal opinion" in limitations.body_markdown
        assert "does not provide medical" in limitations.body_markdown

    async def test_contradictions_are_carried_through(self) -> None:
        result = await run_workflow(make_context())
        assert result["contradictions"]

    async def test_section_confidence_is_computed(self) -> None:
        result = await run_workflow(make_context())
        assert result["section_confidence"]
        assert all(
            v in {"high", "moderate", "low", "insufficient_evidence"}
            for v in result["section_confidence"].values()
        )

    async def test_progress_events_reflect_real_work(self) -> None:
        events = MemoryEventSink()
        await run_workflow(make_context(events=events))
        # Provider results are emitted from actual search returns, not a timer.
        assert events.of_type("provider_result")
        assert events.of_type("evidence_stored")


# --------------------------------------------------------------------------- #
# Citation integrity, end to end
# --------------------------------------------------------------------------- #


class TestCitationIntegrityEndToEnd:
    async def test_hallucinated_citation_never_reaches_the_report(self) -> None:
        # The model cites E999, which was never retrieved.
        models = FakeModelProvider(citation_override=["E999"])
        result = await run_workflow(make_context(models=models))

        body = "\n".join(s.body_markdown for s in result["report"].sections)
        assert "E999" not in body
        assert "[unverified citation removed]" in body

    async def test_stripped_citations_are_surfaced_as_warnings(self) -> None:
        models = FakeModelProvider(citation_override=["E999"])
        result = await run_workflow(make_context(models=models))
        assert any("never retrieved" in w for w in result["warnings"])

    async def test_reviewer_flags_the_unresolvable_citation(self) -> None:
        models = FakeModelProvider(citation_override=["E999"])
        result = await run_workflow(make_context(models=models))
        issues = result["verification"].issues
        assert any(i.issue_type == "unresolvable_citation" for i in issues)

    async def test_every_marker_in_the_report_resolves_to_stored_evidence(self) -> None:
        from app.llm.citations import extract_markers

        result = await run_workflow(make_context())
        known = evidence_markers(result)
        for section in result["report"].sections:
            for marker in extract_markers(section.body_markdown):
                assert marker in known, f"{marker} does not resolve"


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #


class TestHonestDegradation:
    async def test_unconfigured_patent_provider_does_not_stop_the_run(self) -> None:
        context = make_context(patents=[FakePatentProvider(configured=False)])
        result = await run_workflow(context)

        assert result["report"] is not None
        assert result["patent_search_unavailable"] is True
        assert result["patent_results"] == []

    async def test_unavailable_patents_are_stated_not_implied_absent(self) -> None:
        context = make_context(patents=[FakePatentProvider(configured=False)])
        result = await run_workflow(context)
        limitations = next(
            s for s in result["report"].sections if s.section_key == "limitations"
        )
        assert "No patent search was performed" in limitations.body_markdown
        assert "not evidence that" in limitations.body_markdown

    async def test_failed_patent_search_records_an_honest_error(self) -> None:
        context = make_context(
            patents=[FakePatentProvider(fail_with="EPO OPS returned 503")]
        )
        result = await run_workflow(context)
        assert any("503" in e["message"] for e in result["errors"])
        assert result["patent_results"] == []

    async def test_failed_literature_search_yields_no_substituted_records(self) -> None:
        context = make_context(
            literature=[FakeLiteratureProvider(fail_with="PubMed unavailable")]
        )
        result = await run_workflow(context)
        assert result["literature_results"] == []
        assert result["no_literature_found"] is True
        assert any("unavailable" in w for w in result["warnings"])

    async def test_run_completes_with_no_sources_at_all(self) -> None:
        context = make_context(
            literature=[FakeLiteratureProvider(fail_with="down")],
            patents=[FakePatentProvider(configured=False)],
        )
        result = await run_workflow(context)

        assert result["report"] is not None
        assert result["evidence_records"] == []
        references = next(
            s for s in result["report"].sections if s.section_key == "references"
        )
        assert "No sources were retrieved" in references.body_markdown

    async def test_one_failed_provider_does_not_lose_the_other(self) -> None:
        context = make_context(
            literature=[
                FakeLiteratureProvider("pubmed", fail_with="down"),
                FakeLiteratureProvider("europepmc", records=sample_literature(2, "europepmc")),
            ]
        )
        result = await run_workflow(context)
        assert len(result["literature_results"]) == 2
        assert any(e["provider"] == "pubmed" for e in result["errors"])

    async def test_strategy_failure_still_produces_a_report(self) -> None:
        from app.models.agents import DevelopmentStrategy

        models = FakeModelProvider(fail_on={DevelopmentStrategy})
        result = await run_workflow(make_context(models=models))

        assert result["report"] is not None
        assert result["development_strategy"] is None
        assert any("could not be produced" in w for w in result["warnings"])

    async def test_fatal_intake_failure_aborts_without_a_report(self) -> None:
        models = FakeModelProvider(fail_on={StructuredObjective})
        result = await run_workflow(make_context(models=models))

        assert result.get("report") is None
        assert any(e["is_fatal"] for e in result["errors"])


class TestQueryRouting:
    """Regression guards for a defect the first live run exposed.

    All ten planned queries were written in PubMed syntax and sent to both
    providers. PubMed returned six usable records; Europe PMC returned zero for
    all ten, because `[tiab]` and `[MeSH]` mean nothing to it. An entire
    provider contributed nothing, and it was invisible because zero results is
    a legitimate outcome.
    """

    def test_each_query_goes_only_to_its_named_provider(self) -> None:
        from app.graph.nodes.literature import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            literature_searches=[
                PlannedSearch(provider="pubmed", query="peptide[tiab]", rationale="r"),
                PlannedSearch(
                    provider="europepmc", query="TITLE_ABS:peptide", rationale="r"
                ),
            ],
        )
        providers = [FakeLiteratureProvider("pubmed"), FakeLiteratureProvider("europepmc")]

        routed = _queries_by_provider(plan, providers, "fallback")
        assert routed["pubmed"] == ["peptide[tiab]"]
        assert routed["europepmc"] == ["TITLE_ABS:peptide"]

    def test_provider_with_no_queries_falls_back_rather_than_idling(self) -> None:
        from app.graph.nodes.literature import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            literature_searches=[
                PlannedSearch(provider="pubmed", query="peptide[tiab]", rationale="r")
            ],
        )
        providers = [FakeLiteratureProvider("pubmed"), FakeLiteratureProvider("europepmc")]

        routed = _queries_by_provider(plan, providers, "the original question")
        assert routed["europepmc"] == ["the original question"]

    def test_unknown_provider_name_goes_to_all_rather_than_being_dropped(self) -> None:
        from app.graph.nodes.literature import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            literature_searches=[
                PlannedSearch(provider="scopus", query="peptide", rationale="r")
            ],
        )
        providers = [FakeLiteratureProvider("pubmed"), FakeLiteratureProvider("europepmc")]

        routed = _queries_by_provider(plan, providers, "fallback")
        assert routed["pubmed"] == ["peptide"]
        assert routed["europepmc"] == ["peptide"]


class TestPatentQueryRouting:
    """Regression guards for the patent-side twin of `TestQueryRouting` above.

    A live run's planner put four Europe PMC queries (`TITLE_ABS:` syntax,
    correctly labelled `provider="europepmc"`) into `patent_searches` alongside
    five EPO OPS queries. `patent_agent` sent every one of the nine to EPO OPS
    regardless of the label, because nothing read it. Live, that produced
    `CLIENT.InvalidIndex` (400) for the mis-routed queries, and once one also
    carried two NOT clauses, `CLIENT.NotOperatorMaxNumber` (413).

    This differs from the literature case in one deliberate way: an unnamed
    provider still broadcasts (there is nothing to route it by), but a query
    naming a provider that plainly is not a patent provider must be DROPPED,
    not broadcast — broadcasting is what caused the incident, since the only
    configured patent provider received it anyway.
    """

    def test_each_query_goes_only_to_its_named_provider(self) -> None:
        from app.graph.nodes.patents import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            patent_searches=[
                PlannedSearch(provider="epo_ops", query='ti="peptide"', rationale="r"),
                PlannedSearch(
                    provider="europepmc", query="TITLE_ABS:peptide", rationale="r"
                ),
            ],
        )
        providers = [FakePatentProvider("epo_ops")]

        routed = _queries_by_provider(plan, providers, "fallback")
        assert routed["epo_ops"] == ['ti="peptide"']

    def test_a_query_naming_a_non_patent_provider_is_dropped_not_broadcast(self) -> None:
        """The behaviour that would have prevented the incident: forwarding a
        query in a dialect no patent provider understands is worse than
        skipping it, because it is guaranteed to fail rather than merely
        possibly waste a query."""
        from app.graph.nodes.patents import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            patent_searches=[
                PlannedSearch(
                    provider="europepmc", query="TITLE_ABS:peptide", rationale="r"
                ),
                PlannedSearch(provider="epo_ops", query='ti="peptide"', rationale="r"),
            ],
        )
        providers = [FakePatentProvider("epo_ops")]

        routed = _queries_by_provider(plan, providers, "fallback")
        assert routed["epo_ops"] == ['ti="peptide"']
        assert "TITLE_ABS:peptide" not in routed["epo_ops"]

    def test_an_unlabelled_query_still_broadcasts(self) -> None:
        from app.graph.nodes.patents import _queries_by_provider
        from app.models.agents import PlannedSearch, ResearchPlan

        plan = ResearchPlan(
            approach="x",
            patent_searches=[
                PlannedSearch(provider="", query="peptide depot", rationale="r")
            ],
        )
        providers = [FakePatentProvider("epo_ops")]

        routed = _queries_by_provider(plan, providers, "fallback")
        assert routed["epo_ops"] == ["peptide depot"]

    def test_provider_with_no_matching_queries_falls_back_rather_than_idling(self) -> None:
        from app.graph.nodes.patents import _queries_by_provider
        from app.models.agents import ResearchPlan

        plan = ResearchPlan(approach="x", patent_searches=[])
        providers = [FakePatentProvider("epo_ops")]

        routed = _queries_by_provider(plan, providers, "the original question")
        assert routed["epo_ops"] == ["the original question"]

    async def test_providers_receive_only_their_own_queries_end_to_end(self) -> None:
        from app.models.agents import PlannedSearch, ResearchPlan

        pubmed = FakeLiteratureProvider("pubmed")
        epmc = FakeLiteratureProvider("europepmc", records=sample_literature(2, "europepmc"))

        models = FakeModelProvider(
            responses={
                ResearchPlan: ResearchPlan(
                    approach="x",
                    literature_searches=[
                        PlannedSearch(
                            provider="pubmed", query="PUBMED-ONLY[tiab]", rationale="r"
                        ),
                        PlannedSearch(
                            provider="europepmc",
                            query="TITLE_ABS:EPMC-ONLY",
                            rationale="r",
                        ),
                    ],
                )
            }
        )

        await run_workflow(make_context(models=models, literature=[pubmed, epmc]))

        assert pubmed.searches == ["PUBMED-ONLY[tiab]"]
        assert epmc.searches == ["TITLE_ABS:EPMC-ONLY"]


class TestDeduplicationInWorkflow:
    async def test_same_paper_from_two_providers_counts_once(self) -> None:
        shared = sample_literature(2, "pubmed")
        duplicate = [r.model_copy(update={"provider": "europepmc"}) for r in shared]
        context = make_context(
            literature=[
                FakeLiteratureProvider("pubmed", records=shared),
                FakeLiteratureProvider("europepmc", records=duplicate),
            ]
        )
        result = await run_workflow(context)
        assert len(result["literature_results"]) == 2

    async def test_patent_family_members_collapse(self) -> None:
        patents = sample_patents(2)
        same_family = [p.model_copy(update={"family_id": "SHARED"}) for p in patents]
        context = make_context(patents=[FakePatentProvider(records=same_family)])
        result = await run_workflow(context)
        assert len(result["patent_results"]) == 1


class TestCancellation:
    async def test_cancelled_run_stops_producing_work(self) -> None:
        context = make_context()
        context.is_cancelled = _always_cancelled
        result = await run_workflow(context)

        assert result.get("report") is None
        assert any("cancelled" in w.lower() for w in result["warnings"])


async def _always_cancelled() -> bool:
    return True


@pytest.mark.parametrize("max_results", [1, 5, 25])
async def test_max_results_is_respected(max_results: int) -> None:
    context = make_context(
        literature=[FakeLiteratureProvider(records=sample_literature(30))]
    )
    result = await run_workflow(context, make_state(max_results=max_results))
    assert len(result["literature_results"]) <= max_results
