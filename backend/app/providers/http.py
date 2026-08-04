"""Shared HTTP behaviour for provider adapters: rate limiting, retries and
consistent mapping of transport failures onto ProviderError types.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import TracebackType
from typing import Any

import httpx

from app.providers.base import (
    ProviderError,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

#: Status codes worth retrying. 429 is handled separately so Retry-After is honoured.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class RateLimiter:
    """Minimum-interval limiter.

    Providers publish limits as requests per second (PubMed: 3, or 10 with an
    API key), so spacing requests is both sufficient and simpler than a token
    bucket. The lock makes it safe when the literature agent fans out queries
    concurrently.
    """

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            elapsed = time.monotonic() - self._last_request
            wait = self._min_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


class ProviderHTTPClient:
    """Thin httpx wrapper that applies rate limiting and retry policy.

    Retries use exponential backoff with a cap. A 429 honours the server's
    Retry-After when present, because guessing shorter than the provider asked
    is how quotas get revoked.
    """

    def __init__(
        self,
        provider: str,
        *,
        base_url: str = "",
        timeout: float = 30.0,
        max_retries: int = 3,
        requests_per_second: float = 3.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries
        self._limiter = RateLimiter(requests_per_second)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": (
                    "PharmaRDCopilot/0.1 "
                    "(research support tool; +https://github.com/pharma-rd-copilot)"
                ),
                **(headers or {}),
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> ProviderHTTPClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform a request, retrying transient failures.

        Raises ProviderRateLimited, ProviderUnavailable or ProviderError. It
        never returns a non-2xx response, so callers can parse unconditionally.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            await self._limiter.acquire()
            try:
                response = await self._client.request(
                    method, url, params=params, data=data, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "%s request timed out (attempt %d/%d)",
                    self.provider,
                    attempt + 1,
                    self.max_retries + 1,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise ProviderUnavailable(
                    self.provider, f"Request timed out after {self.max_retries + 1} attempts."
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise ProviderUnavailable(
                    self.provider, f"Network error: {type(exc).__name__}."
                ) from exc

            if response.status_code == 429:
                retry_after = _parse_retry_after(response)
                if attempt < self.max_retries:
                    await asyncio.sleep(retry_after or self._backoff(attempt))
                    continue
                raise ProviderRateLimited(
                    self.provider,
                    "Rate limit or quota exceeded.",
                    retry_after=retry_after,
                    status_code=429,
                )

            if response.status_code in RETRYABLE_STATUS:
                if attempt < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise ProviderUnavailable(
                    self.provider,
                    f"Server error {response.status_code} after "
                    f"{self.max_retries + 1} attempts.",
                    status_code=response.status_code,
                )

            if response.status_code in (401, 403):
                raise ProviderUnavailable(
                    self.provider,
                    "Authentication failed. Check the configured credentials.",
                    status_code=response.status_code,
                )

            if response.status_code >= 400:
                raise ProviderError(
                    self.provider,
                    f"Request failed with status {response.status_code}.",
                    status_code=response.status_code,
                )

            return response

        # Unreachable: every path above either returns or raises.
        raise ProviderError(self.provider, f"Request failed: {last_error}")

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = await self.request("GET", url, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                self.provider, "Response was not valid JSON."
            ) from exc

    async def get_text(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        response = await self.request("GET", url, params=params)
        return response.text

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff capped at 8s: 0.5, 1, 2, 4, 8..."""
        return min(0.5 * (2**attempt), 8.0)


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        # The HTTP-date form is legal but rare here; backoff covers it.
        return None
