"""Provider interfaces and shared failure semantics.

The contract every adapter honours:

* A search that succeeds returns records.
* A search that finds nothing returns zero records with ``ok=True``.
* A search that fails returns zero records with ``ok=False`` and an error
  message describing what went wrong.

There is no fourth case. An adapter never substitutes, approximates or
synthesises a result, because a fabricated source is worse than no source.
"""

from __future__ import annotations

import abc

from app.models.records import (
    LiteratureRecord,
    PatentRecord,
    SearchFilters,
    SearchResult,
)

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ProviderError(Exception):
    """Base class for provider failures.

    ``error_type`` maps onto the run_errors.error_type check constraint so a
    caught error can be persisted without translation.
    """

    error_type = "provider_failure"

    def __init__(self, provider: str, message: str, *, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")


class ProviderUnavailable(ProviderError):
    """The provider is not configured, or is unreachable.

    Not configured is a normal state for optional providers and must surface to
    the user as "not configured", never as a crash.
    """

    error_type = "provider_unavailable"


class ProviderRateLimited(ProviderError):
    """Rate limit or quota exhaustion. Retryable after a delay."""

    error_type = "rate_limit"

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
    ):
        self.retry_after = retry_after
        super().__init__(provider, message, status_code=status_code)


class ProviderResponseError(ProviderError):
    """The provider replied, but the payload could not be parsed."""

    error_type = "provider_failure"


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #


class Provider(abc.ABC):
    """Common surface for every external data source."""

    #: Stable identifier. Matches the provider check constraints in the schema.
    name: str

    #: Whether the provider needs credentials to function at all.
    requires_credentials: bool = False

    @property
    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True when this provider can be called.

        Keyless providers return True unconditionally. Credentialed providers
        return False when their keys are absent, which routes the run down the
        "integration unavailable" path instead of failing it.
        """

    async def health_check(self) -> tuple[bool, str]:
        """Cheap reachability probe. Returns (ok, detail).

        Default implementation reports configuration only, so a provider that
        cannot be probed without spending quota does not have to.
        """
        if not self.is_configured:
            return False, "Not configured."
        return True, "Configured."


class LiteratureProvider(Provider):
    """A source of scientific publications."""

    @abc.abstractmethod
    async def search(
        self, query: str, filters: SearchFilters
    ) -> SearchResult[LiteratureRecord]:
        """Run a search. Must not raise for ordinary failures - return a
        SearchResult with ok=False instead, so one dead provider cannot take
        down a run that other providers could still serve."""

    @abc.abstractmethod
    async def fetch_record(self, identifier: str) -> LiteratureRecord | None:
        """Fetch one record by its native identifier. Returns None if absent."""


class PatentProvider(Provider):
    """A source of patent documents."""

    @abc.abstractmethod
    async def search(
        self, query: str, filters: SearchFilters
    ) -> SearchResult[PatentRecord]:
        """Run a search. Same non-raising contract as LiteratureProvider."""

    @abc.abstractmethod
    async def fetch_record(self, identifier: str) -> PatentRecord | None:
        """Fetch one patent by publication number. Returns None if absent."""
