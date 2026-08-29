# VAL-FDA-HVD-002

**PowerTOST switches at sWR = 0.293560; FDA Appendix G states 0.294.**

| | |
|---|---|
| Raised | source inspection during the `VAL-FDA-HVD-001` investigation, 2026-08-28 |
| Status | `RESOLVED` |
| Classification | `ACCEPTED_ORACLE_DIVERGENCE` |
| Method | `fda_hvd_rsabe` |
| Action required in `be-stats` | None. |

## What differs

FDA, *Statistical Approaches to Establishing Bioequivalence*, May 2026,
Appendix G states the switching rule as a number:

    sWR >= 0.294

PowerTOST 1.5-7 derives it instead. `R/scABEL.R` line 17:

```r
r <- list(name="FDA", CVswitch=0.3, r_const=log(1.25)/0.25, CVcap=Inf, ...)
```

and `R/power_RSABE2L_isc.R` line 156 converts that CV to the log scale:

```r
s2switch <- log(CVswitch^2 + 1)
```

which on the sWR scale is `sqrt(log(1.09))` = **0.293560379208524**, not 0.294.
The two differ by 4.4 × 10⁻⁴. A study whose estimated sWR lands in
`[0.293560, 0.294)` is routed to the scaled criterion by PowerTOST and to the
unscaled branch by FDA.

## Why `be-stats` does not follow the oracle here

This is the exact distinction settled in `be-stats` 0.1.1 (PR #54). FDA's 0.294
is the regulator's criterion applied to an estimated sWR — not a rounded display
of `sqrt(log(1 + 0.30²))`. The earlier plan to derive the threshold from
CV = 30% was reversed on statistical review, and the guard that forbade the
literal `0.294` was deleted.

Both numbers are in the package, and they are different things:

- `CV = 0.30` — the classification threshold for a highly variable drug,
  section III.C.
- `sWR = 0.294` — the switching threshold, Appendix G.

PowerTOST is an implementation oracle, not a regulatory authority. It is free to
encode the rule differently; `be-stats` follows the regulator.

## How much it is worth

On CVwR 0.31, n = 36, 2×2×4 — the scenario with the largest share of studies
near the switch:

| | |
|---|---|
| `P(below)` at FDA's 0.294 | 0.4354 |
| `P(below)` at PowerTOST's 0.293560 | 0.4307 |
| difference in switching probability | 0.0047 |
| difference in mixed power | under 0.001 |

That is roughly a twentieth of the 0.01238 that raised `VAL-FDA-HVD-001`, and it
was never a candidate explanation for it: the be-stats quantity in that
comparison was computed without reference to any switch at all.

Recomputed on every investigation run and recorded under `switch_probability` in
`VAL-FDA-HVD-001-evidence.json`.

## Consequence for the comparison

None, by construction. The RSABE cases now run PowerTOST with `CVswitch = 0`, so
no comparison depends on the oracle's threshold. The threshold is compared as a
*rule* instead: the R side reports both switching probabilities in closed form,
and the be-stats side is checked against FDA's via `p_below_switch`.

## Why a resolved finding still qualifies the tier-3 row

Resolved is not absent. Both sides behave as designed and will continue to
differ for as long as PowerTOST derives the threshold and FDA states it, so the
`fda_hvd_rsabe` tier-3 row reads `PASSED_WITH_FINDING` rather than `PASSED` —
which is the honest summary. The scaled criterion agrees with an independent
implementation whose switching rule is known to differ from the regulator's in
the fourth decimal.

`RESOLVED` records that nobody needs to investigate it again; the qualification
records that the comparison is not unconditional. Both are true.

Revisit only if FDA restates the rule, or if a comparison is added that depends
on the oracle's switch.
