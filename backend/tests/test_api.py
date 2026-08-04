"""HTTP API behaviour: auth enforcement, validation, and run lifecycle.

The database is faked, so these exercise routing, authentication, input
validation and serialisation rather than SQL. Real SQL is exercised against the
live database separately.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from app.repository import NotFound

# At least 32 bytes, matching the HS256 minimum a real Supabase secret meets.
JWT_SECRET = "test-jwt-secret-padded-to-32-bytes-minimum"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal valid configuration, and a cleared settings cache."""
    for key, value in {
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "OPENAI_API_KEY": "sk-test",
        "CORS_ALLOW_ORIGINS": "http://localhost:3000",
    }.items():
        monkeypatch.setenv(key, value)

    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def token_for(user_id: str, *, expired: bool = False, audience: str = "authenticated") -> str:
    now = int(datetime.now(UTC).timestamp())
    return jwt.encode(
        {
            "sub": user_id,
            "email": "scientist@example.com",
            "role": "authenticated",
            "aud": audience,
            "exp": now - 60 if expired else now + 3600,
            "iat": now,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


USER_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
RUN_ID = "33333333-3333-3333-3333-333333333333"


def auth_headers(user_id: str = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


class FakeRepository:
    """In-memory stand-in enforcing the same ownership rules as the real one."""

    def __init__(self) -> None:
        self.owner = USER_ID
        self.runs: dict[str, dict] = {}
        self.events: list[dict] = []
        self.created_payloads: list[dict] = []

    def _check(self, user_id: str) -> None:
        if user_id != self.owner:
            raise NotFound("Not found.")

    async def list_projects(self, user_id: str) -> list[dict]:
        self._check(user_id)
        return [
            {
                "id": PROJECT_ID,
                "user_id": user_id,
                "name": "Peptide Depot Delivery Feasibility Assessment",
                "code": None,
                "description": None,
                "molecule": None,
                "indication": None,
                "is_seed": True,
                "run_count": 1,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]

    async def create_project(self, user_id: str, **kwargs: Any) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": kwargs["name"],
            "code": kwargs.get("code"),
            "description": kwargs.get("description"),
            "molecule": kwargs.get("molecule"),
            "indication": kwargs.get("indication"),
            "is_seed": False,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

    async def create_run(self, user_id: str, project_id: str, payload: dict) -> dict:
        self._check(user_id)
        if project_id != PROJECT_ID:
            raise NotFound("Project not found.")
        self.created_payloads.append(payload)
        run = {
            "id": RUN_ID,
            "project_id": project_id,
            "user_id": user_id,
            "status": "queued",
            **payload,
        }
        self.runs[RUN_ID] = run
        return run

    async def get_run(self, user_id: str, run_id: str) -> dict:
        self._check(user_id)
        run = self.runs.get(run_id)
        if run is None:
            raise NotFound("Run not found.")
        return {
            "id": run_id,
            "project_id": PROJECT_ID,
            "user_id": user_id,
            "status": run.get("status", "queued"),
            "original_question": run.get("original_question", "q" * 20),
            "current_node": None,
            "progress_pct": 0,
            "evidence_count": 0,
            "error_message": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "jurisdictions": [],
            "max_results": 50,
            "contradictions": [],
            "evidence_gaps": [],
            "warnings": [],
            "section_confidence": {},
            "cancel_requested": False,
            "started_at": None,
            "completed_at": None,
            "created_at": datetime.now(UTC),
        }

    async def list_runs(self, user_id: str, **kwargs: Any) -> list[dict]:
        self._check(user_id)
        return [await self.get_run(user_id, r) for r in self.runs]

    async def request_cancel(self, user_id: str, run_id: str) -> None:
        self._check(user_id)
        if run_id not in self.runs:
            raise NotFound("Run not found.")
        self.runs[run_id]["cancel_requested"] = True

    async def retry_run(self, user_id: str, run_id: str) -> None:
        self._check(user_id)
        run = self.runs.get(run_id)
        if run is None:
            raise NotFound("Run not found.")
        if run.get("status") not in ("failed", "cancelled"):
            raise ValueError(f"Run is {run.get('status')}; only failed or cancelled runs retry.")
        run["status"] = "queued"

    async def get_events(self, user_id: str, run_id: str, **kwargs: Any) -> list[dict]:
        self._check(user_id)
        return self.events

    async def get_evidence(self, user_id: str, run_id: str) -> list[dict]:
        self._check(user_id)
        return []

    async def get_report(self, user_id: str, run_id: str) -> list[dict]:
        self._check(user_id)
        return []

    async def get_search_queries(self, user_id: str, run_id: str) -> list[dict]:
        self._check(user_id)
        return []

    async def get_run_errors(self, user_id: str, run_id: str) -> list[dict]:
        self._check(user_id)
        return []

    async def dashboard_summary(self, user_id: str) -> dict:
        self._check(user_id)
        return {
            "running": 1, "queued": 0, "completed": 3, "failed": 1,
            "total_runs": 5, "total_cost": 1.25, "total_tokens": 40000,
            "source_counts": {"literature": 42, "patents": 7},
        }


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    app = create_app()
    # Bypass lifespan so no real database connection is attempted.
    app.router.lifespan_context = _noop_lifespan
    app.state.repository = FakeRepository()
    return TestClient(app)


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):
    yield


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


class TestAuthentication:
    @pytest.mark.parametrize(
        "path",
        ["/api/projects", "/api/runs", "/api/dashboard", f"/api/runs/{RUN_ID}"],
    )
    def test_protected_routes_reject_anonymous_requests(
        self, client: TestClient, path: str
    ) -> None:
        # The prototype served every page to unauthenticated callers. This is
        # the regression guard for that (audit finding S1).
        assert client.get(path).status_code == 401

    def test_expired_token_is_rejected(self, client: TestClient) -> None:
        headers = {"Authorization": f"Bearer {token_for(USER_ID, expired=True)}"}
        response = client.get("/api/projects", headers=headers)
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    def test_token_signed_with_the_wrong_secret_is_rejected(self, client: TestClient) -> None:
        forged = jwt.encode(
            {"sub": USER_ID, "aud": "authenticated", "exp": 9999999999},
            "a-different-secret-also-padded-to-32-bytes",
            algorithm="HS256",
        )
        response = client.get("/api/projects", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401

    def test_wrong_audience_is_rejected(self, client: TestClient) -> None:
        headers = {"Authorization": f"Bearer {token_for(USER_ID, audience='anon')}"}
        assert client.get("/api/projects", headers=headers).status_code == 401

    def test_malformed_token_is_rejected(self, client: TestClient) -> None:
        headers = {"Authorization": "Bearer not.a.jwt"}
        assert client.get("/api/projects", headers=headers).status_code == 401

    def test_rejection_does_not_explain_why_a_token_failed(self, client: TestClient) -> None:
        # Detail beyond "invalid" tells an attacker which part to fix next.
        forged = jwt.encode(
            {"sub": USER_ID, "aud": "authenticated", "exp": 9999999999},
            "a-different-secret-also-padded-to-32-bytes",
            algorithm="HS256",
        )
        detail = client.get(
            "/api/projects", headers={"Authorization": f"Bearer {forged}"}
        ).json()["detail"]
        assert detail == "Invalid authentication token."

    def test_valid_token_is_accepted(self, client: TestClient) -> None:
        assert client.get("/api/projects", headers=auth_headers()).status_code == 200


class TestOwnership:
    def test_another_users_run_is_not_found(self, client: TestClient) -> None:
        other = "99999999-9999-9999-9999-999999999999"
        response = client.get(f"/api/runs/{RUN_ID}", headers=auth_headers(other))
        assert response.status_code == 404

    def test_not_found_does_not_reveal_existence(self, client: TestClient) -> None:
        other = "99999999-9999-9999-9999-999999999999"
        body = client.get(f"/api/runs/{RUN_ID}", headers=auth_headers(other)).json()
        assert "not found" in body["detail"].lower()
        assert "permission" not in body["detail"].lower()


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


class TestHealth:
    def test_health_is_public(self, client: TestClient) -> None:
        assert client.get("/api/health").status_code == 200

    def test_health_reports_every_integration(self, client: TestClient) -> None:
        names = {i["name"] for i in client.get("/api/health").json()["integrations"]}
        assert {"openai", "pubmed", "europepmc", "epo_ops"} <= names

    def test_unconfigured_integration_is_reported_honestly(self, client: TestClient) -> None:
        integrations = {
            i["name"]: i for i in client.get("/api/health").json()["integrations"]
        }
        assert integrations["epo_ops"]["state"] == "not_configured"
        assert "not configured" in integrations["epo_ops"]["detail"].lower()

    def test_health_exposes_no_secrets(self, client: TestClient) -> None:
        body = client.get("/api/health").text
        assert "sk-test" not in body
        assert JWT_SECRET not in body
        assert "service-role" not in body


# --------------------------------------------------------------------------- #
# Run creation and validation
# --------------------------------------------------------------------------- #


VALID_RUN = {
    "project_id": PROJECT_ID,
    "original_question": (
        "Evaluate the feasibility of a sustained-release depot injection of a "
        "therapeutic peptide using carbon nanotube-based delivery technology."
    ),
    "max_results": 25,
}


class TestRunCreation:
    def test_run_is_accepted_and_returns_an_id_immediately(self, client: TestClient) -> None:
        response = client.post("/api/runs", json=VALID_RUN, headers=auth_headers())
        assert response.status_code == 202
        body = response.json()
        assert body["run_id"] == RUN_ID
        assert body["status"] == "queued"

    def test_unknown_project_is_rejected(self, client: TestClient) -> None:
        payload = {**VALID_RUN, "project_id": str(uuid.uuid4())}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 404

    @pytest.mark.parametrize("question", ["", "   ", "too short"])
    def test_question_must_be_substantial(self, client: TestClient, question: str) -> None:
        payload = {**VALID_RUN, "original_question": question}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 422

    def test_question_length_is_bounded(self, client: TestClient) -> None:
        # An unbounded question becomes an unbounded prompt.
        payload = {**VALID_RUN, "original_question": "x" * 5000}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 422

    def test_max_results_is_bounded(self, client: TestClient) -> None:
        # An unbounded result count becomes unbounded spend.
        payload = {**VALID_RUN, "max_results": 100000}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 422

    def test_reversed_date_range_is_rejected(self, client: TestClient) -> None:
        payload = {**VALID_RUN, "date_from": 2024, "date_to": 2010}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 422

    def test_jurisdiction_codes_are_validated(self, client: TestClient) -> None:
        payload = {**VALID_RUN, "jurisdictions": ["EP", "not-a-code"]}
        assert client.post("/api/runs", json=payload, headers=auth_headers()).status_code == 422

    def test_jurisdictions_are_normalised_to_uppercase(self, client: TestClient) -> None:
        payload = {**VALID_RUN, "jurisdictions": ["ep", "us"]}
        client.post("/api/runs", json=payload, headers=auth_headers())
        repository: FakeRepository = client.app.state.repository
        assert repository.created_payloads[-1]["jurisdictions"] == ["EP", "US"]

    def test_creation_requires_authentication(self, client: TestClient) -> None:
        assert client.post("/api/runs", json=VALID_RUN).status_code == 401


class TestRunLifecycle:
    def _create(self, client: TestClient) -> None:
        client.post("/api/runs", json=VALID_RUN, headers=auth_headers())

    def test_run_can_be_cancelled(self, client: TestClient) -> None:
        self._create(client)
        response = client.post(f"/api/runs/{RUN_ID}/cancel", headers=auth_headers())
        assert response.status_code == 204
        assert client.app.state.repository.runs[RUN_ID]["cancel_requested"] is True

    def test_cancelling_an_unknown_run_is_404(self, client: TestClient) -> None:
        assert client.post(
            f"/api/runs/{uuid.uuid4()}/cancel", headers=auth_headers()
        ).status_code == 404

    def test_only_failed_or_cancelled_runs_can_retry(self, client: TestClient) -> None:
        self._create(client)
        response = client.post(f"/api/runs/{RUN_ID}/retry", headers=auth_headers())
        assert response.status_code == 409

    def test_failed_run_can_be_retried(self, client: TestClient) -> None:
        self._create(client)
        client.app.state.repository.runs[RUN_ID]["status"] = "failed"
        response = client.post(f"/api/runs/{RUN_ID}/retry", headers=auth_headers())
        assert response.status_code == 202
        assert client.app.state.repository.runs[RUN_ID]["status"] == "queued"


class TestDashboard:
    def test_returns_real_counts(self, client: TestClient) -> None:
        body = client.get("/api/dashboard", headers=auth_headers()).json()
        assert body["completed"] == 3
        assert body["failed"] == 1
        assert body["source_counts"]["literature"] == 42
