"""The API must not flatten two statuses into one word.

WHAT THESE TESTS ARE ACTUALLY DEFENDING

The engine keeps `implementation` and `validation` apart with some care. The
place that separation dies is a serialisation layer, three modules away from
anybody thinking about it, where somebody writes `status: "available"` because
the frontend wanted one string. These tests sit at that boundary.

They also check the boring but load-bearing property that the capability
surface needs no database. It is served from code, so it stays available in
exactly the degraded deployment where somebody most needs to ask what still
works - and a test that constructs the app with no repository at all is the
only way that claim stays true.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager

import pytest
from be_stats.dossier import CAPABILITY_MATRIX, method_catalogue
from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, current_user


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def client() -> TestClient:
    """An app with NO database of any kind.

    Not a convenience. The capability surface must answer without one, and the
    only honest way to assert that is to give it nothing to fall back on.
    """
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        id="00000000-0000-0000-0000-000000000001",
        email="reviewer@example.com",
        # Any signed-in user. The capability surface carries no privileged
        # content: it says what the engine can be trusted with, which is
        # exactly what a customer is entitled to know.
        role="scientist",
    )
    return TestClient(app)


@pytest.fixture
def anonymous_client() -> TestClient:
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    return TestClient(app)


PATHS = [
    "/api/statistics/methods",
    "/api/statistics/capabilities",
    "/api/statistics/routing",
    "/api/statistics/refusals",
    "/api/statistics/dossier",
]


@pytest.mark.parametrize("path", PATHS)
def test_every_route_requires_authentication(anonymous_client: TestClient, path):
    """Not secret, and not public. Consistency is worth more than convenience."""
    response = anonymous_client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_every_route_answers_without_a_database(client: TestClient, path):
    response = client.get(path)
    assert response.status_code == 200, response.text


def test_the_catalogue_matches_the_engine(client: TestClient):
    """A view, not a second copy. Field by field."""
    body = client.get("/api/statistics/methods").json()
    expected = method_catalogue()
    assert len(body) == len(expected)
    for row, entry in zip(body, expected, strict=True):
        assert row["capability_id"] == entry.capability_id
        assert row["status"] == str(entry.status)
        assert row["qualification"] == entry.qualification


def test_the_api_never_shows_everything_as_available():
    """The single failure this surface exists to prevent."""
    statuses = {str(entry.status) for entry in method_catalogue()}
    assert len(statuses) >= 2
    assert "NOT IMPLEMENTED" in statuses
    for status in statuses:
        assert status != "Available"


def test_the_wire_keeps_implementation_and_validation_apart(client: TestClient):
    """Both axes survive to the client, plus the display bucket as a third.

    If the two ever collapse into one field the frontend has no way to show
    the distinction, whatever the design says.
    """
    rows = client.get("/api/statistics/capabilities").json()
    assert rows
    for row in rows:
        assert "implementation_status" in row
        assert "validation_status" in row
        assert "display_status" in row

    implemented_unvalidated = [
        r for r in rows if r["validation_status"] == "implemented_unvalidated"
    ]
    assert implemented_unvalidated, "No unvalidated rows; this would pass vacuously."
    for row in implemented_unvalidated:
        assert row["implementation_status"] == "implemented"
        assert row["display_status"] != "VALIDATED", (
            f"{row['capability_id']} is unvalidated and displays as VALIDATED."
        )


def test_no_capability_is_serialised_without_its_limitations(client: TestClient):
    rows = client.get("/api/statistics/capabilities").json()
    for row in rows:
        assert row["known_limitations"], row["capability_id"]


def test_partial_appendix_c_is_reported_as_not_implemented(client: TestClient):
    rows = {r["capability_id"]: r for r in client.get("/api/statistics/capabilities").json()}
    partial = rows["FDA_REPLICATE_STANDARD_ABE_PARTIAL"]
    assert partial["validation_status"] == "not_implemented"
    assert partial["implementation_status"] == "not_implemented"
    assert partial["display_status"] == "NOT IMPLEMENTED"
    assert partial["decision_supported"] is False
    assert "APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED" in partial[
        "refusal_conditions"
    ]


def test_the_dossier_reports_the_partial_oracle_flags(client: TestClient):
    body = client.get("/api/statistics/dossier").json()
    assert body["partial_oracle_ready"] is False
    assert body["real_sas_oracle_status"] == "PENDING"


def test_the_dossier_reports_unestablished_claims_rather_than_hiding_them(
    client: TestClient,
):
    """A missing external oracle environment is never silently a pass."""
    body = client.get("/api/statistics/dossier").json()
    assert body["certification_blockers"], (
        "The external oracle comparisons cannot run here, and the API must "
        "say so rather than let a green release gate imply otherwise."
    )
    assert body["release_gate_passed"] is True, (
        "The release gate and the certification blockers answer different "
        "questions; the gate passing while claims are unestablished is the "
        "expected state and is exactly why both fields are sent."
    )


def test_provenance_is_served_split_by_kind(client: TestClient):
    """One combined coverage figure is how the overstatement happened.

    The API used to send `verified`, `derived` and `unverified` over every
    constant at once, counting no sections - and a summary built on it claimed
    all of them carried document, section and version. The split shape makes
    that reading unavailable rather than merely discouraged.
    """
    body = client.get("/api/statistics/dossier").json()
    provenance = body["provenance"]

    # Exactly one field counts sections, over the normative set only.
    pinned_fields = [k for k in provenance if "pinned" in k]
    assert pinned_fields == ["normative_pinned"]

    assert (
        provenance["normative"]
        + provenance["derived"]
        + provenance["illustrative"]
        == provenance["total"]
    )
    assert (
        provenance["normative_pinned"] + provenance["normative_exceptions"]
        == provenance["normative"]
    )
    assert provenance["normative_pinned"] < provenance["total"], (
        "A pinned count reaching the total would let a client restate the "
        "claim over the wrong denominator."
    )


def test_the_unsupported_route_is_served_rather_than_omitted(client: TestClient):
    routes = client.get("/api/statistics/routing").json()
    ids = {r["route_id"] for r in routes}
    assert "UNSUPPORTED" in ids
    unsupported = next(r for r in routes if r["route_id"] == "UNSUPPORTED")
    assert unsupported["method"] is None
    assert unsupported["raises"] == "NotApplicable"


def test_every_refusal_served_says_what_would_lift_it(client: TestClient):
    for row in client.get("/api/statistics/refusals").json():
        assert row["summary"].strip()
        assert row["lifted_by"].strip()


def test_explaining_a_not_implemented_capability_answers_rather_than_404s(
    client: TestClient,
):
    """A 404 says "never heard of it", which is the wrong thing to tell
    somebody whose study just came back undecided."""
    response = client.get(
        "/api/statistics/capabilities/FDA_REPLICATE_STANDARD_ABE_PARTIAL/explain"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decided"] is False
    assert body["passes"] is None, (
        "An unimplemented capability must not report a verdict of any kind, "
        "and specifically must not report false."
    )
    assert body["refusal_code"] == "APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED"
    assert body["refusal_lifted_by"]
    assert body["submission_ready"] is False
    assert "APPENDIX-C-PARTIAL-ORACLE" in body["blockers"]


def test_an_unknown_capability_is_a_404(client: TestClient):
    response = client.get("/api/statistics/capabilities/NOPE/explain")
    assert response.status_code == 404


def test_every_capability_can_be_explained(client: TestClient):
    for capability_id in CAPABILITY_MATRIX:
        response = client.get(
            f"/api/statistics/capabilities/{capability_id}/explain"
        )
        assert response.status_code == 200, capability_id
        body = response.json()
        assert body["rendered"], capability_id
        if not body["decided"]:
            assert body["passes"] is None, capability_id


def test_the_validation_report_requires_authentication(anonymous_client: TestClient):
    for suffix in ("", "?format=json", "?format=markdown", "?format=html"):
        response = anonymous_client.get(f"/api/statistics/validation-report{suffix}")
        assert response.status_code == 401, suffix


def test_the_validation_report_serves_three_formats(client: TestClient):
    json_response = client.get("/api/statistics/validation-report?format=json")
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")

    markdown = client.get("/api/statistics/validation-report?format=markdown")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")

    page = client.get("/api/statistics/validation-report?format=html")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")


def test_the_report_defaults_to_json(client: TestClient):
    default = client.get("/api/statistics/validation-report")
    explicit = client.get("/api/statistics/validation-report?format=json")
    assert default.status_code == 200
    assert default.json()["schema"] == explicit.json()["schema"]


def test_an_unknown_format_is_refused(client: TestClient):
    response = client.get("/api/statistics/validation-report?format=pdf")
    assert response.status_code == 400


def test_the_report_schema_is_stable_and_complete(client: TestClient):
    body = client.get("/api/statistics/validation-report").json()
    assert body["schema"] == "be-stats.validation-report/1"
    for section in (
        "identity",
        "reading_notes",
        "capabilities",
        "evidence_by_tier",
        "provenance",
        "limitations",
        "governance",
    ):
        assert section in body, section
    assert body["capabilities"], "the report served no capabilities"


def test_the_served_report_is_the_reviewer_audience(client: TestClient):
    """The audience is fixed server-side and cannot be chosen by a caller.

    The internal audience carries candidate values for the unresolved
    partial-replicate question. A query parameter selecting the audience would
    let a client ask for them, which is why there is not one.
    """
    body = client.get("/api/statistics/validation-report").json()
    assert body["identity"]["audience"] == "reviewer"

    for blocker in body["limitations"]["open_blockers"]:
        assert "candidate_evidence" not in blocker


#: An ISO-8601 timestamp, which ends in `seconds.microseconds`.
#:
#: Removed before scanning for stray numbers. A real clock produces
#: `...:21.194755` for four seconds in every minute, and that is a decimal
#: inside the candidate range - so the first version of this test failed on
#: the generation timestamp and reported it as a leaked degrees-of-freedom
#: value. The report is built server-side, so the clock cannot be injected
#: here; stripping it is the honest alternative.
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?"
)


@pytest.mark.parametrize("fmt", ["json", "markdown", "html"])
def test_no_candidate_df_is_served_in_any_format(client: TestClient, fmt):
    response = client.get(f"/api/statistics/validation-report?format={fmt}")
    body = _TIMESTAMP.sub("<timestamp>", response.text)
    leaked = sorted(
        {n for n in re.findall(r"\d+\.\d+", body) if 19.0 <= float(n) <= 23.0}
    )
    assert not leaked, f"{fmt} leaked candidate values {leaked}"


def test_the_timestamp_stripper_actually_matches_the_served_timestamp(
    client: TestClient,
):
    """Otherwise the scan above could be neutered by a format change.

    A stripper that stopped matching would leave the timestamp in place and
    reintroduce the flake; one that matched too much would hide a real leak.
    """
    body = client.get("/api/statistics/validation-report").json()
    generated = body["identity"]["generated_at"]
    assert _TIMESTAMP.fullmatch(generated), generated


def test_the_report_cannot_be_steered_by_the_client(client: TestClient):
    """No client-supplied status, evidence or capability reaches the report.

    Every parameter a caller can set is tried; the served statuses must be
    identical to the unparameterised call. A report a caller can shape is a
    report a caller can quote back at us.
    """
    baseline = client.get("/api/statistics/validation-report").json()
    baseline_statuses = {
        c["capability_id"]: c["validation_status"] for c in baseline["capabilities"]
    }

    for query in (
        "?validation_status=validated",
        "?audience=internal",
        "?capability_ids=AVERAGE_BE_2X2",
        "?partial_oracle_ready=true",
        "?format=json&audience=internal",
    ):
        body = client.get(f"/api/statistics/validation-report{query}").json()
        assert body["identity"]["audience"] == "reviewer", query
        assert {
            c["capability_id"]: c["validation_status"] for c in body["capabilities"]
        } == baseline_statuses, query


def test_the_served_report_leaks_no_secrets(client: TestClient):
    payload = client.get("/api/statistics/validation-report").text.lower()
    for marker in (
        "sk-",
        "bearer ",
        "postgres://",
        "postgresql://",
        "service_role",
        "supabase_service",
        "api_key",
        "password",
        "secret",
        "signed_url",
    ):
        assert marker not in payload, marker


def test_the_served_report_contains_no_tenant_or_study_data(client: TestClient):
    """The report describes the engine, not anybody's studies.

    That is a structural property - it is built from code - and it is worth
    asserting once, because the day somebody joins study data onto it is the
    day this endpoint becomes a tenancy problem.
    """
    body = client.get("/api/statistics/validation-report").json()
    assert "single-organisation" in body["governance"]["tenancy"]
    payload = json.dumps(body).lower()
    for marker in ("subject_id", "tenant_id", "project_id", "run_id", "user_id"):
        assert marker not in payload, marker


def test_the_report_reports_the_governance_state_unchanged(client: TestClient):
    governance = client.get("/api/statistics/validation-report").json()["governance"]
    assert governance["partial_oracle_ready"] is False
    assert governance["real_sas_oracle_status"] == "PENDING"


def test_the_surface_is_read_only():
    """No verb in this module could take part in a promotion.

    Checked on the ROUTES the app actually registered rather than by reading
    the source for the word "post" - a source search would match a docstring
    and pass whether or not a writing route existed.
    """
    from app.main import create_app

    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/statistics"):
            continue
        methods = getattr(route, "methods", set())
        assert methods <= {"GET", "HEAD", "OPTIONS"}, (
            f"{path} accepts {methods}. Changing a validation status is a "
            "governed statistical change, and this surface must have no way "
            "to take part in one."
        )
