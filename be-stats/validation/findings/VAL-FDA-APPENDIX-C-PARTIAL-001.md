# VAL-FDA-APPENDIX-C-PARTIAL-001

**The best-supported partial-replicate denominator df is about 19.89; 22.540 is
incompatible with EMA's published interval under the corroborated SE; and
Appendix C's covariance is not fully identifiable on a partial replicate
design.**

Raised by PR #63. **Resolved** — `PACKAGE_SCOPE_LIMITATION`. No production code
was touched; `FDA_REPLICATE_STANDARD_ABE_PARTIAL` remains `NOT_IMPLEMENTED`.

## The answer

| source | −2logREML | estimate | SE | df | reproduces published CI |
|---|---|---|---|---|---|
| independent, **observed** information | −151.974445 | 102.26440% | 0.0303172 | **19.8906** | **yes — 97.05, 107.76** |
| independent, expected information | −151.974445 | 102.26440% | 0.0303172 | 21.5425 | no — 97.07, 107.73 |
| ReplicateBE.jl 1.0.15 | −151.974445 | 102.26439% | 0.0303172 | 22.5403 | no — 97.08, 107.72 |

**22.540 is incompatible with EMA's published two-decimal CI when combined with
the independently corroborated SE ≈ 0.0303172. The published interval supports
a df of approximately 19.24–19.98; the independent observed-information
calculation gives 19.8906.** `19.603` was the right region for the wrong reason.

### What is and is not claimed

`19.8906` is the **best-supported independent candidate**. It is *not* a
regulator-confirmed df: EMA published neither a standard error nor a
denominator df, and no licensed SAS run is available.

About `22.540`, precisely:

- ReplicateBE's point estimate and SE agree with every other engine tried.
- Its df produces a 90% CI that does not round to EMA's published CI.
- Given the independently reproduced SE, 22.540 lies outside the **entire** df
  range compatible with the published rounded interval.
- **A licensed SAS denominator df remains the decisive missing oracle.** Until
  one exists this is an incompatibility with a published *rounded* interval
  under a corroborated but *unpublished* SE — not a proof that 22.540 is wrong,
  and not a refutation by any regulator.

## How much the published output actually pins down

`19.603` has been carried through three PRs and looks precise to three
decimals. It is not a published value — it is one inversion of a
**two-decimal** interval against an **unpublished** standard error.

The half-width on the log scale depends only on the *ratio* of the published
limits, so the estimate's own rounding never enters:

    half_width = log(U / L) / 2,   L ∈ [97.045, 97.055),  U ∈ [107.755, 107.765)

That gives **df ∈ [19.24, 19.98]**. `19.603` is inside it, `19.8906` is inside
it, `22.540` is not.

### The conclusion rests on the standard error, so it was inverted onto it

Rather than assert the SE is right, hold each candidate df fixed and ask what
SE the published interval would then demand:

| df | SE it would require | shift from the agreed value |
|---|---|---|
| 22.540 | 0.0304844 – 0.0305415 | **+0.55% to +0.74%** |
| 19.603 | 0.0302889 – 0.0303456 | −0.09% to +0.09% |

For ReplicateBE's df to reproduce the published interval, **its own standard
error would have to be off by more than half a percent** — a quantity that
nlme, glmmTMB, ReplicateBE and the implementation built for this PR all
reproduce to seven significant figures.

That is the strength of the incompatibility, and also its limit: EMA published
no standard error, so 0.0303172 is an inference from independent software
rather than a regulator's number, and every conclusion resting on it inherits
that status.

## Why ReplicateBE is not an oracle here

**It is not a covariance disagreement.** The independent fit reaches the same
optimum (−2logREML = −151.974445), the same estimate and the same SE.

**Its own stated scope** covers *"full-replicated … (2x2x4, 2x2x3)"* — both
**two-sequence** designs. Data set II is a **three-sequence** partial replicate
and was never claimed.

**Its source was inspected**: `A = 2.0*inv(H)` from a ForwardDiff Hessian of
−2logREML, falling back to `pinv` below a singular-value limit. So it uses
*observed* information, as this package does — the difference is **not**
observed-versus-expected, and an earlier hypothesis to that effect was dropped
when the source contradicted it.

**Not claimed:** the exact line responsible for 22.540 was not isolated, and no
defect in ReplicateBE has been demonstrated. The evidence is external and
negative.

## The mathematical identifiability result — ESTABLISHED

> For the TRR/RTR/RRT partial-replicate structure with **one test observation
> per subject**, σ²_BT and σ²_WT are not separately identifiable under the
> Appendix C covariance decomposition. Only their sum is identified from these
> data.

- The observed information has **rank 4 of 5**. Its null eigenvector is
  `(+0.707, 0, 0, −0.707, 0)` — exactly the σ²_BT − σ²_WT direction.
- The two engines report materially different splits — 0.070494 / 0.0000006
  against 0.061604 / 0.008890 — while their **sums agree to five decimals**:
  0.0704946 against 0.0704941.
- **The T−R estimate and its SE remain estimable.** The contrast depends only
  on the identified sum; the gradient of `Var(L'β)` has equal components on
  σ²_BT and σ²_WT and is therefore orthogonal to the null direction. The df is
  stable at 19.8906 across eight orders of magnitude of pseudo-inverse cutoff.

A consistent observation, offered as nothing more: EMA publishes a
within-subject CV for the reference on Data set II and does not publish one for
the test. That is consistent with the identifiability result, but **the
document does not state that non-identifiability is the reason for the
omission**, and no rationale is attributed to EMA here.

## The regulatory handling of that result — NOT DETERMINED

No SAS output and no FDA text has been found explaining how `PROC MIXED` with
`DDFM=SATTERTH` resolves this rank-deficient variance-parameter situation —
whether it holds a parameter, reduces the dimension, or proceeds another way —
nor what a submission is expected to report when one of the five covariance
parameters is not identifiable.

So: estimate, SE, df and the 90% CI are unique and computable. The individual
covariance parameters are not — any implementation reports an arbitrary point
on a flat ridge, and two correct implementations will disagree about σ²_BT and
σ²_WT while agreeing about every decision quantity. **How that should be
reported is an open regulatory question, not a settled one.**

## Boundary handling, confirmed by a second route

Data set I is the control and sits on the PSD boundary at ρ = 1.

| | df | reproduces published CI |
|---|---|---|
| unconstrained, five free parameters | 75.0801 | no |
| **boundary-reduced, four free parameters** | **207.7269** | **yes** |
| be-stats production (Cholesky) | 207.7350 | yes |

Counting five free parameters at a boundary solution understates the df by a
factor of nearly three. Production reaches 207.735 through a Cholesky
parameterisation in which the boundary is an interior point; this
implementation reaches 207.727 by imposing the rank-1 constraint explicitly.

Two different routes agreeing, with a published interval to select between them
and the naive alternative, is what makes the boundary treatment credible — on
the **fully** replicate design, where such an interval exists.

## What was not done

- **Licensed SAS: NOT AVAILABLE.** SAS OnDemand was excluded by the brief as
  licence-inappropriate. The strongest possible evidence remains unobtained.
- **EMA raw SAS output: searched, NOT FOUND.** The Medicines for Europe copy of
  the Q&A is a scanned image PDF. EMA publishes the estimate, the interval and
  the reference within-subject CV — no SE, df, t statistic or covariance table.
- **nlme / glmmTMB not re-run.** Their agreement on the SE is carried from
  `VAL-FDA-APPENDIX-C-001`, not reproduced here.
- **Synthetic partial-replicate cases not built.** They would have been checked
  against the same single independent implementation.

## `partial_oracle_ready = false`

**The blocking reason, stated narrowly:** we have a strongly supported
candidate df and have excluded ReplicateBE's 22.540 from compatibility with the
published CI under the independently corroborated SE, but **no regulator or SAS
output confirms the denominator-df construction in the rank-deficient
partial-replicate case.**

In more detail:

1. The df rests on **one** independent derivation. It passes a full-replicate
   control and reproduces the published interval — but the brief's bar is
   independent *agreement*, and the only other engine that computes a df
   disagrees.
2. The published two decimals constrain df to `[19.24, 19.98]`. That excludes
   22.540 and contains 19.8906, but does not confirm 19.8906 to the precision
   an implementation would be validated against — and more than one
   construction could land inside the same window.
3. The **mathematical** non-identifiability is established; its **regulatory
   handling** is not.

**Recommendation: `BLOCKED_WITH_PRECISE_REASONS`.**

What would unblock it: a licensed SAS run reporting the df directly — one
number closes this; or a second independent Satterthwaite implementation
agreeing on 19.89; or a regulator statement on reporting when σ²_WT is not
identifiable.
