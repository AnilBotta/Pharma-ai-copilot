"""Regulatory minimum subject counts, attached to a design.

THE RULE BELONGS TO THE DESIGN, NOT TO THE JURISDICTION

ICH M13A gives twelve evaluable subjects for a **crossover**, and twelve per
treatment group for a **parallel** design. Those are different totals - twelve
and twenty-four - so a single `EMA_MIN_N = 12` would be wrong for half the
studies it applied to.

Worse, a jurisdiction-keyed constant leaks. Replicate and partial-replicate
designs, highly variable products and product-specific requirements all sit
outside M13A's core scope, and a lookup keyed only on "EMA" would happily
return twelve for a design the document never addressed. So the key is
(jurisdiction, design family, drug class), and an absent entry returns None
rather than a fallback.

ABSENT IS A REAL ANSWER

`None` means "this package has not confirmed a figure", and callers must render
that differently from a number. It is not zero, and it is not twelve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.provenance import (
    Citation,
    FDA_STATISTICAL_APPROACHES,
    ICH_M13A_QA,
    VerificationStatus,
)


class DesignFamily(StrEnum):
    """Coarse enough to key a regulatory rule, fine enough not to over-reach."""

    CROSSOVER = "crossover"
    PARALLEL = "parallel"
    REPLICATE = "replicate"
    PARTIAL_REPLICATE = "partial_replicate"


@dataclass(frozen=True, slots=True)
class RegulatoryMinimum:
    """A floor on evaluable subjects, and the document that sets it."""

    jurisdiction: str
    design_family: DesignFamily
    citation: Citation
    verification: VerificationStatus = VerificationStatus.UNVERIFIED

    #: Exactly one of these is set. `evaluable_per_group` is doubled to reach a
    #: total for the two-group designs this package supports.
    evaluable_total: int | None = None
    evaluable_per_group: int | None = None

    #: What is being counted. "Evaluable" excludes dropouts, which is why a
    #: study is normally over-recruited against this figure.
    counts: str = "evaluable subjects"

    def required_total(self) -> int:
        if self.evaluable_total is not None:
            return self.evaluable_total
        if self.evaluable_per_group is not None:
            return 2 * self.evaluable_per_group
        raise ValueError(
            f"{self.jurisdiction}/{self.design_family} minimum defines neither "
            "a total nor a per-group figure."
        )

    def explain(self) -> str:
        if self.evaluable_per_group is not None:
            what = f"{self.evaluable_per_group} {self.counts} per treatment group"
        else:
            what = f"{self.evaluable_total} {self.counts}"
        return f"{self.jurisdiction}: {what} for a {self.design_family} design — {self.citation}"


# ICH M13A is adopted by both regions, so the crossover and parallel floors
# share a source. They are registered per jurisdiction anyway, because a future
# divergence should be a new row rather than a rewrite - and because FDA's own
# guidance states its figure independently.
_M13A_CROSSOVER = dict(
    design_family=DesignFamily.CROSSOVER,
    citation=ICH_M13A_QA,
    evaluable_total=12,
    verification=VerificationStatus.VERIFIED,
)
_M13A_PARALLEL = dict(
    design_family=DesignFamily.PARALLEL,
    citation=ICH_M13A_QA,
    evaluable_per_group=12,
    verification=VerificationStatus.VERIFIED,
)

_REGISTRY: dict[tuple[str, DesignFamily], RegulatoryMinimum] = {
    ("EMA", DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="EMA", **_M13A_CROSSOVER
    ),
    ("EMA", DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="EMA", **_M13A_PARALLEL
    ),
    ("FDA", DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="FDA",
        design_family=DesignFamily.CROSSOVER,
        citation=FDA_STATISTICAL_APPROACHES,
        evaluable_total=12,
        verification=VerificationStatus.VERIFIED,
    ),
    # FDA + parallel is deliberately ABSENT. The figure cited at review for FDA
    # was "not fewer than 12 evaluable subjects in a PK BE study"; whether the
    # M13A twelve-per-group rule governs an FDA parallel study was flagged as
    # unconfirmed. Registering it here on the strength of the EMA row is
    # exactly the leak this module is shaped to prevent.
}

#: Highly variable products carry their own floor, which is why the lookup
#: takes a drug class at all. Keyed separately so it cannot be reached by a
#: study that merely happens to be replicate.
_HVD_MINIMUM = RegulatoryMinimum(
    jurisdiction="FDA",
    design_family=DesignFamily.REPLICATE,
    citation=FDA_STATISTICAL_APPROACHES,
    evaluable_total=24,
    verification=VerificationStatus.VERIFIED,
)


def lookup(
    jurisdiction: str,
    design_family: DesignFamily,
    *,
    is_highly_variable: bool = False,
) -> RegulatoryMinimum | None:
    """The floor for this combination, or None when none is confirmed."""
    if is_highly_variable and jurisdiction == "FDA":
        return _HVD_MINIMUM
    return _REGISTRY.get((jurisdiction, design_family))


def design_family_for(design: str) -> DesignFamily:
    """Map the estimator's design string onto the family a rule is keyed by."""
    match design:
        case "2x2":
            return DesignFamily.CROSSOVER
        case "parallel":
            return DesignFamily.PARALLEL
        case _:
            raise ValueError(
                f"Unknown design {design!r}; cannot determine which regulatory "
                "minimum applies. Guessing would risk applying a crossover rule "
                "to a design the document never addressed."
            )
