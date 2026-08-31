# VAL-FDA-APPENDIX-C-PARTIAL-001

**The partial-replicate denominator df is about 19.89, not 22.540 — and FDA's
Appendix C model is not fully identifiable on a partial replicate design.**

Raised by PR #63. **Resolved** — `PACKAGE_SCOPE_LIMITATION`. No production code
was touched; `FDA_REPLICATE_STANDARD_ABE_PARTIAL` remains `NOT_IMPLEMENTED`.

## The answer

| source | −2logREML | estimate | SE | df | reproduces published CI |
|---|---|---|---|---|---|
| independent, **observed** information | −151.974445 | 102.26440% | 0.0303172 | **19.8906** | **yes — 97.05, 107.76** |
| independent, expected information | −151.974445 | 102.26440% | 0.0303172 | 21.5425 | no — 97.07, 107.73 |
| ReplicateBE.jl 1.0.15 | −151.974445 | 102.26439% | 0.0303172 | 22.5403 | no — 97.08, 107.72 |

**22.540 is refuted. 19.603 was the right region for the wrong reason.**

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

For ReplicateBE's df to be right, **its own standard error would have to be
wrong by more than half a percent** — a quantity that nlme, glmmTMB,
ReplicateBE and the implementation built for this PR all reproduce to seven
significant figures. That is the sense in which 22.540 is refuted rather than
merely disagreed with.

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

**Not claimed:** the exact line responsible for 22.540 was not isolated. The
evidence that it is wrong is external.

## The structural finding

> In a partial replicate design each subject contributes **one** test
> measurement, so **σ²_BT and σ²_WT are exactly non-identifiable**. Only their
> sum is estimable.

Three independent confirmations:

- The observed information has **rank 4 of 5**. Its null eigenvector is
  `(+0.707, 0, 0, −0.707, 0)` — exactly the σ²_BT − σ²_WT direction.
- The two engines report materially different splits — 0.070494 / 0.0000006
  against 0.061604 / 0.008890 — while their **sums agree to five decimals**:
  0.0704946 against 0.0704941.
- **EMA publishes a within-subject CV for the reference on Data set II and none
  for the test.** The gap in the regulator's own table is the same fact.

**The decision is still well defined.** The contrast depends only on the
identified sum; the gradient of `Var(L'β)` has equal components on σ²_BT and
σ²_WT and is therefore orthogonal to the null direction. The df is stable at
19.8906 across eight orders of magnitude of pseudo-inverse cutoff.

**But a future implementation must not report what it cannot identify.** Two
correct implementations will disagree about σ²_BT and σ²_WT while agreeing
about every decision quantity, so a production partial-replicate result must
decline to report a within-subject CV for the test product — exactly as EMA's
own table does.

## Boundary handling, confirmed by a second route

Data set I is the control and sits on the PSD boundary at ρ = 1.

| | df | reproduces published CI |
|---|---|---|
| unconstrained, five free parameters | 75.0801 | no |
| **boundary-reduced, four free parameters** | **207.7269** | **yes** |
| be-stats production (Cholesky) | 207.7350 | yes |

Counting five free parameters at a boundary solution understates the df by a
factor of nearly three. Production reaches the right answer through a Cholesky
parameterisation in which the boundary is an interior point; this
implementation reaches it by imposing the rank-1 constraint explicitly. Two
different routes, same number.

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

Not because the answer is unknown, but because of how much stands behind it:

1. The df rests on **one** independent derivation. It passes a control,
   reproduces the published interval and refutes the alternative — but the
   brief's bar is independent *agreement*, and the only other engine that
   computes a df disagrees.
2. The published two decimals constrain df to `[19.24, 19.98]`. That excludes
   22.540 and contains 19.8906, but does not confirm 19.8906 to the precision
   an implementation would be validated against.
3. The non-identifiability of σ²_WT is a **new and material constraint** on
   what a production implementation may report, and no regulator text has been
   found stating how Appendix C applies to a design that cannot identify one of
   its five parameters.

**Recommendation: `BLOCKED_WITH_PRECISE_REASONS`.**

What would unblock it: a licensed SAS run reporting the df directly — one
number closes this; or a second independent Satterthwaite implementation
agreeing on 19.89; or a regulator statement on reporting when σ²_WT is not
identifiable.
