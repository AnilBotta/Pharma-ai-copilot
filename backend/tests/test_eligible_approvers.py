"""Who may approve a requirement, as the client is told it.

The three segregation rules are each enforced in the database and each correct.
Their combination is what caught us out during testing: on a two-person team,
the only holder of the approving role confirmed the acceptance criteria, which
barred them, and the other person did not hold the role. The requirement could
not be approved by anybody, and neither person was told why - both saw a button
that did nothing.

`private.eligible_approvers` supplies the missing fact and is verified against
the live database. What is pinned here is the small piece of Python between
that function and the page, because it has a failure mode that looks exactly
like a correct answer: given the raw jsonb string instead of a decoded list,
`_is_eligible` would report "no, you may not approve" for everybody, forever,
and nothing about the screen would look wrong.
"""

from __future__ import annotations

import json
import uuid

from app.pdp.repository import _is_eligible

ALICE = str(uuid.uuid4())
BRIJESH = str(uuid.uuid4())

ROSTER = [
    {"user_id": ALICE, "name": "Alice Novak"},
    {"user_id": BRIJESH, "name": "Brijesh Rao"},
]


class TestIsEligible:
    def test_a_named_person_may_approve(self) -> None:
        assert _is_eligible(ROSTER, ALICE) is True

    def test_somebody_not_named_may_not(self) -> None:
        assert _is_eligible(ROSTER, str(uuid.uuid4())) is False

    def test_an_empty_roster_means_nobody_at_all(self) -> None:
        """The deadlock case. Every reader must be told no, including the
        person who holds the role, because the trigger will refuse them."""
        assert _is_eligible([], ALICE) is False

    def test_an_anonymous_reader_is_never_eligible(self) -> None:
        assert _is_eligible(ROSTER, None) is False

    def test_raw_jsonb_is_parsed_rather_than_compared_as_text(self) -> None:
        """A connection without the jsonb codec hands back a string.

        Comparing a uuid against the characters of a JSON document silently
        yields False, which renders as a correctly-worded refusal. It has to be
        parsed, or the bug is invisible.
        """
        assert _is_eligible(json.dumps(ROSTER), ALICE) is True
        assert _is_eligible(json.dumps([]), ALICE) is False

    def test_uuid_objects_compare_equal_to_their_text(self) -> None:
        """asyncpg returns uuid.UUID for uuid columns and the roster carries
        strings, so the comparison has to survive crossing that boundary."""
        assert _is_eligible(ROSTER, uuid.UUID(ALICE)) is True
        assert _is_eligible(
            [{"user_id": uuid.UUID(ALICE), "name": "Alice Novak"}], ALICE
        ) is True

    def test_a_null_roster_is_treated_as_nobody(self) -> None:
        assert _is_eligible(None, ALICE) is False
