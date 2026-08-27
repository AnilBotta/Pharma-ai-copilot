# VAL-EMA-ABEL-002

**EMA states the ABEL cap as a limit pair; the formula at CVwR = 50% gives a
very slightly wider one. `be-stats` applies the stated pair.**

| | |
|---|---|
| Raised | PR #60, while implementing the cap |
| Status | `ACCEPTED_ORACLE_DIVERGENCE` |
| Method | `ema_hvd_abel` |
| Action in `be-stats` | none — the regulator's stated numbers decide |

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
reading (a) is the marginally more conservative of the two, and the cap engages
at CVwR ≈ 49.993% rather than exactly 50%.

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

## Why it stays open

No run closes it. Both readings are defensible and will keep differing for as
long as EMA prints a rounded pair and PowerTOST recomputes it. It is carried on
the EMA cases so the `ema_hvd_abel` tier-3 row reads `PASSED_WITH_FINDING`
rather than `PASSED`.
