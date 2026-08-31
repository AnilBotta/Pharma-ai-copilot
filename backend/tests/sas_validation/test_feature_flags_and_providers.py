"""A disabled mode must be unreachable, not merely unadvertised.

Hiding an option in the interface is not a feature flag. Anyone can guess an
API shape, and a nonfunctional provider reached that way fails somewhere far
less legible than the place that should have refused.

So the flag is checked in `provider_for`, and these tests reach past the UI to
prove it.
"""

from __future__ import annotations

import pytest

from app.sas_validation import modes
from app.sas_validation.modes import (
    SASCapability,
    SASIntegrationMode,
    is_enabled,
    mode_is_available,
)
from app.sas_validation.package import ValidationPackage
from app.sas_validation.providers import (
    CustomerRemoteSASProvider,
    CustomerViyaSASProvider,
    ManagedSASValidationProvider,
    ManualSASValidationProvider,
    SASProviderUnavailable,
    provider_for,
)


def test_only_manual_validation_ships_enabled():
    """The honest default. Everything that does not work is off."""
    assert is_enabled(SASCapability.MANUAL_PACKAGE_GENERATION)
    assert is_enabled(SASCapability.MANUAL_RESULT_UPLOAD)

    assert not is_enabled(SASCapability.MANAGED_VALIDATION)
    assert not is_enabled(SASCapability.CUSTOMER_CONNECTION)


@pytest.mark.parametrize(
    "mode",
    [
        SASIntegrationMode.MANAGED,
        SASIntegrationMode.CUSTOMER_VIYA,
        SASIntegrationMode.CUSTOMER_REMOTE,
    ],
)
def test_a_disabled_mode_refuses_when_asked_for_directly(mode):
    """Not "the button is hidden" - the provider itself will not be built."""
    assert not mode_is_available(mode)
    with pytest.raises(SASProviderUnavailable):
        provider_for(mode)


def test_the_manual_provider_is_available_and_connects_to_nothing():
    provider = provider_for(SASIntegrationMode.MANUAL_UPLOAD)
    assert isinstance(provider, ManualSASValidationProvider)

    result = provider.test_connection()
    assert result.ok
    assert "needs no connection" in result.detail
    assert "under your organisation's control" in result.detail


def test_an_unconfigured_integration_has_no_provider():
    with pytest.raises(SASProviderUnavailable, match="No SAS validation mode"):
        provider_for(SASIntegrationMode.NOT_CONFIGURED)


@pytest.mark.parametrize(
    "provider_class",
    [ManagedSASValidationProvider, CustomerViyaSASProvider, CustomerRemoteSASProvider],
)
def test_the_stubs_refuse_rather_than_returning_a_plausible_success(provider_class):
    """A stub that returned a fake success would be worse than no stub.

    It would look finished, pass a smoke test, and fail in front of the first
    customer who enabled it. Every method raises, and the connection test
    reports not-ok with a reason.
    """
    provider = provider_class()

    assert provider.test_connection().ok is False

    package = ValidationPackage(
        package_id="0" * 64,
        case_id="X",
        regulatory_method="m",
        files=(),
        manifest={},
        generated_at="2026-08-31T12:00:00+00:00",
        be_stats_version="0.7.0",
        git_sha="abc",
    )
    with pytest.raises(SASProviderUnavailable):
        provider.submit_validation(package)
    with pytest.raises(SASProviderUnavailable):
        provider.get_validation_status("job-1")
    with pytest.raises(SASProviderUnavailable):
        provider.fetch_validation_result("job-1")


def test_every_unavailable_mode_explains_itself_to_a_customer():
    """A greyed-out control with no explanation reads as a broken product."""
    for mode in (
        SASIntegrationMode.MANAGED,
        SASIntegrationMode.CUSTOMER_VIYA,
        SASIntegrationMode.CUSTOMER_REMOTE,
    ):
        reason = modes.UNAVAILABLE_REASON[mode]
        assert len(reason) > 40
        assert "not yet available" in reason


def test_the_managed_notice_never_promises_availability():
    """Managed SAS depends on commercial rights this organisation may not hold.

    The product must not imply a service is purchasable before it is.
    """
    notice = modes.MANAGED_AVAILABILITY_NOTICE
    assert "depends on" in notice
    for forbidden in ("pay-as-you-go", "available now", "$", "per run for"):
        assert forbidden not in notice


def test_enabling_managed_in_a_test_does_not_leak_into_others(monkeypatch):
    """The flags are a plain dict, so a test must patch rather than mutate."""
    monkeypatch.setitem(
        modes.FEATURE_FLAGS, SASCapability.MANAGED_VALIDATION, True
    )
    assert mode_is_available(SASIntegrationMode.MANAGED)
    # provider_for now builds it - and it still refuses to do any work,
    # because the flag controls exposure and the stub controls capability.
    provider = provider_for(SASIntegrationMode.MANAGED)
    with pytest.raises(SASProviderUnavailable):
        provider.get_validation_status("job-1")


def test_the_acknowledgement_is_required_only_for_connected_modes():
    assert SASIntegrationMode.CUSTOMER_VIYA.requires_authorisation_acknowledgement
    assert SASIntegrationMode.CUSTOMER_REMOTE.requires_authorisation_acknowledgement
    assert not SASIntegrationMode.MANUAL_UPLOAD.requires_authorisation_acknowledgement
    assert not SASIntegrationMode.MANAGED.requires_authorisation_acknowledgement


def test_manual_mode_is_the_only_one_that_never_connects_outbound():
    assert not SASIntegrationMode.MANUAL_UPLOAD.connects_outbound
    assert not SASIntegrationMode.MANUAL_UPLOAD.stores_secrets
    for mode in (
        SASIntegrationMode.MANAGED,
        SASIntegrationMode.CUSTOMER_VIYA,
        SASIntegrationMode.CUSTOMER_REMOTE,
    ):
        assert mode.connects_outbound
