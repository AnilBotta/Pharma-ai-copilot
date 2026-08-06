"""Shared test configuration."""

from __future__ import annotations

import pytest

from app.providers import epo_ops, europepmc, pubmed


@pytest.fixture(autouse=True)
def _no_rate_limiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove inter-request pacing and retry backoff from provider tests.

    Providers space requests to respect published API limits (PubMed allows 3/s
    without a key) and back off exponentially on 5xx. Against mocked transports
    there is no service to protect, and both behaviours dominated runtime: the
    suite spent roughly a minute asleep.

    Neither behaviour goes untested. Pacing and backoff are exercised directly
    in test_providers.py::TestHTTPRetry, which constructs a ProviderHTTPClient
    itself and is unaffected by this fixture. What is removed here is only the
    incidental cost of those delays in tests that are about parsing and failure
    reporting.
    """
    for module, attr in (
        (pubmed, "PubMedProvider"),
        (europepmc, "EuropePMCProvider"),
        (epo_ops, "EPOOPSProvider"),
    ):
        cls = getattr(module, attr)
        original = cls.__init__

        def make_init(original_init):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("requests_per_second", 0)
                kwargs.setdefault("max_retries", 0)
                original_init(self, *args, **kwargs)

            return __init__

        monkeypatch.setattr(cls, "__init__", make_init(original))
