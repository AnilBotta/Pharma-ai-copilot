"""Configuration loading, and the one alias that exists.

Required settings must fail loudly when absent - a service that starts without
its database URL and discovers the problem on the first user request is worse
than one that refuses to start. The tests here pin that behaviour, plus the
single deliberate exception to it.
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import ValidationError

MINIMAL = {
    "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role",
    "OPENAI_API_KEY": "sk-test",
}

#: Cleared before every case. Anything a test asserts the ABSENCE of has to be
#: here, or the result depends on what happens to be exported on the machine
#: running it - which is the same reason the fixture points env_file at a path
#: that does not exist.
SUPABASE_KEYS = (
    "SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "RESEND_API_KEY",
    "NOTIFICATION_FROM_EMAIL",
    "RESEND_FROM_EMAIL",
)


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """Construct Settings from an explicit environment only.

    pydantic-settings also reads backend/.env, so without pointing env_file at
    a path that does not exist these tests would pass or fail depending on
    whose machine they ran on.
    """
    from app.config import Settings

    def _build(**env: str):
        for key in SUPABASE_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=tmp_path / "absent.env")

    return _build


class TestEmailProviderIsReportable:
    """The one integration whose absence fails quietly must be visible.

    Every other provider announces itself when missing - a run without patents
    says so in its own output. Notifications do not: alerts are raised,
    deliveries are recorded, and nobody is told. Production accumulated 44 of
    those before anyone looked, and /api/health did not mention email at all.
    """

    def _resend(self, settings):
        return settings.integration_status()["resend"]

    def test_absent_is_reported_with_the_consequence(self, build) -> None:
        status = self._resend(build(**MINIMAL, SUPABASE_URL="https://x.supabase.co"))
        assert status["state"] == "not_configured"
        assert "nobody is told" in str(status["detail"])

    def test_fully_configured_names_the_sender(self, build) -> None:
        status = self._resend(
            build(
                **MINIMAL,
                SUPABASE_URL="https://x.supabase.co",
                RESEND_API_KEY="re_test",
                NOTIFICATION_FROM_EMAIL="alerts@example.test",
            )
        )
        assert status["state"] == "configured"
        assert "alerts@example.test" in str(status["detail"])

    def test_a_key_without_a_sender_is_not_configured(self, build) -> None:
        """Half-configured cannot send, so reporting it as configured would be
        the system telling its own operator a comfortable lie."""
        status = self._resend(
            build(
                **MINIMAL,
                SUPABASE_URL="https://x.supabase.co",
                RESEND_API_KEY="re_test",
            )
        )
        assert status["state"] == "not_configured"
        # And it must name WHICH half is missing, or the operator checks the
        # wrong variable half the time.
        assert "NOTIFICATION_FROM_EMAIL" in str(status["detail"])

    def test_resend_from_email_is_accepted_as_the_sender(self, build) -> None:
        """RESEND_FROM_EMAIL is what somebody setting RESEND_API_KEY reaches for.

        A real deployment had both correctly set under that pairing and still
        delivered nothing, because the field only bound NOTIFICATION_FROM_EMAIL.
        `build_notifier` needs both, so a near-miss on one name disables alerts
        entirely and reports nothing about why.
        """
        status = self._resend(
            build(
                **MINIMAL,
                SUPABASE_URL="https://x.supabase.co",
                RESEND_API_KEY="re_test",
                RESEND_FROM_EMAIL="alerts@example.test",
            )
        )
        assert status["state"] == "configured"
        assert "alerts@example.test" in str(status["detail"])

    def test_the_explicit_name_still_wins(self, build) -> None:
        settings = build(
            **MINIMAL,
            SUPABASE_URL="https://x.supabase.co",
            NOTIFICATION_FROM_EMAIL="explicit@example.test",
            RESEND_FROM_EMAIL="alias@example.test",
        )
        assert settings.notification_from_email == "explicit@example.test"

    def test_a_sender_without_a_key_is_not_configured(self, build) -> None:
        status = self._resend(
            build(
                **MINIMAL,
                SUPABASE_URL="https://x.supabase.co",
                NOTIFICATION_FROM_EMAIL="alerts@example.test",
            )
        )
        assert status["state"] == "not_configured"
        assert "RESEND_API_KEY" in str(status["detail"])


class TestSupabaseUrlAlias:
    """SUPABASE_URL accepts NEXT_PUBLIC_SUPABASE_URL as a fallback.

    The same value under two names. Requiring both to be set separately is a
    trap, and it sprang on the first real deployment: the frontend variable was
    configured, the backend one was not, and the API failed at import with a
    validation error that named a field rather than a missing variable.
    """

    def test_explicit_value_is_used(self, build) -> None:
        settings = build(**MINIMAL, SUPABASE_URL="https://explicit.supabase.co")
        assert settings.supabase_url == "https://explicit.supabase.co"

    def test_next_public_is_accepted_as_a_fallback(self, build) -> None:
        settings = build(
            **MINIMAL, NEXT_PUBLIC_SUPABASE_URL="https://fallback.supabase.co"
        )
        assert settings.supabase_url == "https://fallback.supabase.co"

    def test_explicit_wins_over_the_fallback(self, build) -> None:
        settings = build(
            **MINIMAL,
            SUPABASE_URL="https://wins.supabase.co",
            NEXT_PUBLIC_SUPABASE_URL="https://loses.supabase.co",
        )
        assert settings.supabase_url == "https://wins.supabase.co"

    def test_absent_entirely_still_fails(self, build) -> None:
        """The alias is a convenience, not a way to start unconfigured."""
        with pytest.raises(ValidationError):
            build(**MINIMAL)

    def test_the_service_role_key_has_no_such_fallback(self, build) -> None:
        """Deliberate asymmetry, and the reason the alias is URL-only.

        A NEXT_PUBLIC_ variable is compiled into the browser bundle. Accepting
        one for the service role key would invite somebody to set it there, and
        that key bypasses every row-level security policy in the database.
        """
        with pytest.raises(ValidationError):
            build(
                DATABASE_URL=MINIMAL["DATABASE_URL"],
                OPENAI_API_KEY=MINIMAL["OPENAI_API_KEY"],
                SUPABASE_URL="https://x.supabase.co",
                NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY="should-not-be-honoured",
            )


class TestRequiredSettingsFailLoudly:
    @pytest.mark.parametrize("missing", ["DATABASE_URL", "OPENAI_API_KEY"])
    def test_a_missing_required_value_refuses_to_start(self, build, missing) -> None:
        env = {**MINIMAL, "SUPABASE_URL": "https://x.supabase.co"}
        env.pop(missing)
        with pytest.raises(ValidationError):
            build(**env)
