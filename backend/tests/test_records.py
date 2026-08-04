"""Normalisation rules on the shared record models.

These carry real weight: identifier normalisation is what makes cross-provider
deduplication work, and access_level is what stops the report claiming full text
was reviewed when only an abstract was retrieved.
"""

from __future__ import annotations

import pytest

from app.models.records import (
    AccessLevel,
    LiteratureRecord,
    PatentRecord,
    PatentRecordType,
    SearchFilters,
)


def lit(**kwargs) -> LiteratureRecord:
    return LiteratureRecord(provider="pubmed", title="A title", **kwargs)


class TestDOINormalisation:
    @pytest.mark.parametrize(
        "raw",
        [
            "10.1016/j.biomaterials.2015.08.045",
            "https://doi.org/10.1016/j.biomaterials.2015.08.045",
            "http://doi.org/10.1016/j.biomaterials.2015.08.045",
            "doi:10.1016/j.biomaterials.2015.08.045",
            "  10.1016/J.BIOMATERIALS.2015.08.045  ",
        ],
    )
    def test_equivalent_forms_collapse_to_one_key(self, raw: str) -> None:
        assert lit(doi=raw).doi == "10.1016/j.biomaterials.2015.08.045"

    @pytest.mark.parametrize("raw", ["not-a-doi", "12.3456/x", "", "10.1016"])
    def test_malformed_doi_is_dropped_not_stored(self, raw: str) -> None:
        # Storing a malformed DOI would produce a citation link that resolves
        # to nothing, so it is discarded instead.
        assert lit(doi=raw).doi is None


class TestIdentifierNormalisation:
    def test_pmid_is_bare_digits(self) -> None:
        assert lit(pmid=" 26414409 ").pmid == "26414409"

    @pytest.mark.parametrize("raw", ["PMC26414409", "abc", "26414409x"])
    def test_non_numeric_pmid_is_rejected(self, raw: str) -> None:
        # Regression: an earlier validator prefixed "PMC" onto long PMIDs,
        # turning PMID 26414409 into the non-existent identifier PMC26414409.
        assert lit(pmid=raw).pmid is None

    @pytest.mark.parametrize("raw", ["PMC4610009", "pmc4610009", "4610009"])
    def test_pmcid_prefix_is_normalised_on(self, raw: str) -> None:
        assert lit(pmcid=raw).pmcid == "PMC4610009"

    def test_non_numeric_pmcid_is_rejected(self) -> None:
        assert lit(pmcid="PMCabc").pmcid is None


class TestAccessLevel:
    def test_full_text_only_when_text_present(self) -> None:
        assert lit(full_text="body", abstract="a").access_level is AccessLevel.FULL_TEXT

    def test_abstract_only_when_no_body(self) -> None:
        assert lit(abstract="a").access_level is AccessLevel.ABSTRACT_ONLY

    def test_metadata_only_when_neither(self) -> None:
        assert lit().access_level is AccessLevel.METADATA_ONLY

    def test_whitespace_full_text_does_not_count_as_full_text(self) -> None:
        assert lit(full_text="   ", abstract="a").access_level is AccessLevel.ABSTRACT_ONLY

    def test_open_access_flag_does_not_imply_full_text(self) -> None:
        # Knowing a paper is open access is not the same as having retrieved it.
        assert lit(abstract="a", is_open_access=True).access_level is AccessLevel.ABSTRACT_ONLY


class TestURLDerivation:
    def test_url_is_built_from_verified_doi(self) -> None:
        assert lit(doi="10.1016/x").best_url == "https://doi.org/10.1016/x"

    def test_falls_back_through_identifier_hierarchy(self) -> None:
        assert lit(pmid="123").best_url == "https://pubmed.ncbi.nlm.nih.gov/123/"
        assert lit(pmcid="PMC9").best_url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9/"

    def test_no_identifier_yields_no_invented_url(self) -> None:
        assert lit().best_url is None


class TestIdentifierRequirement:
    def test_record_without_identifier_is_not_usable_as_evidence(self) -> None:
        assert lit().has_identifier is False

    @pytest.mark.parametrize(
        "kwargs",
        [{"doi": "10.1016/x"}, {"pmid": "1"}, {"pmcid": "PMC1"}, {"url": "https://e.org/a"}],
    )
    def test_any_single_identifier_suffices(self, kwargs: dict) -> None:
        assert lit(**kwargs).has_identifier is True


class TestPatentNormalisation:
    @pytest.mark.parametrize(
        "raw", ["EP3123456B1", "ep 3123456 b1", "EP-3123456-B1", "ep/3123456/b1"]
    )
    def test_publication_number_forms_collapse(self, raw: str) -> None:
        record = PatentRecord(provider="epo_ops", publication_number=raw)
        assert record.publication_number == "EP3123456B1"

    def test_family_key_prefers_family_id(self) -> None:
        record = PatentRecord(
            provider="epo_ops", publication_number="EP1A1", family_id="999"
        )
        assert record.family_key == "999"

    def test_family_key_falls_back_to_publication_number(self) -> None:
        record = PatentRecord(provider="epo_ops", publication_number="EP1A1")
        assert record.family_key == "EP1A1"

    def test_default_record_type_is_application_not_granted(self) -> None:
        # Defaulting to "granted" would overstate every result.
        record = PatentRecord(provider="epo_ops", publication_number="EP1A1")
        assert record.record_type is PatentRecordType.PUBLISHED_APPLICATION


class TestSearchFilters:
    def test_reversed_date_range_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="date_from must not be after date_to"):
            SearchFilters(date_from=2020, date_to=2010)

    def test_max_results_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            SearchFilters(max_results=5000)
