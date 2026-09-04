"""Two axes that a single word keeps collapsing into one.

THE CONFLATION THIS MODULE EXISTS TO PREVENT

"Is FDA HVD RSABE supported?" has two answers and they are not the same
answer. The code runs, and no regulator's published numbers have ever been
reproduced through it. A product surface that offers one word for both -
"Available", "Supported", a green tick - is not being concise. It is
answering the safety question with the engineering one.

So there are two axes here:

    IMPLEMENTATION   does the code exist and run?
    VALIDATION       has it been shown to agree with the regulator, and on
                     what evidence?

`ValidationStatus` in `be_stats.provenance` is the validation axis and stays
exactly as it is - it is referenced across the package, in the SAS validation
workflow, and in committed evidence files. This module adds the implementation
axis beside it and, crucially, the *total function* between them.

WHY IMPLEMENTATION HAS ONLY TWO VALUES

The obvious third value would be `IMPLEMENTED_UNVALIDATED`. It is not here,
and its absence is the point: that name is a PAIR of answers - implemented on
this axis, unvalidated on the other - wearing one label. Admitting it as an
implementation value would rebuild the conflation inside the module written to
prevent it, and would make `implementation is IMPLEMENTED` stop being a
question anyone can answer without also reading the validation column.

`ValidationStatus.IMPLEMENTED_UNVALIDATED` keeps its name and meaning on the
validation axis, where the compound reads correctly: the code is there and its
numbers are unchecked.

THE MAPPING IS TOTAL AND ONE-DIRECTIONAL

Every validation status implies an implementation status; no implementation
status implies a validation status. That asymmetry is the whole design. A
`VALIDATED` thing is necessarily implemented; an `IMPLEMENTED` thing is not
necessarily anything on the validation axis, which is why `implemented` must
never be read as `validated`.
"""

from __future__ import annotations

from enum import StrEnum

from be_stats.provenance import ValidationStatus


class ImplementationStatus(StrEnum):
    """Does the code exist and run? Nothing about whether it is trustworthy."""

    #: No code path produces this. A caller asking for it gets a refusal.
    NOT_IMPLEMENTED = "not_implemented"
    #: Code exists and executes. Says NOTHING about whether its output has
    #: ever been checked against a regulator - read the validation axis for
    #: that, every time, without exception.
    IMPLEMENTED = "implemented"


class EvidenceTier(StrEnum):
    """What KIND of evidence backs a claim, ordered by the authority behind it.

    Tiers are about the source's standing, not about how much work went into
    producing it or how many cases it covers. Ten thousand simulation cases are
    tier 4; one regulator-published table is tier 1B; the second is the one
    that licenses a filing.
    """

    #: Conformance to a REGULATOR'S STATED ALGORITHM or decision rule. The
    #: rule is transcribed from the document and asserted against; no external
    #: numbers are involved.
    TIER_1A = "tier_1a"
    #: A REGULATOR'S OWN PUBLISHED NUMERICAL EXAMPLE or dataset, reproduced.
    #: This is the bar for VALIDATED and nothing below it substitutes.
    TIER_1B = "tier_1b"
    #: A published textbook or peer-reviewed reference dataset.
    TIER_2 = "tier_2"
    #: An INDEPENDENT IMPLEMENTATION agreeing - PowerTOST, ReplicateBE.jl.
    #: Strong engineering evidence and NOT regulatory authority. See
    #: validation/findings/README.md: the hierarchy is regulator, then
    #: be-stats, then the oracle, and a disagreement questions the comparison
    #: first.
    TIER_3 = "tier_3"
    #: Internal simulation, synthetic structural checks, algebraic identities
    #: this package derived itself. Evidence that the code does what this
    #: package believes; no evidence about what the regulator believes.
    TIER_4 = "tier_4"
    #: No evidence of any tier. Used where a capability is NOT_IMPLEMENTED, and
    #: never as a quiet stand-in for "we did not look".
    NONE = "none"


#: The total map from the validation axis to the implementation axis.
#:
#: Written out member by member rather than computed from a predicate, so that
#: adding a `ValidationStatus` member fails `test_every_validation_status_maps`
#: instead of silently defaulting to one side.
_IMPLIED_IMPLEMENTATION: dict[ValidationStatus, ImplementationStatus] = {
    ValidationStatus.NOT_IMPLEMENTED: ImplementationStatus.NOT_IMPLEMENTED,
    ValidationStatus.EXPERIMENTAL: ImplementationStatus.IMPLEMENTED,
    ValidationStatus.IMPLEMENTED: ImplementationStatus.IMPLEMENTED,
    ValidationStatus.IMPLEMENTED_UNVALIDATED: ImplementationStatus.IMPLEMENTED,
    ValidationStatus.VALIDATED: ImplementationStatus.IMPLEMENTED,
}


def implementation_status_of(
    validation: ValidationStatus,
) -> ImplementationStatus:
    """The implementation axis implied by a validation status.

    Note the direction. This function exists; its inverse deliberately does
    not, and cannot be written - `IMPLEMENTED` is consistent with four
    different validation statuses, which is precisely why the product may not
    show one word for both.
    """
    return _IMPLIED_IMPLEMENTATION[validation]


#: Validation statuses that license use in a regulatory submission.
#:
#: A frozenset of one. It is a set rather than an equality check so that the
#: question "may this be filed on" is asked in one place, and so that widening
#: it would be a visible edit to a named constant rather than a relaxed
#: comparison somewhere in a route handler.
SUBMISSION_READY: frozenset[ValidationStatus] = frozenset(
    {ValidationStatus.VALIDATED}
)


def is_submission_ready(validation: ValidationStatus) -> bool:
    """Whether a result from this may be relied on for a filing."""
    return validation in SUBMISSION_READY
