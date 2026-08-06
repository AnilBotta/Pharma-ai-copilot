"""PubMed adapter over the NCBI E-utilities API.

Two calls per search: ``esearch`` returns PMIDs, ``efetch`` returns full records
as XML. The XML is parsed with defusedxml-equivalent hardening via
``xml.etree.ElementTree`` restricted to parsing (no entity resolution is
performed by ElementTree, so external entity attacks do not apply).

Rate limits are NCBI's published figures: 3 requests/second without an API key,
10 with one. NCBI's usage policy asks for an identifying email, which is sent
when configured.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any
from xml.etree import ElementTree

from app.models.records import (
    LiteratureRecord,
    SearchFilters,
    SearchResult,
)
from app.providers.base import LiteratureProvider, ProviderError
from app.providers.cache import NullCache, ResponseCache, cache_key
from app.providers.http import ProviderHTTPClient

logger = logging.getLogger(__name__)

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

#: PublicationType values that mark a record as a preprint.
_PREPRINT_TYPES = {"preprint"}


class PubMedProvider(LiteratureProvider):
    name = "pubmed"
    requires_credentials = False  # keyless at a lower rate limit

    def __init__(
        self,
        api_key: str | None = None,
        email: str | None = None,
        *,
        cache: ResponseCache | None = None,
        cache_ttl: int = 86_400,
        timeout: float = 30.0,
        requests_per_second: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._email = email
        self._cache = cache or NullCache()
        self._cache_ttl = cache_ttl
        self._client = ProviderHTTPClient(
            self.name,
            base_url=BASE_URL,
            timeout=timeout,
            max_retries=max_retries,
            # NCBI: 10 req/s with a key, 3 without. Stay just under.
            requests_per_second=(
                requests_per_second
                if requests_per_second is not None
                else (9.0 if api_key else 2.5)
            ),
        )

    @property
    def is_configured(self) -> bool:
        # Usable without credentials; a key only raises the rate limit.
        return True

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------- search ---

    async def search(
        self, query: str, filters: SearchFilters
    ) -> SearchResult[LiteratureRecord]:
        started = time.monotonic()
        effective_query = self._apply_date_filter(query, filters)

        key = cache_key(
            self.name,
            "search",
            {"q": effective_query, "n": filters.max_results},
        )
        cached = await self._cache.get(key)
        if cached is not None:
            records = [LiteratureRecord.model_validate(r) for r in cached["records"]]
            return SearchResult[LiteratureRecord](
                provider=self.name,
                query=effective_query,
                records=records,
                total_available=cached.get("total_available"),
                from_cache=True,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            pmids, total = await self._esearch(effective_query, filters.max_results)
            records = await self._efetch(pmids) if pmids else []
        except ProviderError as exc:
            # Honest empty result. The caller records the error and continues
            # with whatever other providers returned.
            logger.warning("PubMed search failed: %s", exc)
            return SearchResult[LiteratureRecord](
                provider=self.name,
                query=effective_query,
                records=[],
                ok=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        await self._cache.set(
            key,
            self.name,
            {
                "records": [r.model_dump(mode="json") for r in records],
                "total_available": total,
            },
            self._cache_ttl,
        )

        return SearchResult[LiteratureRecord](
            provider=self.name,
            query=effective_query,
            records=records,
            total_available=total,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def fetch_record(self, identifier: str) -> LiteratureRecord | None:
        records = await self._efetch([identifier.strip()])
        return records[0] if records else None

    # ------------------------------------------------------------- E-utilities ---

    def _common_params(self) -> dict[str, str]:
        params = {"db": "pubmed", "tool": "PharmaRDCopilot"}
        if self._api_key:
            params["api_key"] = self._api_key
        if self._email:
            params["email"] = self._email
        return params

    @staticmethod
    def _apply_date_filter(query: str, filters: SearchFilters) -> str:
        """Express the date range in PubMed query syntax.

        Done in the query rather than via mindate/maxdate parameters so the
        exact string we searched is what gets logged to search_queries.
        """
        if not filters.date_from and not filters.date_to:
            return query
        start = filters.date_from or 1800
        end = filters.date_to or date.today().year
        return f"({query}) AND {start}:{end}[dp]"

    async def _esearch(self, query: str, retmax: int) -> tuple[list[str], int]:
        params = {
            **self._common_params(),
            "term": query,
            "retmax": str(retmax),
            "retmode": "json",
            "sort": "relevance",
        }
        payload = await self._client.get_json("/esearch.fcgi", params=params)
        result = payload.get("esearchresult", {})
        if "ERROR" in result:
            raise ProviderError(self.name, str(result["ERROR"]))
        idlist = [str(i) for i in result.get("idlist", [])]
        try:
            total = int(result.get("count", 0))
        except (TypeError, ValueError):
            total = len(idlist)
        return idlist, total

    async def _efetch(self, pmids: list[str]) -> list[LiteratureRecord]:
        if not pmids:
            return []
        params = {
            **self._common_params(),
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        xml_text = await self._client.get_text("/efetch.fcgi", params=params)
        try:
            root = ElementTree.fromstring(xml_text)  # noqa: S314 - see module docstring
        except ElementTree.ParseError as exc:
            raise ProviderError(self.name, f"Malformed XML from efetch: {exc}") from exc

        records = []
        for article in root.findall(".//PubmedArticle"):
            parsed = self._parse_article(article)
            # Enforce the same rule the database enforces: no identifier, no evidence.
            if parsed and parsed.has_identifier:
                records.append(parsed)
        return records

    # ------------------------------------------------------------------ parsing ---

    def _parse_article(self, article: ElementTree.Element) -> LiteratureRecord | None:
        medline = article.find("MedlineCitation")
        if medline is None:
            return None
        art = medline.find("Article")
        if art is None:
            return None

        title = _text_content(art.find("ArticleTitle"))
        if not title:
            return None

        ids = _article_ids(article)
        pmid = _text(medline.find("PMID")) or ids.get("pubmed")

        pub_types = [
            _text(pt) or ""
            for pt in art.findall(".//PublicationTypeList/PublicationType")
        ]
        pub_types = [p for p in pub_types if p]

        published = _parse_pub_date(art)

        return LiteratureRecord(
            provider=self.name,
            title=title,
            abstract=_parse_abstract(art),
            authors=_parse_authors(art),
            journal=_text(art.find("Journal/Title")),
            publication_date=published,
            publication_year=published.year if published else _parse_year(art),
            doi=ids.get("doi"),
            pmid=pmid,
            pmcid=ids.get("pmc"),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            publication_types=pub_types,
            is_preprint=any(p.lower() in _PREPRINT_TYPES for p in pub_types),
            # PubMed does not assert open access; Europe PMC does. Leaving this
            # False rather than guessing keeps the claim honest.
            is_open_access=False,
            # efetch returns metadata and abstract only, never full text.
            full_text=None,
            raw=None,
        )


# --------------------------------------------------------------------------- #
# XML helpers
# --------------------------------------------------------------------------- #


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _text_content(element: ElementTree.Element | None) -> str | None:
    """Flatten an element that may contain inline markup (italics in titles)."""
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _article_ids(article: ElementTree.Element) -> dict[str, str]:
    ids: dict[str, str] = {}
    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        id_type = node.get("IdType")
        value = (node.text or "").strip()
        if id_type and value:
            ids[id_type] = value
    return ids


def _parse_authors(art: ElementTree.Element) -> list[str]:
    authors = []
    for author in art.findall("AuthorList/Author"):
        last = _text(author.find("LastName"))
        initials = _text(author.find("Initials"))
        collective = _text(author.find("CollectiveName"))
        if collective:
            authors.append(collective)
        elif last:
            authors.append(f"{last} {initials}" if initials else last)
    return authors


def _parse_abstract(art: ElementTree.Element) -> str | None:
    """Reassemble a structured abstract, preserving its section labels."""
    parts = []
    for node in art.findall("Abstract/AbstractText"):
        content = "".join(node.itertext()).strip()
        if not content:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {content}" if label else content)
    return "\n\n".join(parts) if parts else None


def _parse_pub_date(art: ElementTree.Element) -> date | None:
    """Prefer ArticleDate (electronic publication) over the journal issue date,
    which is frequently year-only or a season."""
    for path in ("ArticleDate", "Journal/JournalIssue/PubDate"):
        node = art.find(path)
        if node is None:
            continue
        year = _int(_text(node.find("Year")))
        if not year:
            continue
        month = _parse_month(_text(node.find("Month"))) or 1
        day = _int(_text(node.find("Day"))) or 1
        try:
            return date(year, month, day)
        except ValueError:
            try:
                return date(year, month, 1)
            except ValueError:
                return None
    return None


def _parse_year(art: ElementTree.Element) -> int | None:
    return _int(_text(art.find("Journal/JournalIssue/PubDate/Year")))


def _parse_month(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        month = int(value)
        return month if 1 <= month <= 12 else None
    return _MONTHS.get(value[:3].lower())


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
