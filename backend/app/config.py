"""Application configuration.

All secrets are read from the process environment on the server only. Nothing in
this module is ever serialised to the frontend.

Required settings raise at startup if absent. Optional settings default to
``None`` and are surfaced through :func:`integration_status` so the UI can show
an honest "not configured" state instead of failing or, worse, fabricating
results.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AliasChoices,
    Field,
    PostgresDsn,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class IntegrationState(StrEnum):
    """Whether an external integration can be used."""

    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    KEYLESS = "keyless"  # usable without credentials, possibly rate-limited


def _resend_detail(has_key: bool, from_email: str | None) -> str:
    """Say which half of the email configuration is missing, not just that one is.

    "Not configured" sends an operator to look at the wrong variable half the
    time. Both are needed and either can be the one that was forgotten.
    """
    if has_key and from_email:
        return f"Alert email via Resend, from {from_email}."
    if has_key:
        return (
            "RESEND_API_KEY is set but NOTIFICATION_FROM_EMAIL is not, so "
            "nothing can be sent. Alerts are raised and recorded only."
        )
    if from_email:
        return (
            "NOTIFICATION_FROM_EMAIL is set but RESEND_API_KEY is not, so "
            "nothing can be sent. Alerts are raised and recorded only."
        )
    return (
        "No email provider. Alerts are raised and recorded, and nobody is told."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- app ---
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_allow_origins: str = "http://localhost:3000"

    # ----------------------------------------------------------- database ---
    database_url: PostgresDsn

    # ----------------------------------------------------------- supabase ---
    #: Accepts NEXT_PUBLIC_SUPABASE_URL as a fallback.
    #:
    #: It is the same value under two names - the project URL, which is public
    #: either way - and requiring both to be set separately is a trap rather
    #: than a safeguard. It caught us on the first real deployment: the frontend
    #: variable was set, the backend one was not, and because this field is
    #: required the whole API failed at import with a validation error rather
    #: than anything that pointed at a missing environment variable.
    #:
    #: Only the URL is aliased. The service role key deliberately has no such
    #: fallback: a NEXT_PUBLIC_ variable is compiled into the browser bundle,
    #: so accepting one there would invite someone to publish it.
    supabase_url: str = Field(
        validation_alias=AliasChoices("supabase_url", "next_public_supabase_url")
    )
    supabase_service_role_key: SecretStr
    #: Only needed by legacy projects that sign JWTs with a shared HS256 secret.
    #: Current Supabase projects publish asymmetric public keys via JWKS, which
    #: app/auth.py uses by preference, so this stays unset for most deployments.
    supabase_jwt_secret: SecretStr | None = None

    # ------------------------------------------------------------- openai ---
    openai_api_key: SecretStr
    openai_model_supervisor: str = "gpt-5"
    openai_model_research: str = "gpt-5"
    openai_model_extraction: str = "gpt-5-mini"
    openai_model_synthesis: str = "gpt-5"
    openai_model_verification: str = "gpt-5"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 3

    # ------------------------------------------------- literature providers ---
    # PubMed works without a key at 3 req/s; with a key at 10 req/s.
    ncbi_api_key: SecretStr | None = None
    ncbi_email: str | None = None
    crossref_mailto: str | None = None
    openalex_api_key: SecretStr | None = None

    # ----------------------------------------------------- patent providers ---
    epo_ops_consumer_key: SecretStr | None = None
    epo_ops_consumer_secret: SecretStr | None = None
    uspto_api_key: SecretStr | None = None

    # ------------------------------------------------------------- worker ---
    #: Shared secret for POST /api/worker/tick. The endpoint executes paid work,
    #: so it is not left open; the scheduler presents this header. Absent, the
    #: endpoint refuses every request rather than defaulting to open.
    worker_trigger_secret: SecretStr | None = None

    #: Elapsed seconds after which a slice stops taking on ANOTHER node.
    #:
    #: This is a gate on starting work, not a wall to stop at mid-node: a node
    #: already running is allowed to finish. Worst case is therefore
    #: `budget + longest_node`, which is what must fit inside the host's
    #: function timeout.
    #:
    #: Measured on a real run: the longest single node visit is ~120 s
    #: (supervisor_synthesis). At 150 s the worst case is ~280 s, inside
    #: Vercel Hobby's unraisable 300 s cap. On Pro (800 s) set this to 600.
    #: Zero disables slicing entirely, which is what a long-lived process wants.
    worker_slice_budget_seconds: int = Field(default=0, ge=0, le=3_600)

    #: Absolute origin this deployment answers on, e.g. https://app.vercel.app.
    #: Needed because a slice triggers its own successor over HTTP and a
    #: serverless invocation cannot otherwise know its own public URL - and now
    #: also to put a clickable link in an alert email.
    #:
    #: NEXT_PUBLIC_SITE_URL is accepted as the same value. It is what a person
    #: configuring a Next.js deployment sets, and having two variables for one
    #: origin is how you end up with alerts that link nowhere.
    public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("public_base_url", "next_public_site_url"),
    )

    # ------------------------------------------------------ notifications ---
    #: Absent means notifications are computed and recorded but nothing is
    #: emailed. Deliveries are then marked `skipped` with a reason rather than
    #: silently doing nothing, so nobody believes mail is going out when it is
    #: not.
    resend_api_key: SecretStr | None = None
    #: Also accepted as RESEND_FROM_EMAIL, which is what an operator setting
    #: RESEND_API_KEY naturally reaches for - the two look like a pair.
    #:
    #: This is not politeness. `build_notifier` needs BOTH values and falls
    #: back to sending nothing if either is missing, so a near-miss on the name
    #: disables alerts entirely and says nothing about why. It happened: a
    #: deployment with RESEND_API_KEY and RESEND_FROM_EMAIL both correctly set
    #: still delivered nothing, and the only symptom was 44 rows quietly
    #: marked `skipped`.
    #:
    #: Same reasoning as the SUPABASE_URL alias above. Where two names for one
    #: value are both reasonable, accepting both is a safeguard; insisting on
    #: one is a trap.
    notification_from_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "notification_from_email", "resend_from_email"
        ),
    )
    #: Where a reply goes. Alerts are sent from a no-reply address, so without
    #: this a person answering one is talking to nobody.
    email_reply_to: str | None = None

    # ------------------------------------------------------------- limits ---
    max_literature_results: int = Field(default=50, ge=1, le=200)
    max_patent_results: int = Field(default=30, ge=1, le=200)
    max_upload_size_mb: int = Field(default=25, ge=1, le=100)
    provider_cache_ttl_seconds: int = Field(default=86_400, ge=0)
    run_timeout_seconds: int = Field(default=1_800, ge=60)

    # --------------------------------------------------------- validators ---
    @field_validator("cors_allow_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return ",".join(part.strip() for part in v.split(",") if part.strip())

    @field_validator(
        "supabase_jwt_secret",
        "ncbi_api_key",
        "openalex_api_key",
        "epo_ops_consumer_key",
        "epo_ops_consumer_secret",
        "uspto_api_key",
        "worker_trigger_secret",
        "resend_api_key",
        mode="before",
    )
    @classmethod
    def _blank_optional_secret_is_absent(cls, v: object) -> object:
        """Treat `KEY=` in a .env file as unset rather than as an empty secret.

        A blank line is how people leave an optional credential unconfigured.
        Without this, `SecretStr('')` reads as "configured" everywhere: the
        integrations page would claim a provider is ready, and JWT fallback
        would attempt HMAC verification with an empty key.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(
        "ncbi_email", "crossref_mailto", "public_base_url",
        "notification_from_email", "email_reply_to", mode="before",
    )
    @classmethod
    def _blank_optional_string_is_absent(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("public_base_url")
    @classmethod
    def _no_trailing_slash(cls, v: str | None) -> str | None:
        """Normalise so callers can concatenate a path without doubling '/'."""
        return v.rstrip("/") if v else v

    # ---------------------------------------------------------- accessors ---
    @property
    def cors_origins(self) -> list[str]:
        return [o for o in self.cors_allow_origins.split(",") if o]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def epo_configured(self) -> bool:
        """EPO OPS needs *both* halves of the client-credentials pair."""
        return bool(self.epo_ops_consumer_key and self.epo_ops_consumer_secret)

    def integration_status(self) -> dict[str, dict[str, str | bool]]:
        """Per-provider availability, surfaced by ``GET /health/integrations``.

        Reports configuration only. It does not reach out over the network --
        reachability is probed separately so a slow provider cannot block the
        health endpoint.
        """
        return {
            "openai": {
                "state": IntegrationState.CONFIGURED,
                "required": True,
                "detail": "Model provider.",
            },
            "pubmed": {
                "state": (
                    IntegrationState.CONFIGURED
                    if self.ncbi_api_key
                    else IntegrationState.KEYLESS
                ),
                "required": True,
                "detail": (
                    "NCBI E-utilities at 10 req/s."
                    if self.ncbi_api_key
                    else "No NCBI_API_KEY: throttled to 3 req/s."
                ),
            },
            "europepmc": {
                "state": IntegrationState.KEYLESS,
                "required": True,
                "detail": "Europe PMC requires no credentials.",
            },
            "epo_ops": {
                "state": (
                    IntegrationState.CONFIGURED
                    if self.epo_configured
                    else IntegrationState.NOT_CONFIGURED
                ),
                "required": True,
                "detail": (
                    "EPO Open Patent Services."
                    if self.epo_configured
                    else "Not configured: patent search is unavailable and runs "
                    "proceed on literature evidence alone."
                ),
            },
            "crossref": {
                "state": (
                    IntegrationState.CONFIGURED
                    if self.crossref_mailto
                    else IntegrationState.KEYLESS
                ),
                "required": False,
                "detail": "DOI metadata enrichment.",
            },
            "openalex": {
                "state": (
                    IntegrationState.CONFIGURED
                    if self.openalex_api_key
                    else IntegrationState.KEYLESS
                ),
                "required": False,
                "detail": "Broader discovery and citation relationships.",
            },
            "uspto": {
                "state": (
                    IntegrationState.CONFIGURED
                    if self.uspto_api_key
                    else IntegrationState.NOT_CONFIGURED
                ),
                "required": False,
                "detail": "Optional secondary patent source.",
            },
            # Listed because its absence is the one that fails quietly. Every
            # other integration here announces itself when missing - a run
            # without patents says so in its own output. Notifications do not:
            # alerts are still raised and still recorded, the deliveries table
            # still fills up, and nobody is told. Production had 44 of those
            # before anyone thought to look.
            "resend": {
                # Half-configured counts as not configured. A key with no from
                # address cannot send, and reporting that as CONFIGURED would
                # be this system telling its own operator a comfortable lie.
                "state": (
                    IntegrationState.CONFIGURED
                    if (self.resend_api_key and self.notification_from_email)
                    else IntegrationState.NOT_CONFIGURED
                ),
                "required": False,
                "detail": _resend_detail(
                    bool(self.resend_api_key), self.notification_from_email
                ),
            },
        }

    def safe_summary(self) -> dict[str, object]:
        """Configuration safe to log. Contains no secret values."""
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "models": {
                "supervisor": self.openai_model_supervisor,
                "research": self.openai_model_research,
                "extraction": self.openai_model_extraction,
                "synthesis": self.openai_model_synthesis,
                "verification": self.openai_model_verification,
                "embedding": self.openai_embedding_model,
            },
            "integrations": {
                name: cfg["state"] for name, cfg in self.integration_status().items()
            },
            "limits": {
                "max_literature_results": self.max_literature_results,
                "max_patent_results": self.max_patent_results,
                "max_upload_size_mb": self.max_upload_size_mb,
            },
        }


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that a missing variable fails once, loudly, at startup rather than
    intermittently deep inside a research run.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = [
            ".".join(str(p) for p in err["loc"])
            for err in exc.errors()
            if err["type"] == "missing"
        ]
        detail = (
            f"Missing required environment variables: {', '.join(missing)}"
            if missing
            else str(exc)
        )
        print(
            f"\nConfiguration error.\n{detail}\n\n"
            f"Copy .env.example to {BACKEND_DIR / '.env'} and fill in the "
            f"required values.\n",
            file=sys.stderr,
        )
        raise
