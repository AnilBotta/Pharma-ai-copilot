"""The user-facing method catalogue: what a pharma user may rely on.

WHY THIS IS NOT JUST THE MATRIX WITH DIFFERENT FIELD NAMES

Two audiences, two documents. `capabilities.py` is written for a reviewer who
needs the whole argument - every limitation, every refusal code, the reasoning
behind a status. This is written for someone deciding whether to run their
study through the engine tomorrow, and for them the whole argument is noise
they will not read, which means the one sentence that matters gets buried.

So the catalogue shows three states and one qualification each. The three
states are the only distinction a user has to make:

    VALIDATED                        rely on it
    IMPLEMENTED - VALIDATION PENDING it will give you a number, and no
                                     regulator's published output has been
                                     reproduced through it
    NOT IMPLEMENTED                  it will refuse, and here is why

THE ONE THING THIS MUST NEVER DO

Show all three as "Available". That is not a simplification, it is a different
claim, and a customer who reads it and files on an unvalidated method has been
misled by us rather than by their own optimism.

WHAT IT MUST NOT LEAK

Candidate oracle values. The partial-replicate blocker carries a best-supported
candidate denominator df; it is a live statistical question, and a number
displayed in a product catalogue stops being a candidate and starts being a
specification. `test_the_catalogue_leaks_no_candidate_values` enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.dossier.blockers import blockers_for
from be_stats.dossier.capabilities import CAPABILITY_MATRIX, CapabilityRecord
from be_stats.dossier.evidence import best_tier_for
from be_stats.dossier.statuses import EvidenceTier
from be_stats.provenance import ValidationStatus
from be_stats.spec import Endpoint, Jurisdiction


class DisplayStatus(StrEnum):
    """The three states a user has to tell apart. Exactly three."""

    VALIDATED = "VALIDATED"
    IMPLEMENTED_VALIDATION_PENDING = "IMPLEMENTED - VALIDATION PENDING"
    NOT_IMPLEMENTED = "NOT IMPLEMENTED"


_DISPLAY: dict[ValidationStatus, DisplayStatus] = {
    ValidationStatus.NOT_IMPLEMENTED: DisplayStatus.NOT_IMPLEMENTED,
    ValidationStatus.EXPERIMENTAL: DisplayStatus.IMPLEMENTED_VALIDATION_PENDING,
    ValidationStatus.IMPLEMENTED: DisplayStatus.IMPLEMENTED_VALIDATION_PENDING,
    ValidationStatus.IMPLEMENTED_UNVALIDATED: (
        DisplayStatus.IMPLEMENTED_VALIDATION_PENDING
    ),
    ValidationStatus.VALIDATED: DisplayStatus.VALIDATED,
}


def display_status(validation: ValidationStatus) -> DisplayStatus:
    """Three buckets, from five statuses.

    `IMPLEMENTED` - the structural status, for a capability that produces no
    number a regulator could disagree with - lands in the middle bucket even
    though nothing is literally pending for it. That is deliberate: the
    alternative is a fourth state whose distinction only a statistician can
    use, and erring towards more caution is the right direction when the cost
    of the other error is a filing. The qualification line says which kind it
    is.
    """
    return _DISPLAY[validation]


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    """One row a pharma user reads."""

    capability_id: str
    jurisdiction: str
    method: str
    design: str
    supported_endpoints: str
    status: DisplayStatus
    #: One sentence. Why the status is what it is, in the user's terms.
    qualification: str
    #: The single most important thing this does not cover.
    key_limitation: str
    #: Document and section, so a user can look it up.
    regulatory_source: str


def _design_phrase(record: CapabilityRecord) -> str:
    names = {
        "crossover": "2x2 crossover",
        "parallel": "parallel group",
        "replicate": "fully replicate crossover",
        "partial_replicate": "partial replicate crossover",
    }
    parts = [names.get(str(d), str(d)) for d in record.design_requirement]
    return ", ".join(parts) if parts else "any"


def _endpoint_phrase(record: CapabilityRecord) -> str:
    if set(record.endpoints) == {Endpoint.AUC, Endpoint.CMAX, Endpoint.OTHER}:
        return "all endpoints"
    return ", ".join(str(e) for e in record.endpoints)


def _qualification(record: CapabilityRecord) -> str:
    """The sentence that carries the status. Written once, per situation."""
    status = record.validation_status

    if status is ValidationStatus.NOT_IMPLEMENTED:
        blockers = blockers_for(record.capability_id)
        if any(b.blocker_id == "APPENDIX-C-PARTIAL-ORACLE" for b in blockers):
            return "Not implemented - external SAS oracle evidence pending."
        return "Not implemented. Studies routed here receive no verdict."

    if status is ValidationStatus.VALIDATED:
        return (
            "Reproduces the regulator's own published numerical output for "
            "this procedure."
        )

    if status is ValidationStatus.IMPLEMENTED:
        return (
            "Implemented and structural: it enforces the regulator's stated "
            "definitions and produces no number for a regulator to disagree "
            "with, so there is no numerical validation to perform."
        )

    tier = best_tier_for(record.capability_id)
    if tier is EvidenceTier.TIER_1B:
        return (
            "Implemented, and validation is pending: a regulator's published "
            "output has been reproduced for the model, and not by the "
            "regulator whose procedure this is."
        )
    if tier is EvidenceTier.TIER_1A:
        return (
            "Implemented, and validation is pending: the regulator's stated "
            "algorithm is conformed to, and no regulator-published worked "
            "example of it exists to reproduce."
        )
    return (
        "Implemented, and validation is pending: no regulator-published "
        "numerical output has been reproduced through this path."
    )


def _key_limitation(record: CapabilityRecord) -> str:
    """The first limitation, which is written first for that reason."""
    return record.known_limitations[0] if record.known_limitations else ""


def _source_phrase(record: CapabilityRecord) -> str:
    citation = record.regulatory_source
    parts = [citation.authority, citation.document]
    if citation.section:
        parts.append(citation.section)
    return ", ".join(parts)


def catalogue_entry(capability_id: str) -> CatalogueEntry:
    record = CAPABILITY_MATRIX[capability_id]
    return CatalogueEntry(
        capability_id=record.capability_id,
        jurisdiction=(
            str(record.jurisdiction) if record.jurisdiction else "FDA / EMA"
        ),
        method=record.title,
        design=_design_phrase(record),
        supported_endpoints=_endpoint_phrase(record),
        status=display_status(record.validation_status),
        qualification=_qualification(record),
        key_limitation=_key_limitation(record),
        regulatory_source=_source_phrase(record),
    )


#: Capability ids the catalogue shows.
#:
#: The METHODS, plus the two Appendix C rows. A user chooses a method; the
#: internal capabilities that serve it are the reviewer's concern and would
#: turn a five-row page into a twenty-three-row one without answering any
#: question a user has.
#:
#: Appendix C is the exception and has to be: FDA_REPLICATE_STANDARD_ABE_PARTIAL
#: is the reason a highly variable study on a 2x3x3 design can come back
#: undecided, and a user who cannot see that row cannot find out why.
CATALOGUE_IDS: tuple[str, ...] = (
    "AVERAGE_BE_2X2",
    "FDA_HVD_RSABE",
    "FDA_NTI_RSABE",
    "EMA_HVD_ABEL",
    "EMA_NTI_NARROW_ABE",
    "FDA_REPLICATE_STANDARD_ABE_FULL",
    "FDA_REPLICATE_STANDARD_ABE_PARTIAL",
)


def method_catalogue() -> list[CatalogueEntry]:
    """The user-facing catalogue, in reading order."""
    return [catalogue_entry(cid) for cid in CATALOGUE_IDS]


def catalogue_for(jurisdiction: Jurisdiction) -> list[CatalogueEntry]:
    return [
        entry
        for entry in method_catalogue()
        if str(jurisdiction) in entry.jurisdiction
    ]
