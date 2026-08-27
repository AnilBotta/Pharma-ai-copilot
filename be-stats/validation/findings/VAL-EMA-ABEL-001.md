# VAL-EMA-ABEL-001

**PowerTOST's `p(BE-ABEL)` is the mixed decision, not the ABEL criterion — and
`power.scABEL` carries documented empirical adaptations.**

| | |
|---|---|
| Raised | source inspection during PR #60, before any comparison was written |
| Status | `PREEMPTED` — recorded before a fixture existed, so no wrong comparison was ever run |
| Method | `ema_hvd_abel` |
| Action | `scABEL` is the primary oracle; `power.scABEL` is not used |

## Why this was looked for at all

PR #59 (`VAL-FDA-HVD-001`) cost a full investigation to discover that
PowerTOST's `p(BE-sABEc)` is not the scaled criterion but the *mixed* decision.
The conclusion recorded there was that verifying a reported quantity's actual
meaning must become a standard step before writing any oracle comparison. This
is that step, done first.

## Finding 1 — the same naming trap, in the EMA family

PowerTOST 1.5-7, `R/power_scABEL1.R`:

```r
names(counts) <- c("BE", "BEwl", "BEpe", "BEabe")          # line 155
BE   <- (lABEL<=lCL) & (uCL<=uABEL)                        # line 211  ABEL alone
BE   <- ifelse(s2wRs>s2switch, BE, BEABE)                  # line 220  OVERWRITTEN
counts["BEwl"] <- counts["BEwl"] + sum(BE)                 # line 229
names(p) <- c("p(BE)", "p(BE-ABEL)", "p(BE-pe)", "p(BE-ABE)")  # line 133
```

Line 211 computes the ABEL criterion. Line 220 **overwrites the same variable**
with the mixed decision — ABEL above the switch, conventional ABE below — and
that is what is reported as `p(BE-ABEL)`.

The subject-data route does the same thing, in
`R/power_RSABE2L_sdsims.R`:

```r
BE <- ifelse(s2wRs < s2switch, BE_ABE, BE_RSABE)           # line 317
names(p) <- c("p(BE)", "p(BE-ABEL)", "p(BE-pe)", "p(BE-ABE)")  # line 341
```

So the trap is in both routes. `p(BE-pe)` is the point-estimate constraint
alone and *is* directly comparable, exactly as in the FDA case.

## Finding 2 — `power.scABEL` is a tuned approximation

This one has no FDA analogue and is the more serious of the two. For EMA,
`reg_const("EMA")` leaves `est_method = "ANOVA"`, and `power.scABEL` routes on
that (`R/power_scABEL.R` line 17) to `power.scABEL1`, whose own header says:

> power via key statistic sims with empirical adaptions to obtain better
> agreement to sims based on subject data

The adaptations are explicit in the source, and there are three:

| line | what |
|---|---|
| 118 | `# next is purely empirical for 2x3x3` — `dfTT <- dfRR` |
| 177–179 | `s2wT is empirical because dfTT is not defined and artificially set to equal dfRR` |
| 184–185 | for 2×2×4, `mses <- (mses_ABE + (s2wTs + s2wRs)/2)/2` — the *average of two different estimators*, described as the "'mean' of both attempts V1.1-02/V1.1-03" |
| 212–213 | `#--- conventional ABE for low CV (0.2 is purely empiric)` — a different mean square is used for the ABE branch when CVwR ≤ 20% |

None of that is in the EMA guideline. It is curve-fitting to make a fast
key-statistic simulation agree with a slow subject-data one.

**A tuned approximation is not an oracle.** Comparing `be-stats` against
`power.scABEL` would be comparing a faithful implementation against a
deliberately inexact one and calling the difference a finding.

## What is used instead

| oracle | kind | what it establishes |
|---|---|---|
| `scABEL(CV, regulator="EMA")` | **deterministic** | the widened limits, exactly. No simulation, no tolerance beyond floating point. |
| EMA Data set I / II | **tier 1B** | Method A's point estimate and 90% CI, and CVwR, against the regulator's own published numbers |
| `power.scABEL.sdsims` | Monte Carlo | available and adaptation-free (it fits real `lm()` models), but reports the same mixed `p(BE-ABEL)`, so only `p(BE-pe)` is comparable without isolating the switch |

`scABEL` being deterministic is worth stating plainly: it makes the central
quantity of this method checkable **exactly**, which is stronger evidence than
any amount of agreeing simulation.

## Two things `scABEL` does that are worth recording

```r
ret <- ifelse(CV <= (CVswitch + 1e-10), 1.25, exp(r_const*CV2se(CV)))
ret <- ifelse(CV>CVcap, exp(r_const*CV2se(CVcap)), ret)
ret <- c(1/ret, ret)                                  # lower is 1/upper
```

1. **The switch matches EMA.** Widening applies for `CV > 0.3` (with a 1e-10
   tolerance), which is the guideline's strict `>30%`. Unlike the FDA case
   (`VAL-FDA-HVD-002`), PowerTOST and the regulator agree here.
2. **The lower limit is computed as `1/upper`,** not as `exp(-k·sWR)`. Equal in
   exact arithmetic, potentially a last-ULP difference in floating point. EMA
   states the pair symmetrically as `exp[±k·sWR]`, which is what `be-stats`
   computes.

The cap is a separate question — see `VAL-EMA-ABEL-002`.
