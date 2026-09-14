# VAL-EMA-ABEL-003

**EMA states two-decimal rounding of the confidence interval for 80.00-125.00%,
and says nothing about rounding against widened limits.**

| | |
|---|---|
| Raised | PR #85, independent review of the EMA ABEL audit |
| Status | **`OPEN`** |
| Method | `ema_hvd_abel` |
| Severity | qualifying: a regulatory interpretation, recorded rather than chosen silently |

## What the sources say

Section 4.1.8 of the guideline (CPMP/EWP/QWP/1401/98 Rev. 1):

> To be inside the acceptance interval the lower bound should be >= 80.00% when
> rounded to two decimal places and the upper bound should be <= 125.00% when
> rounded to two decimal places.

Section 4.1.10 gives the widened limits as `exp(+/- 0.760 sWR)`, a maximum of
69.84-143.19%, and a table printed to two decimals. It says nothing about
whether the confidence interval is rounded before it is compared with them.

Also read, with no rounding sentence in any of them: the PKWP Q&A
(EMA/618604/2008 Rev. 13 - the replicate analysis section and questions 4 and
19), EMA/531548/2024, and ICH M13A 2.2.4, which states "80.00 - 125.00%" alone.

## What be-stats does

| comparison | rule |
|---|---|
| CI against 80.00-125.00% (AUC; Cmax at CVwR <= 30%; Cmax explicitly not justified or not prespecified) | each bound rounded to two decimals, `ROUND_HALF_UP` in `decimal`, then compared |
| CI against widened limits | unrounded, against the limits as computed |
| GMR against 80.00-125.00% | as estimated, inclusive |

The rounding is `be_stats.regulatory_rounding`: decimal arithmetic on the
shortest decimal representation of the value, never Python's binary `round`
and never a formatted display string.

## Why unrounded against widened limits

Rounding the interval there would grant each bound a margin of up to 0.005
percentage points that EMA has not stated for widened limits. The unrounded
comparison grants none. A third reading - rounding the formula limits
themselves to two decimals, as the table prints them - is not stated by EMA
either, and could move in either direction.

## Tie convention

EMA states none for an exact half. be-stats uses `ROUND_HALF_UP` and names it in
`regulatory_rounding.TIE_POLICY`. No decision test sits on an exact tie; the tie
behaviour is tested on the helper, as the documented policy.

## What would close it

An EMA statement - in the guideline, a PKWP answer or the future ICH M13C - on
how a confidence interval is compared with widened limits.
