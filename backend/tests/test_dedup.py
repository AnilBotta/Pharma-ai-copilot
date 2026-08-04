"""Deduplication and merging.

This is a correctness concern, not a cosmetic one: section confidence is derived
from how many independent sources support a claim, so counting one paper twice
inflates the apparent weight of evidence.
"""

from __future__ import annotations

from datetime import date

from app.models.records import LiteratureRecord, PatentRecord, PatentRecordType
from app.providers.dedup import (
    deduplicate_literature,
    deduplicate_patents,
    merge_literature,
    rank_by_relevance,
)


def lit(provider: str = "pubmed", title: str = "A study of peptide depot delivery", **kw):
    return LiteratureRecord(provider=provider, title=title, **kw)


def pat(number: str, **kw) -> PatentRecord:
    return PatentRecord(provider="epo_ops", publication_number=number, **kw)


class TestLiteratureDeduplication:
    def test_same_doi_across_providers_collapses(self) -> None:
        records = [
            lit("pubmed", doi="10.1016/j.x.2020.01.001"),
            lit("europepmc", doi="10.1016/j.x.2020.01.001"),
        ]
        assert len(deduplicate_literature(records)) == 1

    def test_doi_case_and_prefix_differences_still_collapse(self) -> None:
        records = [
            lit("pubmed", doi="10.1016/J.X.2020.01.001"),
            lit("europepmc", doi="https://doi.org/10.1016/j.x.2020.01.001"),
        ]
        assert len(deduplicate_literature(records)) == 1

    def test_shared_pmid_collapses_without_a_doi(self) -> None:
        records = [lit("pubmed", pmid="123456"), lit("europepmc", pmid="123456")]
        assert len(deduplicate_literature(records)) == 1

    def test_identical_titles_collapse_when_no_identifier_is_shared(self) -> None:
        records = [
            lit("pubmed", title="Carbon nanotube depot formulations for peptides", pmid="1"),
            lit("europepmc", title="Carbon Nanotube Depot Formulations for Peptides!", pmid="2"),
        ]
        assert len(deduplicate_literature(records)) == 1

    def test_short_titles_are_not_used_as_identity(self) -> None:
        # "Erratum" style titles would otherwise merge unrelated records.
        records = [
            lit("pubmed", title="Erratum", pmid="1"),
            lit("europepmc", title="Erratum", pmid="2"),
        ]
        assert len(deduplicate_literature(records)) == 2

    def test_distinct_papers_are_preserved(self) -> None:
        records = [
            lit(doi="10.1016/a.2020.01.001", title="First distinct paper title here"),
            lit(doi="10.1016/b.2020.01.002", title="Second distinct paper title here"),
        ]
        assert len(deduplicate_literature(records)) == 2

    def test_transitive_match_across_different_identifiers(self) -> None:
        # A shares a DOI with B; B shares a PMID with C. All three are one paper.
        records = [
            lit("pubmed", doi="10.1016/x.1", title="Alpha beta gamma delta epsilon"),
            lit("europepmc", doi="10.1016/x.1", pmid="999", title="Alpha beta gamma delta epsilon"),
            lit("crossref", pmid="999", title="Totally different wording of title"),
        ]
        assert len(deduplicate_literature(records)) == 1

    def test_empty_input(self) -> None:
        assert deduplicate_literature([]) == []


class TestMerging:
    def test_merge_unions_identifiers(self) -> None:
        merged = merge_literature(
            lit("pubmed", doi="10.1016/x.1", pmid="123"),
            lit("europepmc", doi="10.1016/x.1", pmcid="PMC456"),
        )
        assert (merged.doi, merged.pmid, merged.pmcid) == ("10.1016/x.1", "123", "PMC456")

    def test_merge_prefers_higher_priority_provider_for_scalars(self) -> None:
        merged = merge_literature(
            lit("europepmc", doi="10.1016/x.1", journal="EPMC journal"),
            lit("pubmed", doi="10.1016/x.1", journal="PubMed journal"),
        )
        assert merged.journal == "PubMed journal"

    def test_full_text_survives_regardless_of_provider_priority(self) -> None:
        # Europe PMC is lower priority but is the one that actually has the text.
        merged = merge_literature(
            lit("pubmed", doi="10.1016/x.1"),
            lit("europepmc", doi="10.1016/x.1", full_text="the full body"),
        )
        assert merged.full_text == "the full body"
        assert merged.has_full_text is True

    def test_merge_does_not_invent_missing_values(self) -> None:
        merged = merge_literature(lit("pubmed", pmid="1"), lit("europepmc", pmid="1"))
        assert merged.doi is None
        assert merged.journal is None

    def test_open_access_and_preprint_flags_are_disjunctive(self) -> None:
        merged = merge_literature(
            lit("pubmed", pmid="1", is_open_access=False, is_preprint=False),
            lit("europepmc", pmid="1", is_open_access=True, is_preprint=True),
        )
        assert merged.is_open_access is True
        assert merged.is_preprint is True

    def test_publication_types_are_unioned(self) -> None:
        merged = merge_literature(
            lit("pubmed", pmid="1", publication_types=["Review"]),
            lit("europepmc", pmid="1", publication_types=["Journal Article"]),
        )
        assert merged.publication_types == ["Journal Article", "Review"]


class TestPatentFamilyDeduplication:
    def test_family_members_collapse_to_one_entry(self) -> None:
        records = [
            pat("EP3123456B1", family_id="55555555"),
            pat("WO2019123456A1", family_id="55555555"),
            pat("US10123456A1", family_id="55555555"),
        ]
        result = deduplicate_patents(records)
        assert len(result) == 1

    def test_absorbed_members_remain_visible(self) -> None:
        records = [
            pat("EP3123456B1", family_id="5"),
            pat("WO2019123456A1", family_id="5"),
        ]
        [survivor] = deduplicate_patents(records)
        assert survivor.raw["family_members"] == ["EP3123456B1", "WO2019123456A1"]

    def test_granted_patent_is_chosen_over_application(self) -> None:
        application = PatentRecordType.PUBLISHED_APPLICATION
        records = [
            pat("WO2019123456A1", family_id="5", record_type=application),
            pat("EP3123456B1", family_id="5", record_type=PatentRecordType.GRANTED_PATENT),
        ]
        [survivor] = deduplicate_patents(records)
        assert survivor.publication_number == "EP3123456B1"

    def test_earliest_priority_breaks_ties(self) -> None:
        records = [
            pat("EP2A1", family_id="5", priority_date=date(2018, 1, 1)),
            pat("EP1A1", family_id="5", priority_date=date(2015, 6, 1)),
        ]
        [survivor] = deduplicate_patents(records)
        assert survivor.publication_number == "EP1A1"

    def test_separate_families_are_kept_apart(self) -> None:
        records = [pat("EP1A1", family_id="5"), pat("US2A1", family_id="7")]
        assert len(deduplicate_patents(records)) == 2

    def test_records_without_family_id_stand_alone(self) -> None:
        records = [pat("EP1A1"), pat("US2A1")]
        assert len(deduplicate_patents(records)) == 2


class TestRanking:
    def test_orders_by_supplied_score(self) -> None:
        a = lit(doi="10.1016/a.1", title="Paper A with a sufficiently long title")
        b = lit(doi="10.1016/b.2", title="Paper B with a sufficiently long title")
        ranked = rank_by_relevance([a, b], {"10.1016/a.1": 0.2, "10.1016/b.2": 0.9})
        assert [r.doi for r in ranked] == ["10.1016/b.2", "10.1016/a.1"]

    def test_unscored_records_sort_last_but_are_not_dropped(self) -> None:
        a = lit(doi="10.1016/a.1", title="Paper A with a sufficiently long title")
        b = lit(doi="10.1016/b.2", title="Paper B with a sufficiently long title")
        ranked = rank_by_relevance([a, b], {"10.1016/a.1": 0.5})
        assert len(ranked) == 2
        assert ranked[0].doi == "10.1016/a.1"
