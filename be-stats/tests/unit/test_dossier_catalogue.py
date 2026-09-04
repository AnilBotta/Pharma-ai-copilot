"""The user-facing catalogue must distinguish three states and leak nothing.

Two failures matter here and they pull in opposite directions. Showing
everything as "Available" misleads a customer into filing on an unvalidated
method. Showing a candidate oracle value turns a live statistical question into
something a reader will treat as a specification.
"""

from __future__ import annotations

import re

from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.catalogue import (
    CATALOGUE_IDS,
    DisplayStatus,
    catalogue_entry,
    display_status,
    method_catalogue,
)
from be_stats.provenance import ValidationStatus


def test_there_are_exactly_three_display_states():
    """Three, because that is the distinction a user has to make.

    A fourth state would be a distinction only a statistician can act on, and
    would push the three that matter down the page.
    """
    assert set(DisplayStatus) == {
        DisplayStatus.VALIDATED,
        DisplayStatus.IMPLEMENTED_VALIDATION_PENDING,
        DisplayStatus.NOT_IMPLEMENTED,
    }


def test_every_validation_status_has_a_display_status():
    for status in ValidationStatus:
        assert isinstance(display_status(status), DisplayStatus)


def test_only_validated_displays_as_validated():
    """The whole point. Nothing below the bar may wear the word."""
    for status in ValidationStatus:
        shown = display_status(status)
        assert (shown is DisplayStatus.VALIDATED) is (
            status is ValidationStatus.VALIDATED
        ), f"{status} displays as {shown}"


def test_not_implemented_never_displays_as_available():
    assert (
        display_status(ValidationStatus.NOT_IMPLEMENTED)
        is DisplayStatus.NOT_IMPLEMENTED
    )


def test_the_catalogue_shows_more_than_one_state():
    """Guards the failure of showing everything as one thing.

    If the catalogue ever collapses to a single status, this fails - which is
    what "do not show all three as simply Available" means operationally.
    """
    shown = {entry.status for entry in method_catalogue()}
    assert len(shown) >= 2
    assert DisplayStatus.NOT_IMPLEMENTED in shown


def test_every_entry_carries_a_qualification():
    for entry in method_catalogue():
        assert entry.qualification.strip(), entry.capability_id
        assert entry.regulatory_source.strip(), entry.capability_id


def test_implemented_but_unvalidated_entries_say_so_concisely():
    for entry in method_catalogue():
        if entry.status is not DisplayStatus.IMPLEMENTED_VALIDATION_PENDING:
            continue
        assert entry.qualification.lower().startswith("implemented"), (
            f"{entry.capability_id}: the qualification must lead with the "
            f"state, not bury it. Got {entry.qualification!r}"
        )
        assert len(entry.qualification) < 260, (
            f"{entry.capability_id}: a qualification nobody finishes reading "
            "is a qualification nobody read."
        )


def test_partial_appendix_c_says_exactly_what_the_brief_requires():
    entry = catalogue_entry("FDA_REPLICATE_STANDARD_ABE_PARTIAL")
    assert entry.status is DisplayStatus.NOT_IMPLEMENTED
    assert entry.qualification == (
        "Not implemented - external SAS oracle evidence pending."
    )


def test_the_catalogue_leaks_no_candidate_oracle_values():
    """No number from the open partial-replicate question reaches a user.

    Checked as a numeric scan over the rendered text rather than a search for
    one literal, so a candidate expressed to different precision - 19.9, 22.54 -
    is caught too. The blocker record keeps those values, with what each does
    and does not establish; a product page is not the place for them.
    """
    text = " ".join(
        " ".join(
            [
                entry.method,
                entry.qualification,
                entry.key_limitation,
                entry.design,
                entry.regulatory_source,
            ]
        )
        for entry in method_catalogue()
    )
    numbers = [float(n) for n in re.findall(r"\d+\.\d+", text)]
    for value in numbers:
        assert not (19.0 <= value <= 23.0), (
            f"{value} appears in the user-facing catalogue and lies in the "
            "range of the candidate partial-replicate denominator df. "
            "Candidate values must not be displayed as product information."
        )


def test_the_catalogue_is_short_enough_to_read():
    """Seven rows. The internal capabilities are the reviewer's document."""
    assert len(CATALOGUE_IDS) <= 8
    assert len(method_catalogue()) == len(CATALOGUE_IDS)


def test_every_catalogue_id_is_a_real_capability():
    for capability_id in CATALOGUE_IDS:
        assert capability_id in CAPABILITY_MATRIX


def test_the_catalogue_covers_every_decision_making_method():
    """A user must be able to find every method that decides a study."""
    from be_stats.spec import Method

    shown = {CAPABILITY_MATRIX[cid].source_key for cid in CATALOGUE_IDS}
    missing = set(Method) - shown
    assert not missing, f"Methods absent from the user catalogue: {missing}"


def test_catalogue_statuses_agree_with_the_matrix():
    """The catalogue is a view, and a view that disagrees is a second copy."""
    for entry in method_catalogue():
        record = CAPABILITY_MATRIX[entry.capability_id]
        assert entry.status is display_status(record.validation_status)
