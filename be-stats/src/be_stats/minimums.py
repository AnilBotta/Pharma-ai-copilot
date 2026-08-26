"""Regulatory minimum subject counts, attached to a design and a framework.

THE RULE BELONGS TO THE DESIGN, NOT TO THE JURISDICTION

ICH M13A gives twelve evaluable subjects for a **crossover**, and twelve per
treatment group for a **parallel** design. Those are different totals - twelve
and twenty-four - so a single `EMA_MIN_N = 12` would be wrong for half the
studies it applied to.

AND IT BELONGS TO A FRAMEWORK, NOT ONLY TO A REGION

That is the second half of the same lesson, and it took a correction to learn.
FDA has adopted ICH M13A, so it is true that "twelve per treatment group"
applies under FDA - but only *within M13A's scope*, which is bioequivalence for
immediate-release solid oral dosage forms. FDA's own general statement is
different and broader: not fewer than twelve evaluable subjects in a PK BE
study, whatever the design.

Writing `FDA_PARALLEL_MIN_PER_GROUP = 12` would collapse those two into one
claim and apply an IR-solid-oral rule to, say, an inhalation or topical study
the document never addressed. So the key is
(jurisdiction, framework, design family), and an absent entry returns None
rather than a fallback.

WHICH FRAMEWORK APPLIES IS THE CALLER'S TO STATE

This package does not know the dosage form, so it cannot decide whether M13A
governs. `framework=None` therefore means "not stated", and resolves against
the region's own general guidance only - never against M13A. The consequence is
deliberate and worth naming: an unstated FDA parallel study returns the general
floor of twelve, not M13A's twenty-four. A caller running an IR solid oral
study must say `Framework.ICH_M13A` to get the rule that actually governs it.
Under-applying a floor the caller never claimed is recoverable; silently
applying a document's rule outside its scope is the failure this module exists
to prevent.

ABSENT IS A REAL ANSWER

`None` means "this package has not confirmed a figure", and callers must render
that differently from a number. It is not zero, and it is not twelve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.provenance import (
    Citation,
    FDA_M13A_QA,
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


class Framework(StrEnum):
    """Which body of guidance the caller is working under.

    Not a synonym for jurisdiction. A single regulator applies several, and
    which one governs depends on the product - most sharply on the dosage form,
    which this package is never told.
    """

    #: The region's own general bioequivalence guidance, applying to PK BE
    #: studies at large.
    GENERAL = "general"
    #: ICH M13A - bioequivalence for immediate-release solid oral dosage forms.
    #: Adopted by both regions, and scoped to that dosage form in both.
    ICH_M13A = "ich_m13a"


@dataclass(frozen=True, slots=True)
class RegulatoryMinimum:
    """A floor on evaluable subjects, and the document that sets it."""

    jurisdiction: str
    design_family: DesignFamily
    citation: Citation
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    framework: Framework = Framework.GENERAL

    #: Exactly one of these is set. `evaluable_per_group` is doubled to reach a
    #: total for the two-group designs this package supports.
    evaluable_total: int | None = None
    evaluable_per_group: int | None = None

    #: What is being counted. "Evaluable" excludes dropouts, which is why a
    #: study is normally over-recruited against this figure.
    counts: str = "evaluable subjects"

    #: The products this row reaches. Printed alongside the figure so a reader
    #: can see at once whether it should have applied to their study.
    scope: str = ""

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
        line = (
            f"{self.jurisdiction}: {what} for a {self.design_family} design "
            f"— {self.citation}"
        )
        return f"{line} (applies to {self.scope})" if self.scope else line


_M13A_SCOPE = "immediate-release solid oral dosage forms"

# ICH M13A is adopted by both regions, so the crossover and parallel floors
# share a rule. They are registered per jurisdiction anyway, because a future
# divergence should be a new row rather than a rewrite - and because FDA
# publishes its own Q&A of the same document, which is what is cited for FDA.
_M13A_CROSSOVER = dict(
    design_family=DesignFamily.CROSSOVER,
    framework=Framework.ICH_M13A,
    evaluable_total=12,
    verification=VerificationStatus.VERIFIED,
    scope=_M13A_SCOPE,
)
_M13A_PARALLEL = dict(
    design_family=DesignFamily.PARALLEL,
    framework=Framework.ICH_M13A,
    evaluable_per_group=12,
    verification=VerificationStatus.VERIFIED,
    scope=_M13A_SCOPE,
)

_REGISTRY: dict[tuple[str, Framework, DesignFamily], RegulatoryMinimum] = {
    # ---------------------------------------------------------- ICH M13A ---
    ("EMA", Framework.ICH_M13A, DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="EMA", citation=ICH_M13A_QA, **_M13A_CROSSOVER
    ),
    ("EMA", Framework.ICH_M13A, DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="EMA", citation=ICH_M13A_QA, **_M13A_PARALLEL
    ),
    # FDA has adopted M13A, so the same two rows exist for FDA - cited to FDA's
    # own publication of the Q&A, and reachable ONLY when the caller states
    # this framework. That scoping is the whole point: these figures must not
    # be readable as "FDA requires 24 for any parallel study".
    ("FDA", Framework.ICH_M13A, DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="FDA", citation=FDA_M13A_QA, **_M13A_CROSSOVER
    ),
    ("FDA", Framework.ICH_M13A, DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="FDA", citation=FDA_M13A_QA, **_M13A_PARALLEL
    ),
    # ----------------------------------------- FDA general PK BE guidance ---
    # "Not fewer than 12 evaluable subjects in a PK BE study" is a floor on the
    # STUDY, not on a treatment group, and it is not restricted by dosage form.
    # So it is 12 total for both designs. Where a study is also within M13A's
    # scope the parallel figure is higher, and a caller who says so gets it.
    ("FDA", Framework.GENERAL, DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="FDA",
        design_family=DesignFamily.CROSSOVER,
        framework=Framework.GENERAL,
        citation=FDA_STATISTICAL_APPROACHES,
        evaluable_total=12,
        verification=VerificationStatus.VERIFIED,
        scope="PK bioequivalence studies generally",
    ),
    ("FDA", Framework.GENERAL, DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="FDA",
        design_family=DesignFamily.PARALLEL,
        framework=Framework.GENERAL,
        citation=FDA_STATISTICAL_APPROACHES,
        evaluable_total=12,
        verification=VerificationStatus.VERIFIED,
        scope="PK bioequivalence studies generally",
    ),
    # EMA + GENERAL is deliberately ABSENT. What review supplied for EMA was
    # the M13A Q&A; no separate EMA general floor was cited, and inventing one
    # by copying the FDA row is the leak this module is shaped to prevent.
}

#: Highly variable products carry their own floor, which is why the lookup
#: takes a drug class at all. Keyed separately so it cannot be reached by a
#: study that merely happens to be replicate.
_HVD_MINIMUM = RegulatoryMinimum(
    jurisdiction="FDA",
    design_family=DesignFamily.REPLICATE,
    framework=Framework.GENERAL,
    citation=FDA_STATISTICAL_APPROACHES,
    evaluable_total=24,
    verification=VerificationStatus.VERIFIED,
    scope="highly variable drug products",
)


def lookup(
    jurisdiction: str,
    design_family: DesignFamily,
    *,
    framework: Framework | None = None,
    is_highly_variable: bool = False,
) -> RegulatoryMinimum | None:
    """The floor for this combination, or None when none is confirmed.

    `framework=None` means the caller has not stated which body of guidance
    governs, and resolves against `Framework.GENERAL` only. M13A's rules are
    never reached by default, because reaching them requires knowing the dosage
    form and this package is never told it.
    """
    if is_highly_variable and jurisdiction == "FDA":
        return _HVD_MINIMUM
    return _REGISTRY.get(
        (jurisdiction, framework or Framework.GENERAL, design_family)
    )


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
