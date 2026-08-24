"""Regulatory profiles.

WHY THIS EXISTS AT ALL, AND WHY IT IS HERE FROM THE FIRST COMMIT

FDA and EMA do not agree, and the disagreement reaches into the ordinary
average-bioequivalence case rather than living out at the edges. For a narrow
therapeutic index drug EMA narrows the acceptance interval; FDA instead applies
reference-scaled average BE together with a comparison of variances. Those are
structurally different tests on the same data.

An engine that computed "the" bioequivalence result and left the regulator as a
formatting concern would be wrong for at least one of the two filings. So a
profile is required at every entry point, and a result always carries the
profile it was computed under.

WHAT IS DELIBERATELY NOT DECIDED HERE

`NARROW_THERAPEUTIC_INDEX` under `FDA` has no interval, because FDA does not
narrow one - it requires reference-scaled ABE plus a variance comparison, which
is Phase 2. Asking for it raises rather than guessing, because a plausible
80.00-125.00 would be a wrong answer that looked like a right one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Regulator(StrEnum):
    FDA = "FDA"
    EMA = "EMA"


class DrugClass(StrEnum):
    """How the acceptance interval is chosen.

    `STANDARD` covers the ordinary case. The other two change the test, not
    merely the limits, and both regulators treat them differently.
    """

    STANDARD = "standard"
    NARROW_THERAPEUTIC_INDEX = "narrow_therapeutic_index"
    HIGHLY_VARIABLE = "highly_variable"


class NotApplicable(Exception):
    """This profile does not answer this question with an interval.

    Raised rather than returning a default. A caller that has asked for
    something the regulator does not do needs to know that, not receive a
    number that happens to be the standard one.
    """


@dataclass(frozen=True, slots=True)
class AcceptanceInterval:
    """The interval a 90% confidence interval must fall inside, in percent."""

    lower: float
    upper: float
    #: Where this interval comes from. Carried into the report so a reader can
    #: check it rather than trust it.
    basis: str

    def contains(self, ci_lower: float, ci_upper: float) -> bool:
        """Is the whole confidence interval inside the acceptance interval?

        Inclusive at both ends: the convention is 80.00-125.00, and a bound
        landing exactly on a limit passes.
        """
        return ci_lower >= self.lower and ci_upper <= self.upper


#: The conventional interval, shared by both regulators for the standard case.
_STANDARD = (80.00, 125.00)

#: EMA narrows for NTI drugs. 90.00-111.11 is 1/1.11 and 1.1111 as percentages;
#: the pair is asymmetric on the percent scale because it is symmetric on the
#: log scale, which is where the test actually happens.
_EMA_NTI = (90.00, 111.11)


@dataclass(frozen=True, slots=True)
class RegulatoryProfile:
    """A regulator, and the rules that follow from choosing it."""

    regulator: Regulator

    #: Both regulators use a 90% confidence interval, i.e. two one-sided tests
    #: at 5%. Kept as data rather than a constant so a profile that differs
    #: cannot be added by editing arithmetic somewhere else.
    alpha: float = 0.05

    @property
    def confidence_level(self) -> float:
        return 1.0 - 2.0 * self.alpha

    def acceptance_interval(
        self, drug_class: DrugClass = DrugClass.STANDARD
    ) -> AcceptanceInterval:
        if drug_class is DrugClass.STANDARD:
            lo, hi = _STANDARD
            return AcceptanceInterval(lo, hi, f"{self.regulator} standard interval")

        if drug_class is DrugClass.NARROW_THERAPEUTIC_INDEX:
            if self.regulator is Regulator.EMA:
                lo, hi = _EMA_NTI
                return AcceptanceInterval(
                    lo, hi, "EMA narrowed interval for NTI drugs"
                )
            raise NotApplicable(
                "FDA does not assess a narrow therapeutic index drug with a "
                "narrowed fixed interval. It requires reference-scaled average "
                "bioequivalence together with a comparison of within-subject "
                "variances, which this version does not implement. Do not "
                "substitute the standard interval."
            )

        if drug_class is DrugClass.HIGHLY_VARIABLE:
            raise NotApplicable(
                f"{self.regulator} widens the interval for a highly variable "
                "drug by scaling to the reference variability, which requires a "
                "replicate design and is not implemented in this version. The "
                "standard interval is not a conservative substitute - it is a "
                "different test."
            )

        raise NotApplicable(f"Unhandled drug class: {drug_class}")


FDA = RegulatoryProfile(Regulator.FDA)
EMA = RegulatoryProfile(Regulator.EMA)


def profile_for(regulator: Regulator | str) -> RegulatoryProfile:
    match Regulator(regulator):
        case Regulator.FDA:
            return FDA
        case Regulator.EMA:
            return EMA
