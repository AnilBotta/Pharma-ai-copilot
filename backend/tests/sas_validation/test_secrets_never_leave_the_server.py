"""A secret must not be returnable, loggable, auditable or maskable.

The rule is narrow and absolute: ordinary settings tables and API responses
carry a REFERENCE into the secret store, never a value. `public_view()` is the
only thing the API returns, so if a secret cannot reach it, a secret cannot
reach a browser, a log line, an audit row, an analytics event or a URL.

Note what is deliberately absent: masking. A masked secret still discloses its
length, and there is no reason to send one when `configured: true` answers the
only question the interface actually asks.
"""

from __future__ import annotations

import json

import pytest

from app.sas_validation.config import (
    ManagedConfig,
    RemoteConfig,
    SASIntegration,
    SecretReference,
    ViyaConfig,
)
from app.sas_validation.modes import SASIntegrationMode

SECRET_VALUE = "sk-live-3f9a2b7c41d84e6fa0c5b18e7d29"


def viya_integration() -> SASIntegration:
    return SASIntegration(
        integration_id="i-1",
        tenant_id="t-1",
        mode=SASIntegrationMode.CUSTOMER_VIYA,
        viya=ViyaConfig(
            base_url="https://viya.customer.example",
            environment_name="Validation",
            organization_name="Customer Pharma",
            tenant_id="customer-tenant",
            client_secret=SecretReference("sas_viya_client_secret_t1"),
            access_token_secret=SecretReference("sas_viya_access_token_t1"),
        ),
    )


def test_a_secret_value_cannot_be_stored_as_a_reference():
    """The type refuses the mistake rather than storing it.

    Someone will eventually pass the secret where the reference belongs. If
    that succeeded, the value would sit in an ordinary settings table.
    """
    with pytest.raises(ValueError, match="looks like a secret value"):
        SecretReference("x" * 200)
    with pytest.raises(ValueError, match="looks like a secret value"):
        SecretReference("some secret with spaces")
    with pytest.raises(ValueError, match="needs a name"):
        SecretReference("  ")


def test_the_public_view_of_a_viya_integration_contains_no_secret():
    view = viya_integration().public_view()
    serialised = json.dumps(view)

    assert SECRET_VALUE not in serialised
    # Not even the reference NAME needs to travel - only whether it exists.
    assert "sas_viya_client_secret_t1" not in serialised
    assert view["viya"]["credentials_configured"] is True
    assert view["configured"] is True


def test_the_public_view_never_masks_a_secret():
    """A mask is still a disclosure, and answers a question nobody asked."""
    serialised = json.dumps(viya_integration().public_view())
    for masking in ("****", "...", "sk-", "•"):
        assert masking not in serialised


def test_the_non_secret_fields_are_returned_because_they_are_useful():
    """The split has to be worth having: an operator must still recognise
    which environment they configured."""
    view = viya_integration().public_view()["viya"]
    assert view["base_url"] == "https://viya.customer.example"
    assert view["environment_name"] == "Validation"
    assert view["organization_name"] == "Customer Pharma"


def test_a_remote_integration_exposes_no_credential_either():
    integration = SASIntegration(
        integration_id="i-2",
        tenant_id="t-1",
        mode=SASIntegrationMode.CUSTOMER_REMOTE,
        remote=RemoteConfig(
            host="sas.customer.internal",
            environment_name="Enterprise",
            port=8591,
            username="svc_validation",
            credential_secret=SecretReference("sas_remote_credential_t1"),
        ),
    )
    view = integration.public_view()["remote"]
    assert view["credentials_configured"] is True
    assert "sas_remote_credential_t1" not in json.dumps(view)
    assert view["username"] == "svc_validation"


def test_the_remote_config_has_no_field_that_could_carry_a_command():
    """This product does not execute anything on customer infrastructure.

    There is no command, script, working directory or shell field - so there
    is nothing through which a user could submit one, by design rather than by
    validation.
    """
    fields = set(RemoteConfig.__dataclass_fields__)
    for forbidden in ("command", "script", "shell", "exec", "cmd", "working_directory"):
        assert forbidden not in fields


def test_managed_configuration_carries_a_price_reference_and_never_an_amount():
    """A number written now would be quoted back later as though it were terms."""
    managed = ManagedConfig(
        provider=None, usage_price_reference="price_managed_validation_v1"
    )
    view = managed.public_view()
    assert view["usage_price_reference"] == "price_managed_validation_v1"
    assert "amount" not in view
    assert "price" not in {k for k in view if k != "usage_price_reference"}
    for value in view.values():
        assert not isinstance(value, float), "no monetary amount belongs here"


def test_an_unconfigured_integration_says_so_plainly():
    integration = SASIntegration(integration_id="i-3", tenant_id="t-1")
    view = integration.public_view()
    assert view["configured"] is False
    assert view["mode"] == "not_configured"
    assert "viya" not in view and "remote" not in view


def test_a_connected_mode_without_an_acknowledgement_is_flagged():
    """The database enforces this too - see migration 0032 - because the API
    is not the only thing that will ever write that table."""
    integration = SASIntegration(
        integration_id="i-4",
        tenant_id="t-1",
        mode=SASIntegrationMode.CUSTOMER_VIYA,
        viya=ViyaConfig(base_url="https://x", environment_name="e"),
    )
    assert integration.requires_acknowledgement()
    assert integration.public_view()["acknowledged"] is False
