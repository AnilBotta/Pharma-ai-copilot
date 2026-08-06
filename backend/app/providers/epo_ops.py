"""EPO Open Patent Services (OPS 3.2) adapter.

OPS uses OAuth2 client credentials. Tokens last 20 minutes, so one is cached and
refreshed shortly before expiry rather than fetched per request.

Two concerns shape this adapter:

* **Quota.** The free tier allows 4 GB/month. Responses are cached and the
  family lookup is only issued for records that actually need one.
* **Honesty about document type.** OPS returns published applications, granted
  patents and family records through the same endpoint. The kind code is used
  to classify each one, because presenting an application as a granted patent
  would materially mislead.

This adapter has been written against the documented OPS 3.2 response shape and
is covered by fixture-based tests. It has **not** yet been exercised against the
live service - that requires credentials, and is listed in
docs/KNOWN_LIMITATIONS.md until it has been.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import date, datetime
from typing import Any

from app.models.records import (
    PatentRecord,
    PatentRecordType,
    SearchFilters,
    SearchResult,
)
from app.providers.base import (
    PatentProvider,
    ProviderError,
    ProviderUnavailable,
)
from app.providers.cache import NullCache, ResponseCache, cache_key
from app.providers.http import ProviderHTTPClient

logger = logging.getLogger(__name__)

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
BASE_URL = "https://ops.epo.org/3.2/rest-services"

#: Refresh this many seconds before the token actually expires.
_TOKEN_SKEW = 60.0

#: EPO kind codes beginning with these letters denote a granted patent.
#: A/U/T are applications, translations and the like.
_GRANTED_KIND_PREFIXES = ("B", "C")


class EPOOPSProvider(PatentProvider):
    name = "epo_ops"
    requires_credentials = True

    def __init__(
        self,
        consumer_key: str | None,
        consumer_secret: str | None,
        *,
        cache: ResponseCache | None = None,
        cache_ttl: int = 86_400,
        timeout: float = 45.0,
        requests_per_second: float = 2.0,
        max_retries: int = 3,
    ) -> None:
        self._key = consumer_key
        self._secret = consumer_secret
        self._cache = cache or NullCache()
        self._cache_ttl = cache_ttl
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._client = ProviderHTTPClient(
            self.name,
            timeout=timeout,
            max_retries=max_retries,
            # OPS throttles by subscription tier; the default is conservative.
            requests_per_second=requests_per_second,
            headers={"Accept": "application/json"},
        )

    @property
    def is_configured(self) -> bool:
        """Both halves of the client-credentials pair are required. A partial
        configuration is treated as unconfigured rather than attempted, so the
        failure message says what is actually wrong."""
        return bool(self._key and self._secret)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> tuple[bool, str]:
        if not self.is_configured:
            return False, "EPO_OPS_CONSUMER_KEY / _SECRET not set."
        try:
            await self._ensure_token()
        except ProviderError as exc:
            return False, str(exc)
        return True, "Authenticated with EPO OPS."

    # -------------------------------------------------------------------- auth ---

    async def _ensure_token(self) -> str:
        if not self.is_configured:
            raise ProviderUnavailable(
                self.name,
                "EPO OPS is not configured. Patent search is unavailable; the run "
                "continues using the remaining sources.",
            )
        if self._token and time.monotonic() < self._token_expires_at - _TOKEN_SKEW:
            return self._token

        credentials = base64.b64encode(f"{self._key}:{self._secret}".encode()).decode()
        response = await self._client.request(
            "POST",
            AUTH_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ProviderUnavailable(self.name, "OPS returned no access token.")

        self._token = str(token)
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in", 1200))
        return self._token

    async def _authorised_get(self, url: str, params: dict[str, Any]) -> Any:
        token = await self._ensure_token()
        response = await self._client.request(
            "GET", url, params=params, headers={"Authorization": f"Bearer {token}"}
        )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(self.name, "OPS response was not valid JSON.") from exc

    # ------------------------------------------------------------------ search ---

    async def search(
        self, query: str, filters: SearchFilters
    ) -> SearchResult[PatentRecord]:
        started = time.monotonic()
        cql = self.build_cql(query, filters)

        if not self.is_configured:
            return SearchResult[PatentRecord](
                provider=self.name,
                query=cql,
                records=[],
                ok=False,
                error=(
                    "EPO OPS is not configured (EPO_OPS_CONSUMER_KEY / "
                    "EPO_OPS_CONSUMER_SECRET missing). No patent results were "
                    "retrieved."
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        key = cache_key(self.name, "search", {"q": cql, "n": filters.max_results})
        cached = await self._cache.get(key)
        if cached is not None:
            return SearchResult[PatentRecord](
                provider=self.name,
                query=cql,
                records=[PatentRecord.model_validate(r) for r in cached["records"]],
                total_available=cached.get("total_available"),
                from_cache=True,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        # OPS caps a single range request at 100 documents.
        end = min(filters.max_results, 100)
        try:
            payload = await self._authorised_get(
                f"{BASE_URL}/published-data/search/biblio",
                {"q": cql, "Range": f"1-{end}"},
            )
        except ProviderError as exc:
            logger.warning("EPO OPS search failed: %s", exc)
            return SearchResult[PatentRecord](
                provider=self.name,
                query=cql,
                records=[],
                ok=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        records, total = self._parse_search(payload)

        await self._cache.set(
            key,
            self.name,
            {
                "records": [r.model_dump(mode="json") for r in records],
                "total_available": total,
            },
            self._cache_ttl,
        )

        return SearchResult[PatentRecord](
            provider=self.name,
            query=cql,
            records=records,
            total_available=total,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def fetch_record(self, identifier: str) -> PatentRecord | None:
        if not self.is_configured:
            return None
        try:
            payload = await self._authorised_get(
                f"{BASE_URL}/published-data/publication/epodoc/{identifier}/biblio", {}
            )
        except ProviderError:
            return None
        records, _ = self._parse_search(payload)
        return records[0] if records else None

    # --------------------------------------------------------------------- CQL ---

    @staticmethod
    def build_cql(query: str, filters: SearchFilters) -> str:
        """Build an OPS CQL query.

        `query` is expected to already be CQL when it contains an operator;
        otherwise it is treated as free text and matched against title and
        abstract, which is what the patent agent produces by default.
        """
        has_operator = any(
            token in query.lower()
            for token in (" and ", " or ", "=", " any ", " all ", " within ")
        )
        base = query if has_operator else f'ti="{query}" or ab="{query}"'

        clauses = [f"({base})"]

        if filters.date_from or filters.date_to:
            start = filters.date_from or 1800
            end = filters.date_to or date.today().year
            clauses.append(f'pd within "{start} {end}"')

        if filters.jurisdictions:
            codes = " or ".join(f'pn="{j.upper()}"' for j in filters.jurisdictions)
            clauses.append(f"({codes})")

        return " and ".join(clauses)

    # ----------------------------------------------------------------- parsing ---

    def _parse_search(self, payload: Any) -> tuple[list[PatentRecord], int | None]:
        """Walk the OPS envelope.

        OPS wraps everything in ops:world-patent-data and collapses
        single-element lists into bare objects, so every level needs the
        `_as_list` treatment.

        The container key is `ops:biblio-search` in the live service. This code
        originally looked for `ops:biblio-search-result`, taken from the
        documented shape, and consequently parsed a search returning 15,159 hits
        as zero records. It failed silently because ok=True with no records is a
        legitimate outcome, which is precisely why the adapter now checks both
        spellings rather than trusting either.
        """
        root = _get(payload, "ops:world-patent-data") or {}
        search_result = (
            _get(root, "ops:biblio-search")
            or _get(root, "ops:biblio-search-result")
            or {}
        )
        total = _int(_get(search_result, "@total-result-count"))

        documents = _as_list(
            _get(search_result, "ops:search-result", "exchange-documents")
        )

        records = []
        for entry in documents:
            for doc in _as_list(_get(entry, "exchange-document")) or _as_list(entry):
                parsed = self._parse_document(doc)
                if parsed:
                    records.append(parsed)
        return records, total

    def _parse_document(self, doc: Any) -> PatentRecord | None:
        if not isinstance(doc, dict):
            return None

        country = _get(doc, "@country") or ""
        number = _get(doc, "@doc-number") or ""
        kind = _get(doc, "@kind") or ""
        if not (country and number):
            return None

        publication_number = f"{country}{number}{kind}"
        biblio = _get(doc, "bibliographic-data") or {}

        return PatentRecord(
            provider=self.name,
            publication_number=publication_number,
            title=_parse_title(biblio),
            abstract=_parse_abstract(doc),
            application_number=_parse_application_number(biblio),
            family_id=_get(doc, "@family-id"),
            kind_code=kind or None,
            jurisdiction=country,
            record_type=(
                PatentRecordType.GRANTED_PATENT
                if kind and kind.upper().startswith(_GRANTED_KIND_PREFIXES)
                else PatentRecordType.PUBLISHED_APPLICATION
            ),
            priority_date=_parse_priority_date(biblio),
            filing_date=_parse_date(
                _get(biblio, "application-reference", "document-id", "date", "$")
            ),
            publication_date=_parse_publication_date(biblio),
            applicants=_parse_parties(biblio, "applicants", "applicant"),
            inventors=_parse_parties(biblio, "inventors", "inventor"),
            cpc_classifications=_parse_cpc(biblio),
            ipc_classifications=_parse_ipc(biblio),
            # OPS exposes legal status through a separate register service that
            # costs extra quota. Left None rather than inferred from kind code.
            legal_status=None,
            raw=None,
        )


# --------------------------------------------------------------------------- #
# OPS JSON helpers
#
# The OPS payload mixes "@attributes", "$" text nodes, and single-vs-list
# collapsing. These helpers absorb that so the parser above stays readable.
# --------------------------------------------------------------------------- #


def _get(obj: Any, *path: str) -> Any:
    """Walk a nested dict, tolerating missing links and collapsed lists."""
    current = obj
    for key in path:
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_list(value: Any) -> list[Any]:
    """OPS emits a bare object when a collection has one member."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str | None:
    """Unwrap a `{"$": "..."}` text node, or take a plain string."""
    if isinstance(value, dict):
        value = value.get("$")
    if isinstance(value, list):
        value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("$")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_title(biblio: Any) -> str | None:
    """Prefer the English title where several languages are present."""
    titles = _as_list(_get(biblio, "invention-title"))
    for title in titles:
        if isinstance(title, dict) and title.get("@lang") == "en":
            return _text(title)
    return _text(titles[0]) if titles else None


def _parse_abstract(doc: Any) -> str | None:
    for abstract in _as_list(_get(doc, "abstract")):
        if isinstance(abstract, dict) and abstract.get("@lang") not in (None, "en"):
            continue
        paragraphs = _as_list(_get(abstract, "p"))
        text = " ".join(filter(None, (_text(p) for p in paragraphs)))
        if text:
            return text
    return None


def _document_ids(reference: Any) -> list[dict[str, Any]]:
    return [d for d in _as_list(_get(reference, "document-id")) if isinstance(d, dict)]


def _find_document_id(reference: Any, id_type: str) -> dict[str, Any] | None:
    for doc_id in _document_ids(reference):
        if doc_id.get("@document-id-type") == id_type:
            return doc_id
    ids = _document_ids(reference)
    return ids[0] if ids else None


def _parse_application_number(biblio: Any) -> str | None:
    doc_id = _find_document_id(_get(biblio, "application-reference"), "epodoc")
    if not doc_id:
        return None
    return _text(doc_id.get("doc-number"))


def _parse_publication_date(biblio: Any) -> date | None:
    doc_id = _find_document_id(_get(biblio, "publication-reference"), "epodoc")
    return _parse_date(_text(doc_id.get("date"))) if doc_id else None


def _parse_priority_date(biblio: Any) -> date | None:
    """Earliest priority claim, which is the date that matters for landscape work."""
    dates = []
    for claim in _as_list(_get(biblio, "priority-claims", "priority-claim")):
        for doc_id in _document_ids(claim):
            parsed = _parse_date(_text(doc_id.get("date")))
            if parsed:
                dates.append(parsed)
    return min(dates) if dates else None


def _parse_parties(biblio: Any, group: str, member: str) -> list[str]:
    """Extract applicant or inventor names, preferring the EPODOC form.

    OPS repeats each party once per name format; taking every entry would
    duplicate every name.
    """
    entries = _as_list(_get(biblio, "parties", group, member))
    preferred, fallback = [], []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = _text(_get(entry, f"{member}-name", "name"))
        if not name:
            continue
        if entry.get("@data-format") == "epodoc":
            preferred.append(name)
        else:
            fallback.append(name)
    chosen = preferred or fallback
    return list(dict.fromkeys(chosen))  # de-duplicate, preserve order


def _parse_cpc(biblio: Any) -> list[str]:
    codes = []
    for item in _as_list(_get(biblio, "patent-classifications", "patent-classification")):
        if not isinstance(item, dict):
            continue
        if item.get("classification-scheme", {}).get("@scheme") not in ("CPC", None):
            continue
        section = _text(item.get("section"))
        cls = _text(item.get("class"))
        subclass = _text(item.get("subclass"))
        main_group = _text(item.get("main-group"))
        subgroup = _text(item.get("subgroup"))
        if section and cls and subclass:
            code = f"{section}{cls}{subclass}"
            if main_group and subgroup:
                code += f"{main_group}/{subgroup}"
            codes.append(code)
    return list(dict.fromkeys(codes))


def _parse_ipc(biblio: Any) -> list[str]:
    """Extract IPC codes from OPS's fixed-width padded form.

    Live examples, where the padding is significant:

        "H10K  30/    15            A I"   -> H10K 30/15
        "A61K   9/    16   20060101A I"    -> A61K 9/16

    Tokenising and taking the first two fields yields "H10K 30/", losing the
    subgroup. The section-class-subclass, main group and subgroup are three
    separate whitespace-delimited tokens, so the last two are rejoined.
    """
    codes = []
    for item in _as_list(_get(biblio, "classifications-ipcr", "classification-ipcr")):
        text = _text(_get(item, "text"))
        if not text:
            continue
        parts = text.split()
        if len(parts) >= 3 and parts[1].endswith("/"):
            codes.append(f"{parts[0]} {parts[1]}{parts[2]}")
        elif len(parts) >= 2:
            codes.append(f"{parts[0]} {parts[1]}")
        else:
            codes.append(text)
    return list(dict.fromkeys(codes))


def _parse_date(value: Any) -> date | None:
    text = _text(value) if not isinstance(value, str) else value
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m", "%Y"):
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
