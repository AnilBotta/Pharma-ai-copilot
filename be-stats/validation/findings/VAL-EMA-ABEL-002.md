# VAL-EMA-ABEL-002

**EMA states the ABEL cap as a limit pair; the formula at CVwR = 50% gives a
very slightly wider one. `be-stats` applies the stated pair.**

| | |
|---|---|
| Raised | PR #60, while implementing the cap |
| Status | **`RESOLVED`** |
| Classification | `ACCEPTED_ORACLE_DIVERGENCE` |
| Method | `ema_hvd_abel` |
| Action in `be-stats` | none — the regulator's stated numbers decide |

> **`RESOLVED` means the question is answered, not that the numbers
> converged.** EMA states the maximum widened range as 69.84 – 143.19% and its
> table gives the ≥50% row as exactly that pair. PowerTOST preserves the
> unrounded formula. That is a documented divergence between an oracle and a
> regulator — not a regulatory ambiguity, and not a `be-stats` defect. The
> 0.0032 percentage-point difference is permanent and appears in every run,
> which is why the tier-3 row stays qualified.

## The two readings

Section 4.1.10 says widening is permitted

> to a maximum of 69.84 – 143.19%

and its table ends `≥50 | 69.84 | 143.19`. Two readings follow, and they are
not quite the same rule:

| reading | lower | upper |
|---|---:|---:|
| **(a) the stated pair** — cap each limit at the printed number | 69.84 | 143.19 |
| (b) cap CVwR at 50% and evaluate `exp(±k·sWR)` | 69.83678 | 143.19102 |

`be-stats` applies **(a)**. PowerTOST's `scABEL` applies **(b)**:

```r
ret <- ifelse(CV>CVcap, exp(r_const*CV2se(CVcap)), ret)
```

## Size of the difference

0.0032 percentage points on the lower limit and 0.0010 on the upper — about
three parts in a hundred thousand. It can only change a decision for a study
whose 90% confidence interval falls in that sliver.

The stated pair is fractionally **narrower** than the formula's value, so
reading (a) is the marginally more conservative of the two at and above the
cap. The cap engages at exactly CVwR = 50% - see the amendment below.

## Why (a)

Consistency with how this package has treated every such question. FDA states
`sWR ≥ 0.294` where the derivation would give 0.293560, and `be-stats` follows
the stated number (`VAL-FDA-HVD-002`). FDA's NTI appendix states `Δ = 1/0.9`
where its own example code writes `1.11111`, and `be-stats` follows the stated
constant. The rule the package applies is the one the regulator wrote down; a
value that reproduces it to the published precision is recorded beside it, not
substituted for it.

`spec.ema_abel_cap_computed()` is reading (b), kept so the two can be compared.
A test asserts they agree to the two decimals the guideline publishes — which
is the real point: the guideline's stated pair *is* the formula's value, printed
to the precision the guideline chose.

## Consequence for tier 3

Predicted, not discovered. A `scABEL` comparison will agree **exactly** for
CVwR below the cap and differ by 0.0032 / 0.0010 percentage points at or above
it. The validation cases assert that pattern rather than widening a tolerance
to hide it: a case below the cap uses a tolerance at floating-point scale, and
the capped case asserts the divergence is the predicted one.

Recording it before the comparison ran is the practice `VAL-FDA-HVD-001`
established. A difference you predicted is evidence that you understand both
implementations; the same difference found afterwards is a finding.

## Why a resolved finding still qualifies the tier-3 row

Resolved is not absent. The divergence is permanent — it appears in every run
for as long as EMA prints a rounded pair and PowerTOST recomputes it — so the
`ema_hvd_abel` tier-3 row reads `PASSED_WITH_FINDING` rather than `PASSED`.

Two different facts, and the report carries both:

- **`RESOLVED`** — nobody needs to investigate this again.
- **the row stays qualified** — the comparison against the oracle is not
  unconditional, and a reader should know that before relying on it.

Collapsing them would mean either hiding a real numerical difference behind a
green tick, or leaving a closed question permanently open. Neither is honest.

## What would reopen it

EMA restating the cap — in the future ICH M13C, say — or a PowerTOST release
that adopts the stated pair. Neither is an action for this package.

## What this finding does *not* qualify

`EMA_ABEL_LIMIT_CALCULATION` is `VALIDATED`. This finding is not a reservation
about the limit calculation: the tier-1B table is what *confirms* the stated
reading, since all five of the guideline's own rows reproduce under it. The
finding records a difference between this package and an **oracle**, and an
oracle does not outrank the regulator.

## Amendment, 2026-09-14 (PR #85, independent review)

The cap was applied to **each limit independently** against the rounded pair.
Because the pair is not exactly reciprocal (1/0.6984 = 1.43184, not 1.4319),
that turned one rule into two floating-point crossings: the lower limit capped
from CVwR 49.9928% and the upper from 49.9989%, with a band in between where
only the lower limit was capped. EMA's table states no such band.

The cap is now **one rule keyed on CVwR**:

| CVwR | limits |
|---|---|
| 30% < CVwR < 50% | `exp(-/+ 0.760 sWR)` |
| CVwR >= 50% | exactly 69.84 - 143.19% |

Consequences, stated rather than hidden:

- Below 50% be-stats and PowerTOST's `scABEL` now agree exactly, including in
  the former band.
- For CVwR in [49.9928%, 50%) the formula gives limits up to 0.0032 percentage
  points beyond the published pair, and they are applied, because the table
  switches to the pair at 50.
- At and above 50% the divergence this finding records is unchanged -
  0.00322 / 0.00102 percentage points - so the status stays **`RESOLVED`** and
  the tier-3 row stays `PASSED_WITH_FINDING`.

The PowerTOST cap case now supplies its CVwR to `ema_abel_limits` exactly, so
the cap decision is not moved by re-deriving CVwR from sWR.
