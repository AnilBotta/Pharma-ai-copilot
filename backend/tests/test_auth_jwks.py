"""JWT verification against asymmetric (ES256) tokens.

Current Supabase projects sign with ES256 and publish public keys via JWKS.
The original implementation assumed the legacy HS256 shared secret and would
have rejected every real token with a blanket 401 and no obvious cause.

These tests use a locally generated EC keypair served through a mocked JWKS
endpoint, which is the same verification path a real Supabase token takes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

SUPABASE_URL = "https://testproject.supabase.co"
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
USER_ID = "11111111-1111-1111-1111-111111111111"
KID = "test-key-1"


@pytest.fixture
def ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KID, "alg": "ES256", "use": "sig"})
    return private_key, {"keys": [jwk]}


def es256_token(private_key, **overrides) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": USER_ID,
        "email": "scientist@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "exp": now + 3600,
        "iat": now,
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": KID})


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Configure with NO shared secret, as a modern project would be.

    env_file is pointed at a path that does not exist so the developer's own
    backend/.env cannot leak values into the test.
    """
    from app.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / "absent.env")

    for key, value in {
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "OPENAI_API_KEY": "sk-test",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)

    from app.auth import reset_jwks_cache
    from app.config import get_settings

    get_settings.cache_clear()
    reset_jwks_cache()
    yield
    get_settings.cache_clear()
    reset_jwks_cache()


@pytest.fixture
def client() -> TestClient:
    from contextlib import asynccontextmanager

    from app.main import create_app
    from tests.test_api import FakeRepository

    @asynccontextmanager
    async def noop(app):
        yield

    app = create_app()
    app.router.lifespan_context = noop
    app.state.repository = FakeRepository()
    return TestClient(app)


class TestAsymmetricVerification:
    @respx.mock
    def test_valid_es256_token_is_accepted(self, client, ec_keypair) -> None:
        private_key, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        response = client.get(
            "/api/projects",
            headers={"Authorization": f"Bearer {es256_token(private_key)}"},
        )
        assert response.status_code == 200

    @respx.mock
    def test_no_shared_secret_is_required(self, client, ec_keypair) -> None:
        # The whole point: a modern project needs no SUPABASE_JWT_SECRET.
        from app.config import get_settings

        assert get_settings().supabase_jwt_secret is None

        private_key, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))
        response = client.get(
            "/api/projects",
            headers={"Authorization": f"Bearer {es256_token(private_key)}"},
        )
        assert response.status_code == 200

    @respx.mock
    def test_token_signed_by_a_different_key_is_rejected(self, client, ec_keypair) -> None:
        _, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        attacker_key = ec.generate_private_key(ec.SECP256R1())
        forged = es256_token(attacker_key)

        assert client.get(
            "/api/projects", headers={"Authorization": f"Bearer {forged}"}
        ).status_code == 401

    @respx.mock
    def test_expired_token_is_rejected(self, client, ec_keypair) -> None:
        private_key, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        now = int(datetime.now(UTC).timestamp())
        expired = es256_token(private_key, exp=now - 60, iat=now - 3600)

        response = client.get(
            "/api/projects", headers={"Authorization": f"Bearer {expired}"}
        )
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @respx.mock
    def test_wrong_audience_is_rejected(self, client, ec_keypair) -> None:
        private_key, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        token = es256_token(private_key, aud="anon")
        assert client.get(
            "/api/projects", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 401

    @respx.mock
    def test_unsigned_token_is_rejected(self, client, ec_keypair) -> None:
        # alg:none must never be accepted.
        _, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        now = int(datetime.now(UTC).timestamp())
        unsigned = jwt.encode(
            {"sub": USER_ID, "aud": "authenticated", "exp": now + 3600},
            key="",
            algorithm="none",
        )
        assert client.get(
            "/api/projects", headers={"Authorization": f"Bearer {unsigned}"}
        ).status_code == 401

    @respx.mock
    def test_hs256_token_is_not_accepted_when_project_is_asymmetric(
        self, client, ec_keypair
    ) -> None:
        # Algorithm-confusion guard: an HS256 token must not be verified using
        # the public key as an HMAC secret.
        _, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        now = int(datetime.now(UTC).timestamp())
        hs_token = jwt.encode(
            {"sub": USER_ID, "aud": "authenticated", "exp": now + 3600},
            "any-secret-at-all-padded-to-32-bytes",
            algorithm="HS256",
        )
        assert client.get(
            "/api/projects", headers={"Authorization": f"Bearer {hs_token}"}
        ).status_code == 401


class TestHealthReporting:
    @respx.mock
    def test_health_reports_the_asymmetric_scheme(self, client, ec_keypair) -> None:
        _, jwks = ec_keypair
        respx.get(JWKS_URL).mock(httpx.Response(200, json=jwks))

        body = client.get("/api/health").json()
        assert "Asymmetric" in body["auth"]
        assert "ES256" in body["auth"]

    @respx.mock
    def test_health_flags_having_no_verification_method(self, client) -> None:
        respx.get(JWKS_URL).mock(httpx.Response(404))

        body = client.get("/api/health").json()
        assert body["status"] == "degraded"
        assert "No verification method" in body["auth"]
