"""Provider adapter behaviour, especially under failure.

The contract being tested throughout: a provider that cannot answer returns an
empty result and says why. It never returns substitute data. Every assertion
that a failed search produced `records == []` is guarding against the single
worst failure mode this system can have.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.models.records import PatentRecordType, SearchFilters
from app.providers.base import ProviderError, ProviderUnavailable
from app.providers.cache import MemoryCache, cache_key
from app.providers.epo_ops import EPOOPSProvider
from app.providers.europepmc import EuropePMCProvider
from app.providers.http import ProviderHTTPClient
from app.providers.pubmed import PubMedProvider

FIXTURES = Path(__file__).parent / "fixtures"

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPS_AUTH = "https://ops.epo.org/3.2/auth/accesstoken"
OPS_SEARCH = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>26414409</PMID>
      <Article>
        <Journal>
          <Title>Biomaterials</Title>
          <JournalIssue><PubDate><Year>2015</Year><Month>Dec</Month></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Gelatin methacryloyl <i>hydrogels</i> for delivery.</ArticleTitle>
        <Abstract>
          <AbstractText Label="OBJECTIVE">Assess the hydrogel.</AbstractText>
          <AbstractText Label="RESULTS">It worked in vitro.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Yue</LastName><Initials>K</Initials></Author>
          <Author><CollectiveName>The Study Group</CollectiveName></Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Review</PublicationType>
        </PublicationTypeList>
        <ArticleDate><Year>2015</Year><Month>08</Month><Day>28</Day></ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">26414409</ArticleId>
        <ArticleId IdType="doi">10.1016/j.biomaterials.2015.08.045</ArticleId>
        <ArticleId IdType="pmc">PMC4610009</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


# --------------------------------------------------------------------------- #
# PubMed
# --------------------------------------------------------------------------- #


class TestPubMedParsing:
    @respx.mock
    async def test_parses_a_complete_record(self) -> None:
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["26414409"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))

        provider = PubMedProvider()
        result = await provider.search("hydrogel", SearchFilters(max_results=5))
        await provider.aclose()

        assert result.ok is True
        [record] = result.records
        assert record.pmid == "26414409"
        assert record.doi == "10.1016/j.biomaterials.2015.08.045"
        assert record.pmcid == "PMC4610009"
        assert record.journal == "Biomaterials"
        assert record.publication_date.isoformat() == "2015-08-28"
        assert result.total_available == 1

    @respx.mock
    async def test_inline_markup_in_title_is_flattened(self) -> None:
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))
        provider = PubMedProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert record.title == "Gelatin methacryloyl hydrogels for delivery."

    @respx.mock
    async def test_structured_abstract_keeps_its_labels(self) -> None:
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))
        provider = PubMedProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert "OBJECTIVE: Assess the hydrogel." in record.abstract
        assert "RESULTS: It worked in vitro." in record.abstract

    @respx.mock
    async def test_collective_author_names_are_kept(self) -> None:
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))
        provider = PubMedProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert record.authors == ["Yue K", "The Study Group"]

    @respx.mock
    async def test_efetch_reports_abstract_only_not_full_text(self) -> None:
        # efetch never returns body text; claiming otherwise would be a lie.
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))
        provider = PubMedProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert record.access_level == "abstract_only"
        assert record.full_text is None

    def test_date_filter_is_expressed_in_the_query_that_gets_logged(self) -> None:
        query = PubMedProvider._apply_date_filter(
            "peptide", SearchFilters(date_from=2015, date_to=2020)
        )
        assert query == "(peptide) AND 2015:2020[dp]"


class TestPubMedFailureHandling:
    @respx.mock
    async def test_server_error_yields_empty_result_not_an_exception(self) -> None:
        respx.get(ESEARCH).mock(httpx.Response(500))
        provider = PubMedProvider()
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert result.ok is False
        assert result.records == []
        assert "500" in result.error

    @respx.mock
    async def test_no_results_is_success_with_zero_records(self) -> None:
        # Distinct from failure: the search worked and found nothing.
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": [], "count": "0"}})
        )
        provider = PubMedProvider()
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert result.ok is True
        assert result.records == []
        assert result.error is None

    @respx.mock
    async def test_malformed_xml_fails_honestly(self) -> None:
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text="<not-closed"))
        provider = PubMedProvider()
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert result.ok is False
        assert result.records == []

    @respx.mock
    async def test_records_without_identifiers_are_dropped(self) -> None:
        xml = """<?xml version="1.0"?><PubmedArticleSet><PubmedArticle>
          <MedlineCitation><Article><ArticleTitle>Untraceable</ArticleTitle></Article></MedlineCitation>
        </PubmedArticle></PubmedArticleSet>"""
        respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=xml))
        provider = PubMedProvider()
        result = await provider.search("x", SearchFilters())
        await provider.aclose()
        assert result.records == []

    @respx.mock
    async def test_api_key_is_sent_when_configured(self) -> None:
        route = respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": [], "count": "0"}})
        )
        provider = PubMedProvider(api_key="secret-key", email="a@b.com")
        await provider.search("x", SearchFilters())
        await provider.aclose()
        assert route.calls[0].request.url.params["api_key"] == "secret-key"

    async def test_works_without_credentials(self) -> None:
        assert PubMedProvider().is_configured is True


class TestPubMedCaching:
    @respx.mock
    async def test_second_identical_search_is_served_from_cache(self) -> None:
        esearch = respx.get(ESEARCH).mock(
            httpx.Response(200, json={"esearchresult": {"idlist": ["26414409"], "count": "1"}})
        )
        respx.get(EFETCH).mock(httpx.Response(200, text=PUBMED_XML))

        cache = MemoryCache()
        provider = PubMedProvider(cache=cache, cache_ttl=60)
        first = await provider.search("hydrogel", SearchFilters(max_results=5))
        second = await provider.search("hydrogel", SearchFilters(max_results=5))
        await provider.aclose()

        assert esearch.call_count == 1
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.records[0].pmid == first.records[0].pmid


# --------------------------------------------------------------------------- #
# Europe PMC
# --------------------------------------------------------------------------- #


EPMC_PAYLOAD = {
    "hitCount": 8553,
    "resultList": {
        "result": [
            {
                "id": "42197269",
                "source": "MED",
                "pmid": "42197269",
                "pmcid": "PMC13209427",
                "doi": "10.3390/molecules31101715",
                "title": "Antimicrobial Peptide Carbon Nanotube Hybrids",
                "abstractText": "We evaluate hybrids.",
                "authorString": "Kim J, Lee S.",
                "journalInfo": {"journal": {"title": "Molecules"}},
                "pubYear": "2026",
                "firstPublicationDate": "2026-04-28",
                "isOpenAccess": "Y",
                "pubTypeList": {"pubType": ["Journal Article"]},
            }
        ]
    },
}


class TestEuropePMC:
    @respx.mock
    async def test_parses_core_result(self) -> None:
        respx.get(EPMC_SEARCH).mock(httpx.Response(200, json=EPMC_PAYLOAD))
        provider = EuropePMCProvider()
        result = await provider.search("peptide", SearchFilters())
        await provider.aclose()

        [record] = result.records
        assert record.doi == "10.3390/molecules31101715"
        assert record.pmcid == "PMC13209427"
        assert record.is_open_access is True
        assert record.journal == "Molecules"
        assert record.publication_date.isoformat() == "2026-04-28"
        assert result.total_available == 8553

    @respx.mock
    async def test_open_access_does_not_imply_retrieved_full_text(self) -> None:
        respx.get(EPMC_SEARCH).mock(httpx.Response(200, json=EPMC_PAYLOAD))
        provider = EuropePMCProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert record.is_open_access is True
        assert record.access_level == "abstract_only"

    @respx.mock
    async def test_preprint_source_is_labelled(self) -> None:
        payload = json.loads(json.dumps(EPMC_PAYLOAD))
        payload["resultList"]["result"][0]["source"] = "PPR"
        respx.get(EPMC_SEARCH).mock(httpx.Response(200, json=payload))
        provider = EuropePMCProvider()
        [record] = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert record.is_preprint is True

    @respx.mock
    async def test_failure_returns_empty_and_explains(self) -> None:
        respx.get(EPMC_SEARCH).mock(httpx.Response(503))
        provider = EuropePMCProvider()
        result = await provider.search("x", SearchFilters())
        await provider.aclose()
        assert result.ok is False
        assert result.records == []
        assert result.error

    def test_date_and_open_access_filters_appear_in_query(self) -> None:
        query = EuropePMCProvider._build_query(
            "peptide", SearchFilters(date_from=2015, date_to=2020, open_access_only=True)
        )
        assert "(peptide)" in query
        assert "FIRST_PDATE:[2015-01-01 TO 2020-12-31]" in query
        assert "OPEN_ACCESS:y" in query

    async def test_requires_no_credentials(self) -> None:
        assert EuropePMCProvider().is_configured is True


# --------------------------------------------------------------------------- #
# EPO OPS
# --------------------------------------------------------------------------- #


def epo_fixture() -> dict:
    return json.loads((FIXTURES / "epo_search_response.json").read_text())


class TestEPOConfiguration:
    async def test_missing_credentials_reports_unconfigured(self) -> None:
        assert EPOOPSProvider(None, None).is_configured is False

    async def test_partial_credentials_count_as_unconfigured(self) -> None:
        # Attempting a call with half a credential pair would produce a
        # confusing 401 instead of a clear "not configured" message.
        assert EPOOPSProvider("key", None).is_configured is False
        assert EPOOPSProvider(None, "secret").is_configured is False

    async def test_unconfigured_search_explains_itself_and_returns_nothing(self) -> None:
        provider = EPOOPSProvider(None, None)
        result = await provider.search("peptide", SearchFilters())
        await provider.aclose()

        assert result.ok is False
        assert result.records == []
        assert "not configured" in result.error.lower()

    async def test_unconfigured_health_check_is_actionable(self) -> None:
        ok, detail = await EPOOPSProvider(None, None).health_check()
        assert ok is False
        assert "EPO_OPS_CONSUMER_KEY" in detail


class TestEPOParsing:
    @respx.mock
    async def test_parses_fixture_documents(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))

        provider = EPOOPSProvider("k", "s")
        result = await provider.search("carbon nanotube depot", SearchFilters())
        await provider.aclose()

        assert result.ok is True
        assert len(result.records) == 3
        ep = next(r for r in result.records if r.publication_number == "EP3123456B1")
        assert ep.title == "Sustained release depot formulation using carbon nanotubes"
        assert ep.record_type is PatentRecordType.GRANTED_PATENT
        assert ep.family_id == "55555555"
        assert ep.jurisdiction == "EP"
        assert ep.publication_date.isoformat() == "2020-01-15"

    @respx.mock
    async def test_kind_code_distinguishes_granted_from_application(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()

        by_number = {r.publication_number: r for r in records}
        assert by_number["EP3123456B1"].record_type is PatentRecordType.GRANTED_PATENT
        assert by_number["WO2019123456A1"].record_type is PatentRecordType.PUBLISHED_APPLICATION

    @respx.mock
    async def test_earliest_priority_date_is_selected(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()

        ep = next(r for r in records if r.publication_number == "EP3123456B1")
        assert ep.priority_date.isoformat() == "2014-02-28"

    @respx.mock
    async def test_party_names_are_not_duplicated_across_data_formats(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()

        ep = next(r for r in records if r.publication_number == "EP3123456B1")
        assert ep.applicants == ["EXAMPLE PHARMA"]
        assert ep.inventors == ["MUELLER ANNA"]

    @respx.mock
    async def test_legacy_envelope_key_is_still_accepted(self) -> None:
        """The live service returns `ops:biblio-search`; the documented shape
        said `ops:biblio-search-result`.

        Regression guard. The adapter originally read only the documented key,
        so a live search returning 15,159 hits parsed as ZERO records — and it
        failed silently, because ok=True with no records is a legitimate
        outcome. Both spellings are now accepted.
        """
        payload = epo_fixture()
        wpd = payload["ops:world-patent-data"]
        wpd["ops:biblio-search-result"] = wpd.pop("ops:biblio-search")

        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=payload))

        provider = EPOOPSProvider("k", "s")
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert len(result.records) == 3
        assert result.total_available == 347

    @respx.mock
    async def test_total_result_count_is_reported(self) -> None:
        # Nonzero hits with zero parsed records is the signature of a parsing
        # failure, so the count must survive parsing to make that detectable.
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        result = await provider.search("x", SearchFilters())
        await provider.aclose()
        assert result.total_available == 347
        assert result.count == 3

    @respx.mock
    async def test_classifications_are_parsed(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()

        ep = next(r for r in records if r.publication_number == "EP3123456B1")
        assert ep.cpc_classifications == ["A61K9/16"]
        # OPS pads IPC to fixed width: "A61K   9/    16   20060101A I".
        # Naive tokenising gave "A61K 9/", silently losing the subgroup.
        assert ep.ipc_classifications == ["A61K 9/16"]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("H10K  30/    15            A I", "H10K 30/15"),
            ("A61K   9/    16   20060101A I", "A61K 9/16"),
            ("C07K  19/    00            A I", "C07K 19/00"),
            ("A61K  31/  7048   20060101A I", "A61K 31/7048"),
        ],
    )
    def test_ipc_padding_is_parsed(self, raw: str, expected: str) -> None:
        from app.providers.epo_ops import _parse_ipc

        biblio = {"classifications-ipcr": {"classification-ipcr": {"text": {"$": raw}}}}
        assert _parse_ipc(biblio) == [expected]

    @respx.mock
    async def test_multi_paragraph_abstract_is_joined(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()

        us = next(r for r in records if r.publication_number == "US10987654A1")
        assert us.abstract == "First paragraph of abstract. Second paragraph."

    @respx.mock
    async def test_legal_status_is_not_inferred(self) -> None:
        # Guessing legal status from a kind code would be a legal claim we
        # have no basis for.
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        records = (await provider.search("x", SearchFilters())).records
        await provider.aclose()
        assert all(r.legal_status is None for r in records)


class TestEPOAuthAndFailures:
    @respx.mock
    async def test_token_is_reused_across_searches(self) -> None:
        auth = respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))

        provider = EPOOPSProvider("k", "s")
        await provider.search("a", SearchFilters())
        await provider.search("b", SearchFilters())
        await provider.aclose()

        assert auth.call_count == 1

    @respx.mock
    async def test_bearer_token_is_attached(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok-123", "expires_in": 1200})
        )
        search = respx.get(OPS_SEARCH).mock(httpx.Response(200, json=epo_fixture()))
        provider = EPOOPSProvider("k", "s")
        await provider.search("x", SearchFilters())
        await provider.aclose()
        assert search.calls[0].request.headers["Authorization"] == "Bearer tok-123"

    @respx.mock
    async def test_bad_credentials_surface_as_unavailable(self) -> None:
        respx.post(OPS_AUTH).mock(httpx.Response(401))
        provider = EPOOPSProvider("wrong", "wrong")
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert result.ok is False
        assert result.records == []
        assert "authentication failed" in result.error.lower()

    @respx.mock
    async def test_quota_exhaustion_returns_no_records(self) -> None:
        respx.post(OPS_AUTH).mock(
            httpx.Response(200, json={"access_token": "tok", "expires_in": 1200})
        )
        respx.get(OPS_SEARCH).mock(httpx.Response(429, headers={"Retry-After": "0"}))
        provider = EPOOPSProvider("k", "s")
        result = await provider.search("x", SearchFilters())
        await provider.aclose()

        assert result.ok is False
        assert result.records == []


class TestEPOQueryBuilding:
    def test_plain_text_becomes_title_or_abstract_search(self) -> None:
        cql = EPOOPSProvider.build_cql("carbon nanotube", SearchFilters())
        assert cql == '(ti="carbon nanotube" or ab="carbon nanotube")'

    def test_existing_cql_is_preserved(self) -> None:
        cql = EPOOPSProvider.build_cql('ti="peptide" and cpc="A61K9/16"', SearchFilters())
        assert cql == '(ti="peptide" and cpc="A61K9/16")'

    def test_date_and_jurisdiction_clauses_are_appended(self) -> None:
        cql = EPOOPSProvider.build_cql(
            "peptide",
            SearchFilters(date_from=2015, date_to=2020, jurisdictions=("EP", "US")),
        )
        assert 'pd within "2015 2020"' in cql
        assert 'pn="EP"' in cql and 'pn="US"' in cql


# --------------------------------------------------------------------------- #
# Shared HTTP behaviour
# --------------------------------------------------------------------------- #


class TestHTTPRetry:
    @respx.mock
    async def test_transient_server_error_is_retried_then_succeeds(self) -> None:
        route = respx.get("https://example.test/x").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
        )
        client = ProviderHTTPClient("test", max_retries=2, requests_per_second=0)
        payload = await client.get_json("https://example.test/x")
        await client.aclose()

        assert route.call_count == 2
        assert payload == {"ok": True}

    @respx.mock
    async def test_retries_are_bounded(self) -> None:
        route = respx.get("https://example.test/x").mock(httpx.Response(503))
        client = ProviderHTTPClient("test", max_retries=2, requests_per_second=0)
        with pytest.raises(ProviderUnavailable, match="Server error"):
            await client.get_json("https://example.test/x")
        await client.aclose()
        assert route.call_count == 3  # initial attempt plus two retries

    @respx.mock
    async def test_client_errors_are_not_retried(self) -> None:
        # A 400 will fail identically every time; retrying only wastes quota.
        route = respx.get("https://example.test/x").mock(httpx.Response(400))
        client = ProviderHTTPClient("test", max_retries=3, requests_per_second=0)
        with pytest.raises(ProviderError, match="status 400"):
            await client.get_json("https://example.test/x")
        await client.aclose()
        assert route.call_count == 1

    def test_backoff_grows_exponentially_and_is_capped(self) -> None:
        delays = [ProviderHTTPClient._backoff(i) for i in range(6)]
        assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]


class TestCacheKeys:
    def test_key_is_stable_regardless_of_parameter_order(self) -> None:
        first = cache_key("p", "search", {"a": 1, "b": 2})
        second = cache_key("p", "search", {"b": 2, "a": 1})
        assert first == second

    def test_different_parameters_produce_different_keys(self) -> None:
        assert cache_key("p", "search", {"q": "a"}) != cache_key("p", "search", {"q": "b"})

    def test_provider_and_operation_are_namespaced(self) -> None:
        assert cache_key("pubmed", "search", {}).startswith("pubmed:search:")
