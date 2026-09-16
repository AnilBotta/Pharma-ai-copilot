"""Rounding a number the way a regulator reads it, not the way a float stores it.

WHY THIS EXISTS

EMA's Guideline on the Investigation of Bioequivalence (CPMP/EWP/QWP/1401/98
Rev. 1), section 4.1.8:

    "To be inside the acceptance interval the lower bound should be >= 80.00%
    when rounded to two decimal places and the upper bound should be <=
    125.00% when rounded to two decimal places."

That is a DECISION rule, and it is stated in decimal. A binary float cannot
hold 79.995 or 125.005; `79.995` is stored as 79.99499999999999744..., and
Python's `round(79.995, 2)` returns 79.99. A decision that depended on that
would turn on the binary representation of a number rather than on the number
the regulator's rule is about.

So the rounding here is done in `decimal`, on the SHORTEST decimal string that
represents the float - `repr(value)`, which Python guarantees round-trips - and
never on the float's exact binary expansion, and never by parsing a formatted
display string.

THE TIE RULE, AND WHERE IT COMES FROM

EMA states "rounded to two decimal places" and does not state what happens to
an exact half. That silence is recorded, not filled in by assumption: this
module uses ROUND_HALF_UP (a half rounds away from zero for the positive
percentages it is applied to), the conventional decimal rule and the one SAS's
ROUND function applies, and names it in `TIE_POLICY` so a reader does not have
to infer it. It is NOT banker's rounding (ROUND_HALF_EVEN), which is what a
reader could otherwise mistake Python's decimal default for.

No be-stats test decides a study on an exact half-tie. The tie behaviour is
tested on the helper itself, as the documented policy, separately from the
decision tests, which sit clearly on one side of a tie or the other.

THIS MODULE KNOWS NO REGULATOR

It rounds. Which comparisons are rounded, and against which limits, is decided
by the module implementing a regulator's rule - see `ema_hvd`.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

#: The tie convention, named once. EMA 4.1.8 does not state one.
TIE_POLICY = (
    "ROUND_HALF_UP on the shortest decimal representation of the value: an "
    "exact half rounds away from zero. EMA 4.1.8 says 'rounded to two decimal "
    "places' and states no tie convention; this is the conventional decimal "
    "rule, chosen explicitly rather than inherited from binary round()."
)


def exact_decimal(value: float) -> Decimal:
    """The decimal a float stands for: its shortest round-tripping repr.

    `Decimal(80.0)` is exact, but `Decimal(79.995)` is the binary expansion
    79.99499999999999744...; `Decimal(repr(79.995))` is 79.995, which is the
    number anyone reading the value means.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"cannot round a non-finite value: {value!r}")
    return Decimal(repr(number))


def round_half_up(value: float, places: int = 2) -> Decimal:
    """`value` rounded to `places` decimal places under `TIE_POLICY`."""
    if places < 0:
        raise ValueError(f"places must be non-negative, got {places}")
    quantum = Decimal(1).scaleb(-places)
    return exact_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


__all__ = ["TIE_POLICY", "exact_decimal", "round_half_up"]
