"""The recipient roster and the daily digest.

The digest exists because of arithmetic. The last sweep raised 44 alerts; five
recipients receiving all of them immediately is 220 emails, and 0021's own
header says what happens next - people stop reading, and the system that reports
everything achieves what one reporting nothing achieves.

So: immediate mail to the person who must act, one summary a day to everyone
else. These tests pin the parts of that where being wrong is silent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.notifications import compose_digest


def _row(**overrides) -> dict:
    return {
        "project_name": "Peptide Depot",
        "project_id": "p1",
        "condition": "requirement_overdue",
        "severity": "warning",
        "title": "G1-FD-001 is overdue",
        "escalation_level": 0,
        "raised_at": datetime.now(UTC) - timedelta(days=3),
        "gate_name": "Gate 1: Feasibility",
        **overrides,
    }


class TestTheDigestIsReadable:
    """One message that a person reads beats forty-four they filter."""

    def test_an_empty_day_says_so_rather_than_sending_a_blank(self) -> None:
        subject, body = compose_digest([])
        assert "nothing outstanding" in subject
        assert "No gate has an open alert" in body

    def test_it_counts_what_it_is_about(self) -> None:
        subject, _ = compose_digest([_row(), _row(title="G1-FD-002 is overdue")])
        assert "2 open alert" in subject
        assert "1 programme" in subject

    def test_alerts_are_grouped_by_programme_and_gate(self) -> None:
        _, body = compose_digest(
            [
                _row(),
                _row(gate_name="Gate 2: Candidate selection", title="G2-AN-001 is overdue"),
                _row(project_name="Other Programme", project_id="p2"),
            ]
        )
        assert "## Peptide Depot" in body
        assert "## Other Programme" in body
        assert "Gate 1: Feasibility" in body
        assert "Gate 2: Candidate selection" in body

    def test_critical_and_escalated_are_called_out_separately(self) -> None:
        """Open and escalated are different facts.

        Escalated means nobody acknowledged it in time, which is a statement
        about the organisation rather than about the requirement.
        """
        _, body = compose_digest(
            [_row(severity="critical"), _row(escalation_level=1)]
        )
        assert "1 are critical" in body
        assert "escalated because nobody acknowledged" in body

    def test_a_long_list_is_truncated_but_the_count_stays_honest(self) -> None:
        """A programme with sixty alerts must not produce an unreadable email.

        The per-gate list is capped; the totals are not, so the summary line
        still tells the truth about how much is outstanding.
        """
        rows = [_row(title=f"G1-FD-{i:03d} is overdue") for i in range(20)]
        subject, body = compose_digest(rows)
        assert "20 open alert" in subject
        assert "and 12 more" in body
        assert body.count("is overdue") == 8

    def test_it_says_how_long_each_has_been_open(self) -> None:
        """A date is not a prompt to act. "9 days open" is."""
        _, body = compose_digest(
            [_row(raised_at=datetime.now(UTC) - timedelta(days=9))]
        )
        assert "9 days open" in body

    def test_a_programme_link_is_included_when_there_is_a_base_url(self) -> None:
        _, body = compose_digest([_row()], base_url="https://app.test")
        assert "https://app.test/programmes/p1" in body

    def test_and_omitted_when_there_is_not(self) -> None:
        """A relative path is not clickable and a guessed origin misleads."""
        _, body = compose_digest([_row()])
        assert "programmes/p1" not in body

    def test_an_alert_not_tied_to_a_gate_still_appears(self) -> None:
        _, body = compose_digest([_row(gate_name=None)])
        assert "Not tied to a gate" in body


class TestResponseModelsAcceptTheirOwnRows:
    """A response model that rejects a real row is a 500 nobody sees coming.

    `serialise` converts UUID and Decimal and deliberately leaves datetimes
    alone, because every response model in this codebase declares them as
    datetimes. Two of mine declared `str`, so the models rejected the very rows
    they exist to describe.

    The failure was invisible for as long as the tables were empty - a
    validation error cannot happen when there is nothing to validate - and
    surfaced the first time somebody added a recipient. `GET /api/documents`
    carried the identical defect and would have returned 500 the moment a
    document existed.

    These build each response from a row shaped like the query's output, which
    is the check that was missing.
    """

    def test_a_recipient_row_builds_its_response(self) -> None:
        from app.settings_module.routes import _to_response

        row = {
            "id": uuid.uuid4(),
            "email": "ceo@example.test",
            "name": "The CEO",
            "is_active": True,
            "conditions": ["task_overdue"],
            "wants_immediate": True,
            "wants_digest": True,
            "sent_count": 3,
            "last_sent_at": datetime.now(UTC),
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        assert _to_response(row).email == "ceo@example.test"

    def test_a_freshly_inserted_recipient_builds_too(self) -> None:
        """`create` returns the bare row: no sent_count, no last_sent_at.

        Those come from the listing query's subselects, so the insert path has
        to tolerate their absence - and it is the path the POST takes.
        """
        from app.settings_module.routes import _to_response

        row = {
            "id": uuid.uuid4(),
            "email": "new@example.test",
            "name": None,
            "is_active": True,
            "conditions": [],
            "wants_immediate": True,
            "wants_digest": True,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        response = _to_response(row)
        assert response.sent_count == 0
        assert response.last_sent_at is None

    def test_a_document_row_builds_its_response(self) -> None:
        from app.documents.routes import _to_response as document_response

        row = {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "filename": "Stability Report.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1913,
            "status": "ready",
            "error": None,
            "page_count": 4,
            "extracted_chars": 5000,
            "chunk_count": 6,
            "pending_chunk_count": 0,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        assert document_response(row).filename == "Stability Report.pdf"


class TestConditionValidation:
    """A typo must not produce a recipient who is configured and silent."""

    def test_an_unknown_alert_type_is_refused_by_name(self) -> None:
        from app.settings_module.schemas import CreateRecipientRequest

        with pytest.raises(ValueError) as exc:
            CreateRecipientRequest(email="a@b.test", conditions=["requirement_overdu"])
        assert "requirement_overdu" in str(exc.value)

    def test_the_new_gate_condition_is_accepted(self) -> None:
        from app.settings_module.schemas import CreateRecipientRequest

        payload = CreateRecipientRequest(
            email="a@b.test", conditions=["gate_unattended"]
        )
        assert payload.conditions == ["gate_unattended"]

    def test_empty_means_everything_and_is_left_empty(self) -> None:
        """Not expanded to the full list.

        Storing the expansion would freeze the set: a condition added later
        would silently not reach anybody configured before it existed.
        """
        from app.settings_module.schemas import CreateRecipientRequest

        assert CreateRecipientRequest(email="a@b.test").conditions == []

    def test_duplicates_are_collapsed_and_ordered(self) -> None:
        from app.settings_module.schemas import CreateRecipientRequest

        payload = CreateRecipientRequest(
            email="a@b.test",
            conditions=["task_overdue", "gate_unattended", "task_overdue"],
        )
        assert payload.conditions == ["gate_unattended", "task_overdue"]

    def test_a_malformed_address_is_refused(self) -> None:
        from app.settings_module.schemas import CreateRecipientRequest

        with pytest.raises(ValueError):
            CreateRecipientRequest(email="not an email")
