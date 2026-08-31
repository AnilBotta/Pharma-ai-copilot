"""Configuration for each SAS mode, split by what may be read back.

THE SPLIT IS THE DESIGN

Every field below is on one side of a line: it is either something a GET may
return, or it is a secret that may never leave the server. Putting that
distinction in the type system rather than in a reviewer's memory is what stops
a secret reaching a log, an audit row, an analytics event or a URL - all of
which have happened to somebody, in every product that kept both kinds of field
in one dictionary.

    NON-SECRET   base_url, environment name, organisation, auth type, tenant
                 -> returned by the API, safe to display, safe to audit

    SECRET       client secret, tokens, passwords
                 -> stored by REFERENCE. The ordinary settings tables hold a
                    pointer into the project's secret store, never a value.

A GET on an integration answers `configured: true`. It never answers with the
secret, not even masked - a mask is still a disclosure of length, and there is
no reason to send one.

WHY THE SECRET REFERENCE IS A STRING AND NOT A VALUE

The project's existing answer for secrets at rest is Supabase Vault
(`private.worker_config()` in migration 0018 reads `vault.decrypted_secrets`,
chosen because Vault encrypts at rest and that view is readable only by
privileged roles). This module stores the NAME of a Vault secret. Nothing in
the application layer ever holds the plaintext, so nothing in the application
layer can leak it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.sas_validation.modes import ManagedBillingMode, SASIntegrationMode


class ViyaAuthType(StrEnum):
    """How a customer's Viya environment authenticates.

    Listed rather than free text because each implies a different set of
    required fields, and a text box would let an operator describe a scheme the
    adapter cannot perform.
    """

    OAUTH_CLIENT_CREDENTIALS = "oauth_client_credentials"
    OAUTH_AUTHORIZATION_CODE = "oauth_authorization_code"
    # Suppressed below because this names an authentication SCHEME, not a
    # token. No token appears in this module - only a SecretReference to one,
    # which is the whole point of the file.
    PERSONAL_ACCESS_TOKEN = "personal_access_token"  # noqa: S105


class RemoteAuthMethod(StrEnum):
    KERBEROS = "kerberos"
    SERVICE_ACCOUNT = "service_account"
    #: The customer's own gateway fronts SAS and authenticates us to it.
    GATEWAY_MEDIATED = "gateway_mediated"


@dataclass(frozen=True, slots=True)
class SecretReference:
    """A pointer into the secret store. Never the secret.

    `name` is a Vault secret name. This object is safe to log, audit and return
    from an API precisely because it carries no value and no way to obtain one.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("a secret reference needs a name")
        # A value that looks like a credential has been passed where a
        # reference belongs. Refuse loudly: the alternative is storing it.
        if len(self.name) > 128 or any(c in self.name for c in " \t\n"):
            raise ValueError(
                "secret reference names are short identifiers. This looks like "
                "a secret value rather than a reference to one, and storing it "
                "here would put it in an ordinary settings table."
            )


@dataclass(frozen=True, slots=True)
class ManagedConfig:
    """Product state for a service that does not exist yet.

    Every field is metadata about a future commercial arrangement. There is no
    price here, and there will not be one until terms are agreed - a number
    written now would be quoted back later as though it had been.
    """

    provider: str | None = None
    service_region: str | None = None
    billing_mode: ManagedBillingMode = ManagedBillingMode.NOT_APPLICABLE
    usage_limit: int | None = None
    validation_runs_remaining: int | None = None
    #: A reference to a price in the billing system, never an amount.
    usage_price_reference: str | None = None
    connection_status: str = "not_provisioned"

    def public_view(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "service_region": self.service_region,
            "billing_mode": self.billing_mode.value,
            "usage_limit": self.usage_limit,
            "validation_runs_remaining": self.validation_runs_remaining,
            "usage_price_reference": self.usage_price_reference,
            "connection_status": self.connection_status,
        }


@dataclass(frozen=True, slots=True)
class ViyaConfig:
    """Customer-owned SAS Viya. Configuration abstraction only."""

    base_url: str
    environment_name: str
    organization_name: str | None = None
    auth_type: ViyaAuthType = ViyaAuthType.OAUTH_CLIENT_CREDENTIALS
    tenant_id: str | None = None

    #: `client_id` is treated as a SECRET here. Some deployments regard it as
    #: public and some do not, and the cost of being wrong is asymmetric: a
    #: needlessly protected identifier costs nothing, a disclosed one that the
    #: customer considered confidential is an incident.
    client_id_secret: SecretReference | None = None
    client_secret: SecretReference | None = None
    access_token_secret: SecretReference | None = None
    refresh_token_secret: SecretReference | None = None

    def public_view(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "environment_name": self.environment_name,
            "organization_name": self.organization_name,
            "auth_type": self.auth_type.value,
            "tenant_id": self.tenant_id,
            "credentials_configured": bool(self.client_secret or self.access_token_secret),
        }


@dataclass(frozen=True, slots=True)
class RemoteConfig:
    """Customer-managed enterprise or remote SAS.

    Note what is NOT here: no command, no script, no working directory, no
    shell. This application does not execute anything on a customer's
    infrastructure, and there is no field through which it could be asked to.
    """

    host: str
    environment_name: str
    port: int | None = None
    authentication_method: RemoteAuthMethod = RemoteAuthMethod.SERVICE_ACCOUNT
    username: str | None = None
    credential_secret: SecretReference | None = None

    def public_view(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "environment_name": self.environment_name,
            "authentication_method": self.authentication_method.value,
            "username": self.username,
            "credentials_configured": self.credential_secret is not None,
        }


@dataclass(frozen=True, slots=True)
class AuthorisationAcknowledgement:
    """Who confirmed the organisation may connect this environment, and when.

    An ACKNOWLEDGEMENT, not a verification. This application cannot check
    anyone's SAS entitlement and does not claim to; it records that a named
    person stated it on a date.
    """

    actor_user_id: str
    acknowledged_at: str
    integration_id: str
    text: str


@dataclass(frozen=True, slots=True)
class SASIntegration:
    """One organisation's SAS validation configuration."""

    integration_id: str
    tenant_id: str
    mode: SASIntegrationMode = SASIntegrationMode.NOT_CONFIGURED
    managed: ManagedConfig | None = None
    viya: ViyaConfig | None = None
    remote: RemoteConfig | None = None
    acknowledgement: AuthorisationAcknowledgement | None = None
    notes: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    def public_view(self) -> dict[str, object]:
        """What a GET returns. Contains no secret and no masked secret."""
        view: dict[str, object] = {
            "integration_id": self.integration_id,
            "mode": self.mode.value,
            "configured": self.mode is not SASIntegrationMode.NOT_CONFIGURED,
            "acknowledged": self.acknowledgement is not None,
            "capabilities": list(self.capabilities),
        }
        if self.managed is not None:
            view["managed"] = self.managed.public_view()
        if self.viya is not None:
            view["viya"] = self.viya.public_view()
        if self.remote is not None:
            view["remote"] = self.remote.public_view()
        return view

    def requires_acknowledgement(self) -> bool:
        return (
            self.mode.requires_authorisation_acknowledgement
            and self.acknowledgement is None
        )


__all__ = [
    "AuthorisationAcknowledgement",
    "ManagedConfig",
    "RemoteAuthMethod",
    "RemoteConfig",
    "SASIntegration",
    "SecretReference",
    "ViyaAuthType",
    "ViyaConfig",
]
