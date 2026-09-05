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

AND IT BELONGS TO A STUDY ROLE, WHICH IS THE THIRD KEY

M13A states its floor for PIVOTAL BE studies, in the guideline at 2.1.3 and
again in Q&A 2.1. The same Q&A answer names a pilot relative bioavailability
study as an INPUT to sizing the pivotal one, so the document plainly does not
hold a pilot to twelve. `lookup` therefore takes a `StudyRole`, and the
constraint lives PER ROW: FDA's Statistical Approaches II.A sets its own
twelve without qualifying the study's role, and gating that one behind
"pivotal" would remove a floor FDA states unconditionally. Two documents, two
scopes, one number - and only one of them is restricted.

ABSENT IS A REAL ANSWER, AND SO IS NOT-APPLICABLE

`lookup` returns a `MinimumOutcome`, not a nullable figure. "No floor applies
to a pilot", "you did not say what kind of study this is" and "this package
has confirmed no figure for this region" are three different answers, and a
`None` would merge them. None of them is zero, and none of them is twelve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from be_stats.provenance import (
    Citation,
    EMA_M13A_QA,
    FDA_M13A_QA,
    FDA_STATISTICAL_APPROACHES_II_A,
    VerificationStatus,
)


class DesignFamily(StrEnum):
    """Coarse enough to key a regulatory rule, fine enough not to over-reach."""

    CROSSOVER = "crossover"
    PARALLEL = "parallel"
    REPLICATE = "replicate"
    PARTIAL_REPLICATE = "partial_replicate"


class StudyRole(StrEnum):
    """What the study is FOR, which is a third thing a floor can depend on.

    M13A states its floor for PIVOTAL BE studies - guideline 2.1.3 and Q&A 2.1
    both say the word - and the same Q&A answer names a pilot relative
    bioavailability study as an INPUT to sizing the pivotal one. A pilot is
    therefore not held to twelve by that document.

    NEITHER M13A NOR ITS Q&A DEFINES "PIVOTAL"

    Its glossary defines Applicant, Batch, Comparator Product, Spare Subject
    and twenty-odd others, and neither "pivotal" nor "pilot" is among them. So
    this package cannot decide which a study is, and does not try. It is not
    inferred from sample size, study name, phase, endpoint, or whether a BE
    calculation was requested - every one of those correlates with the answer
    and none of them IS the answer.

    The caller states it, or `NOT_STATED` stands and the M13A floor is not
    applied. That is the same shape as `Framework`: this package is never told
    the dosage form either.
    """

    #: A study intended to support the BE conclusion. M13A's floor applies.
    PIVOTAL = "pivotal"
    #: A pilot or exploratory study, run to inform the pivotal one. M13A's
    #: floor does not reach it - which does not mean the study needs no
    #: subjects, only that this document sets no minimum for it.
    PILOT = "pilot"
    #: Nobody said. Distinct from PILOT, and deliberately so: "this is a
    #: pilot" and "we have not been told" are different claims, and only the
    #: first is an answer.
    NOT_STATED = "not_stated"


class MinimumApplicability(StrEnum):
    """Why a floor is, or is not, in force for this study.

    Four outcomes and not a nullable number, because "no minimum applies to a
    pilot" and "this package has confirmed no figure for this region" are
    different facts that a `None` would merge. `regulatory_n = 0` would be
    worse still: zero is a floor, and a false one.
    """

    APPLIES = "applies"
    #: A rule exists and its source scopes itself to a role this study is not.
    NOT_APPLICABLE_FOR_ROLE = "not_applicable_for_role"
    #: A rule exists, is role-scoped, and the role was never stated.
    ROLE_NOT_STATED = "role_not_stated"
    #: No rule is registered for this jurisdiction, framework and design.
    NONE_CONFIRMED = "none_confirmed"


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

    #: The study roles this row's SOURCE scopes itself to, or None for a
    #: source that sets its floor without qualifying the study's role.
    #:
    #: This is per-row and not global, because the two 12-subject rules in
    #: this registry come from different documents and only one of them is
    #: qualified. M13A guideline 2.1.3 and Q&A 2.1 both say "pivotal"; FDA's
    #: Statistical Approaches II.A says "The number of evaluable subjects in a
    #: PK BE study should not be less than 12" - a PK BE study, without
    #: qualification. Applying M13A's restriction to FDA's rule would remove a
    #: floor FDA states unconditionally.
    applies_to_roles: frozenset[StudyRole] | None = None

    def applies_to(self, study_role: StudyRole) -> bool:
        """Does this row's source reach a study in this role?"""
        return self.applies_to_roles is None or study_role in self.applies_to_roles

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
# divergence should be a new row rather than a rewrite - and because each
# regulator publishes its OWN Q&A of the same document, which is what each row
# cites.
#
# The EMA rows used to cite ICH's copy, which was the last regulator-specific
# claim in the package resting on the harmonised text. All three documents were
# read at Q&A 2.1 and carry the answer word for word; the numbers below are
# unchanged, and only the document a reader is sent to has.
#: M13A's floor is stated for PIVOTAL studies, in both places it appears:
#:
#:   guideline 2.1.3  "The number of subjects with evaluable data for primary
#:                    statistical analysis in a pivotal BE study should not be
#:                    less than 12 for a crossover design or less than 12 per
#:                    treatment group for a parallel design."
#:
#:   Q&A 2.1          "The requirement for a minimum of 12 evaluable subjects
#:                    in pivotal BE studies for a crossover design, or a
#:                    minimum of 12 per treatment group for a parallel
#:                    design, is an established practice by regulatory
#:                    agencies."
#:
#: Only PIVOTAL. NOT_STATED is excluded deliberately and is not an oversight:
#: an unstated role must not collect a floor its document never placed, and
#: `_resolve` reports that as ROLE_NOT_STATED rather than as no rule at all.
_M13A_ROLES = frozenset({StudyRole.PIVOTAL})

_M13A_CROSSOVER = dict(
    design_family=DesignFamily.CROSSOVER,
    framework=Framework.ICH_M13A,
    evaluable_total=12,
    verification=VerificationStatus.VERIFIED,
    scope=_M13A_SCOPE,
    applies_to_roles=_M13A_ROLES,
)
_M13A_PARALLEL = dict(
    design_family=DesignFamily.PARALLEL,
    framework=Framework.ICH_M13A,
    evaluable_per_group=12,
    verification=VerificationStatus.VERIFIED,
    scope=_M13A_SCOPE,
    applies_to_roles=_M13A_ROLES,
)

_REGISTRY: dict[tuple[str, Framework, DesignFamily], RegulatoryMinimum] = {
    # ---------------------------------------------------------- ICH M13A ---
    ("EMA", Framework.ICH_M13A, DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="EMA", citation=EMA_M13A_QA, **_M13A_CROSSOVER
    ),
    ("EMA", Framework.ICH_M13A, DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="EMA", citation=EMA_M13A_QA, **_M13A_PARALLEL
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
    # Section II.A, in the guidance's own words: "The number of evaluable
    # subjects in a PK BE study should not be less than 12. For highly variable
    # drug products, a minimum of 24 subjects are recommended for BE
    # assessment."
    #
    # That is a floor on the STUDY, not on a treatment group, and it is not
    # restricted by dosage form - so it is 12 total for both designs. Where a
    # study is also within M13A's scope the parallel figure is higher, and a
    # caller who says so gets it.
    #
    # These two rows were VERIFIED by relay until the guidance was obtained;
    # the wording above is now read from section II.A. The M13A rows were the
    # last ones still resting on relay - the three Q&A documents have since
    # been obtained and read at Q&A 2.1, and their citations pinned.
    ("FDA", Framework.GENERAL, DesignFamily.CROSSOVER): RegulatoryMinimum(
        jurisdiction="FDA",
        design_family=DesignFamily.CROSSOVER,
        framework=Framework.GENERAL,
        citation=FDA_STATISTICAL_APPROACHES_II_A,
        evaluable_total=12,
        verification=VerificationStatus.VERIFIED,
        scope="PK bioequivalence studies generally",
    ),
    ("FDA", Framework.GENERAL, DesignFamily.PARALLEL): RegulatoryMinimum(
        jurisdiction="FDA",
        design_family=DesignFamily.PARALLEL,
        framework=Framework.GENERAL,
        citation=FDA_STATISTICAL_APPROACHES_II_A,
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
    citation=FDA_STATISTICAL_APPROACHES_II_A,
    evaluable_total=24,
    verification=VerificationStatus.VERIFIED,
    scope="highly variable drug products",
)


@dataclass(frozen=True, slots=True)
class MinimumOutcome:
    """Whether a floor is in force, and why - not a nullable integer.

    `lookup` used to return `RegulatoryMinimum | None`, which had room for one
    fact where there are three: a rule applies; a rule exists but its source
    does not reach this study; no rule is confirmed at all. Collapsing the
    middle case into `None` is what let M13A's pivotal-study floor be applied
    to studies it was never placed on - the caller could not have told the
    difference even if it had asked.
    """

    applicability: MinimumApplicability
    #: The rule, present whenever one is REGISTERED for the key - including
    #: when it does not apply, so a report can name the document it is
    #: declining to apply and the reader can check that for themselves.
    rule: RegulatoryMinimum | None
    study_role: StudyRole
    #: One sentence a report can print. Never empty.
    reason: str

    @property
    def applies(self) -> bool:
        return self.applicability is MinimumApplicability.APPLIES

    def required_total(self) -> int | None:
        """The floor in subjects, or None when none is in force.

        None here means "no floor", which is NOT zero: zero would be a floor,
        and a false one. `applicability` says which of the three reasons.
        """
        if not self.applies or self.rule is None:
            return None
        return self.rule.required_total()


def lookup(
    jurisdiction: str,
    design_family: DesignFamily,
    *,
    framework: Framework | None = None,
    is_highly_variable: bool = False,
    study_role: StudyRole = StudyRole.NOT_STATED,
) -> MinimumOutcome:
    """Whether a regulatory floor is in force for this study, and which.

    `framework=None` means the caller has not stated which body of guidance
    governs, and resolves against `Framework.GENERAL` only. M13A's rules are
    never reached by default, because reaching them requires knowing the dosage
    form and this package is never told it.

    `study_role` defaults to NOT_STATED for the same reason, and with the same
    consequence: a role-scoped rule is not applied to a study whose role
    nobody has stated. It is reported as ROLE_NOT_STATED rather than as an
    absent rule, so a caller can tell "you did not say" from "there is none" -
    and `power.sample_size_abe` refuses outright rather than quietly
    recommending a smaller study.
    """
    if is_highly_variable and jurisdiction == "FDA":
        return _outcome(_HVD_MINIMUM, study_role)
    rule = _REGISTRY.get(
        (jurisdiction, framework or Framework.GENERAL, design_family)
    )
    if rule is None:
        return MinimumOutcome(
            applicability=MinimumApplicability.NONE_CONFIRMED,
            rule=None,
            study_role=study_role,
            reason=(
                f"No confirmed regulatory minimum for {jurisdiction}, "
                f"{framework or Framework.GENERAL} and a {design_family} "
                "design. Absent is a real answer: it is not zero, and it is "
                "not twelve."
            ),
        )
    return _outcome(rule, study_role)


def _outcome(rule: RegulatoryMinimum, study_role: StudyRole) -> MinimumOutcome:
    """Apply the row's own role constraint, if it declares one."""
    if rule.applies_to(study_role):
        return MinimumOutcome(
            applicability=MinimumApplicability.APPLIES,
            rule=rule,
            study_role=study_role,
            reason=rule.explain(),
        )

    roles = ", ".join(sorted(str(r) for r in rule.applies_to_roles or ()))
    if study_role is StudyRole.NOT_STATED:
        return MinimumOutcome(
            applicability=MinimumApplicability.ROLE_NOT_STATED,
            rule=rule,
            study_role=study_role,
            reason=(
                f"{rule.citation} sets its floor for {roles} studies, and the "
                "study's role was not stated. The floor is not applied to a "
                "study nobody has placed in its scope, and the document does "
                "not define the term for this package to decide it."
            ),
        )
    return MinimumOutcome(
        applicability=MinimumApplicability.NOT_APPLICABLE_FOR_ROLE,
        rule=rule,
        study_role=study_role,
        reason=(
            f"{rule.citation} sets its floor for {roles} studies. This study "
            f"is {study_role}, so that minimum does not apply to it. This "
            "says nothing about how many subjects the study needs - only that "
            "this document sets no floor for it."
        ),
    )


def active_citations() -> frozenset[Citation]:
    """Every citation this module can attach to a returned minimum.

    WHY THIS EXISTS RATHER THAN A SCAN OF `provenance`

    The pinning invariant has to be scoped to citations that live regulatory
    logic actually reaches. Scanning every `Citation` in `provenance` would be
    the wrong set in both directions: it would sweep in objects kept for
    context or history, and it would miss any citation built somewhere other
    than that module.

    So the set is derived from the registry itself. A row added to `_REGISTRY`
    is covered without anybody remembering to add it, which is the property
    that matters - the two Q&A citations sat unpinned AND undeclared for
    releases precisely because nothing enumerated them.
    """
    return frozenset(
        row.citation for row in (*_REGISTRY.values(), _HVD_MINIMUM)
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
