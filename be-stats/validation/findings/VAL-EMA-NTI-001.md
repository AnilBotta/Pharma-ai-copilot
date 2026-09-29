# VAL-EMA-NTI-001

**EMA states two-decimal rounding of the confidence interval for
80.00-125.00%, and does not restate it for the tightened 90.00-111.11%.**

| | |
|---|---|
| Raised | PR #87, the EMA narrow therapeutic index audit |
| Status | **`OPEN`** |
| Method | `ema_nti_narrow_abe` |
| Severity | qualifying: a regulatory interpretation, recorded rather than chosen silently |

## What the sources say

Section 4.1.8 of the guideline (CPMP/EWP/QWP/1401/98 Rev. 1), which is the only
sentence in the document that says what being inside an acceptance interval
means:

> To be inside the acceptance interval the lower bound should be >= 80.00% when
> rounded to two decimal places and the upper bound should be <= 125.00% when
> rounded to two decimal places.

Section 4.1.9 replaces the interval and says nothing about the comparison:

> In specific cases of products with a narrow therapeutic index, the acceptance
> interval for AUC should be tightened to 90.00-111.11%. Where Cmax is of
> particular importance for safety, efficacy or drug level monitoring the
> 90.00-111.11% acceptance interval should also be applied for this parameter.

Also read, with no rounding sentence in any of them: the PKWP Q&A answers for
ciclosporin ("a narrowed (90.00-111.11%) acceptance range should be applied for
both AUC and Cmax") and tacrolimus ("[90-111%] for AUC and [80-125%] for
Cmax"); EMA/531548/2024; and ICH M13A 2.2.4, which states 80.00-125.00% with no
rounding sentence and no narrow therapeutic index provision at all.

## What be-stats does

Both bounds are rounded to two decimal places and then compared - against
90.00-111.11% for a tightened endpoint, and against 80.00-125.00% for a
confirmed NTI drug whose Cmax is explicitly not of particular importance. Both
go through `ema_nti._interval_contained`, which calls the one
`regulatory_rounding` helper this package has.

## Why that reading

4.1.9 changes **which** interval applies. 4.1.8 defines what being inside one
means, and nothing else in the guideline does. Both of 4.1.9's limits are
published to exactly two decimal places, in the same document and the same
style as 4.1.8's, so the comparison is well defined against them.

The residual doubt, which is why this is open: 4.1.8's sentence names 80.00 and
125.00 rather than "the acceptance interval in force", and 4.1.9 does not
repeat it.

## Why this is the opposite choice from VAL-EMA-ABEL-003

That finding records an **unrounded** comparison against 4.1.10's widened
limits. The difference is a fact about the numbers rather than a preference:

| | published form | comparison |
|---|---|---|
| 4.1.9 tightened | 90.00 and 111.11, printed constants | rounded |
| 4.1.8 conventional | 80.00 and 125.00, printed constants | rounded |
| 4.1.10 widened | `exp(+/- 0.760 sWR)`, computed per study | unrounded |

A widened limit has no published two-decimal form to round a bound against, so
rounding there would grant a margin against a number EMA never published.

## Tie policy

EMA states no convention for an exact half. be-stats uses `ROUND_HALF_UP` and
names it (`regulatory_rounding.TIE_POLICY`). No decision test sits on an exact
tie.

## What would close it

An EMA statement - in the guideline, a PKWP answer or the future ICH M13C - on
whether 4.1.8's two-decimal comparison applies to the tightened interval. If
EMA confirms it does not, switch `ema_nti._interval_contained` to the unrounded
comparison for the narrowed branch and close this finding.

## Related

- [VAL-EMA-ABEL-003](VAL-EMA-ABEL-003.md) - the same question for widened limits
