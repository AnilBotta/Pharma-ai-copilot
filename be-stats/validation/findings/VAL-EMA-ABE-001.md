# VAL-EMA-ABE-001

**For a non-replicate EMA study, the 2010 guideline's 4.1.8 rounds the
confidence interval's bounds and ICH M13A 2.2.4 does not.**

| | |
|---|---|
| Raised | PR #88 - opened to add 4.1.8 rounding to EMA standard ABE, and found that doing so would be wrong |
| Status | **`OPEN`** |
| Methods | `standard_abe` under EMA, `ema_nti_narrow_abe` |
| Severity | qualifying: a regulatory interpretation, recorded rather than chosen silently |

## What the sources say

The 2010 guideline, 4.1.8:

> To be inside the acceptance interval the lower bound should be >= 80.00% when
> rounded to two decimal places and the upper bound should be <= 125.00% when
> rounded to two decimal places.

ICH M13A 2.2.4, inside 2.2 "Data Analysis for Non-Replicate Study Design":

> The 90% confidence interval for the geometric mean ratio of these PK
> parameters used to establish BE should lie within a range of 80.00 - 125.00%.

No rounding sentence. The M13A Q&A (EMA/CHMP/ICH/325575/2024, 17 pages) was
extracted and searched for "rounded", "rounding", "decimal", "80.00", "125.00"
and "2.2.4": none occurs. The only match for "round" is "around" in the preface.

EMA/531548/2024 settles which applies:

- M13A came into effect on 25 January 2025, "formally superseding applicable
  parts of" the 2010 guideline.
- M13A "only relates to BE study considerations and data analysis for a
  non-replicate study design", and its data-analysis considerations include
  "BE criteria".
- A study completed and included in a submission **before** 25 January 2025
  keeps the 2010 guideline's requirements; a later submission follows M13A.

## What be-stats does

| route | design | comparison |
|---|---|---|
| standard ABE (EMA and FDA) | 2x2 crossover, parallel | `spec.ci_within_limits` - inclusive, unrounded |
| EMA 4.1.9 NTI | 2x2 crossover, parallel | `spec.ci_within_limits` - the same function |
| EMA 4.1.10 HVD, conventional branch | replicate | rounded to two decimals under 4.1.8 - M13A does not cover replicate designs |
| EMA 4.1.10 HVD, widened branch | replicate | unrounded - VAL-EMA-ABEL-003 |

## What this PR changed

PR #87 had EMA 4.1.9 round both bounds on 4.1.8's authority, while the
standard route compared unrounded and cited M13A 2.2.4. One crossover against
80.00-125.00% got two different comparisons from one regulator depending on
the route. EMA 4.1.9 now calls the standard route's comparison.

**No standard-route or FDA result moves.** `AcceptanceInterval.contains` keeps
the identical expression; it now calls the named function instead of spelling
it out.

## Why unrounded

- For a study submitted **after** 25 January 2025 it is M13A's literal text.
- For a study submitted **before**, 4.1.8 applies and rounds. Unrounded is then
  the stricter reading: every interval that passes unrounded also passes
  rounded, never the reverse. It can refuse a study 4.1.8 would pass, by at most
  0.005 on a bound, and cannot pass one 4.1.8 would refuse.

The engine takes no submission date, so it cannot tell the two apart. That is
why this is open rather than resolved.

## What would close it

Either an EMA statement on whether 4.1.8's two-decimal practice continues under
M13A, or a typed submission-regime input so a pre-2025 study is compared under
4.1.8.

## Related

- [VAL-EMA-NTI-001](VAL-EMA-NTI-001.md) - the same question, asked narrowly about the tightened interval, now confined to pre-2025 studies
- [VAL-EMA-ABEL-003](VAL-EMA-ABEL-003.md) - rounding against widened limits on the replicate path
