"""Europe PMC adapter.

Europe PMC requires no credentials and indexes a broader corpus than PubMed,
including preprints and patents-cited-by-literature. It is also the source that
can tell us whether open-access full text is genuinely available, which PubMed
metadata alone cannot.

The ``core`` result type is requested so abstracts and publication metadata
arrive in the search response, avoiding a second round trip per record.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from app.models.records import LiteratureRecord, SearchFilters, SearchResult
from app.providers.base import LiteratureProvider, ProviderError
from app.providers.cache import NullCache, ResponseCache, cache_key
from app.providers.http import ProviderHTTPClient

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

#: Sources whose records are preprints rather than peer-reviewed articles.
_PREPRINT_SOURCES = {"PPR"}


class EuropePMCProvider(LiteratureProvider):
    name = "europepmc"
    requires_credentials = False

    def __init__(
        self,
        *,
        cache: ResponseCache | None = None,
        cache_ttl: int = 86_400,
        timeout: float = 30.0,
        email: str | None = None,
        requests_per_second: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        self._cache = cache or NullCache()
        self._cache_ttl = cache_ttl
        self._email = email
        self._client = ProviderHTTPClient(
            self.name,
            base_url=BASE_URL,
            timeout=timeout,
            max_retries=max_retries,
            # Europe PMC publishes no hard limit; the default is deliberately polite.
            requests_per_second=requests_per_second,
        )

    @property
    def is_configured(self) -> bool:
        return True  # no credentials required

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------- search ---

    async def search(
        self, query: str, filters: SearchFilters
    ) -> SearchResult[LiteratureRecord]:
        started = time.monotonic()
        effective_query = self._build_query(query, filters)

        key = cache_key(
            self.name, "search", {"q": effective_query, "n": filters.max_results}
        )
        cached = await self._cache.get(key)
        if cached is not None:
            return SearchResult[LiteratureRecord](
                provider=self.name,
                query=effective_query,
                records=[LiteratureRecord.model_validate(r) for r in cached["records"]],
                total_available=cached.get("total_available"),
                from_cache=True,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        params: dict[str, Any] = {
            "query": effective_query,
            "format": "json",
            "resultType": "core",
            "pageSize": min(filters.max_results, 100),
        }
        if self._email:
            params["email"] = self._email

        try:
            payload = await self._client.get_json("/search", params=params)
        except ProviderError as exc:
            logger.warning("Europe PMC search failed: %s", exc)
            return SearchResult[LiteratureRecord](
                provider=self.name,
                query=effective_query,
                records=[],
                ok=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        raw_results = (payload.get("resultList") or {}).get("result") or []
        records = []
        for item in raw_results:
            parsed = self._parse(item)
            if parsed and parsed.has_identifier:
                records.append(parsed)

        total = _int(payload.get("hitCount"))

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
        """Fetch by DOI, PMID or PMCID. Europe PMC accepts all three in a query."""
        field = (
            "DOI" if identifier.startswith("10.")
            else "PMCID" if identifier.upper().startswith("PMC")
            else "EXT_ID"
        )
        try:
            payload = await self._client.get_json(
                "/search",
                params={
                    "query": f'{field}:"{identifier}"',
                    "format": "json",
                    "resultType": "core",
                    "pageSize": 1,
                },
            )
        except ProviderError:
            return None
        results = (payload.get("resultList") or {}).get("result") or []
        return self._parse(results[0]) if results else None

    # ------------------------------------------------------------------ query ---

    @staticmethod
    def _build_query(query: str, filters: SearchFilters) -> str:
        """Compose the Europe PMC query string.

        Kept as a single string (rather than separate parameters) so the exact
        query recorded in search_queries is the one that was executed.
        """
        parts = [f"({query})"]
        if filters.date_from or filters.date_to:
            start = filters.date_from or 1800
            end = filters.date_to or date.today().year
            parts.append(f"(FIRST_PDATE:[{start}-01-01 TO {end}-12-31])")
        if filters.open_access_only:
            parts.append("(OPEN_ACCESS:y)")
        return " AND ".join(parts)

    # ---------------------------------------------------------------- parsing ---

    def _parse(self, item: dict[str, Any]) -> LiteratureRecord | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None

        journal_info = item.get("journalInfo") or {}
        journal = ((journal_info.get("journal") or {}).get("title") or "").strip() or None

        pub_types = [
            str(t) for t in ((item.get("pubTypeList") or {}).get("pubType") or []) if t
        ]

        source = (item.get("source") or "").upper()
        is_preprint = source in _PREPRINT_SOURCES or any(
            "preprint" in t.lower() for t in pub_types
        )

        # `isOpenAccess` is "Y"/"N"; `inEPMC` indicates full text is hosted here.
        is_open_access = str(item.get("isOpenAccess", "")).upper() == "Y"

        authors = [
            (a.get("fullName") or "").strip()
            for a in ((item.get("authorList") or {}).get("author") or [])
        ]
        authors = [a for a in authors if a]
        if not authors and item.get("authorString"):
            authors = [
                part.strip().rstrip(".")
                for part in str(item["authorString"]).split(",")
                if part.strip()
            ]

        published = _parse_date(
            item.get("firstPublicationDate") or item.get("electronicPublicationDate")
        )

        return LiteratureRecord(
            provider=self.name,
            title=title,
            abstract=(item.get("abstractText") or "").strip() or None,
            authors=authors,
            journal=journal,
            publication_date=published,
            publication_year=published.year if published else _int(item.get("pubYear")),
            doi=item.get("doi"),
            pmid=item.get("pmid"),
            pmcid=item.get("pmcid"),
            url=_europepmc_url(item),
            publication_types=pub_types,
            is_preprint=is_preprint,
            is_open_access=is_open_access,
            # The search response carries no body text. Claiming full text here
            # because open access is available would assert something we have
            # not actually retrieved.
            full_text=None,
            raw=None,
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _europepmc_url(item: dict[str, Any]) -> str | None:
    source = item.get("source")
    ext_id = item.get("id")
    if source and ext_id:
        return f"https://europepmc.org/article/{source}/{ext_id}"
    return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
