# VAL-FDA-APPENDIX-C-002

**ReplicateBE.jl reproduces SAS Method C exactly on the fully replicate design
and not on the partial replicate one.**

| | |
|---|---|
| Raised | PR #61, testing the ReplicateBE.jl Satterthwaite claim |
| Status | `OPEN` |
| Classification | `DF_METHOD_DIFFERENCE` |
| Method | `fda_replicate_standard_abe` |
| Effect on `be-stats` | none — Appendix C is `NOT_IMPLEMENTED` and stays so |

## What was observed

Both EMA data sets, same script, same pinned oracle, same published targets.

### Data set I — 2×2×4 fully replicate, 77 subjects, 8 incomplete

| quantity | EMA published (SAS 9.1) | ReplicateBE.jl 1.0.15 | difference |
|---|---:|---:|---:|
| point estimate | 115.66 | 115.65765 | −0.0024 |
| 90% CI lower | 107.10 | **107.10447** | +0.0045 |
| 90% CI upper | 124.89 | **124.89387** | +0.0039 |
| within-subject CV%, reference | 47.3 | **47.33** | +0.03 |
| within-subject CV%, test | 35.3 | **35.29** | −0.01 |
| denominator df | *not published* | 208.081 | — |
| standard error | *not published* | 0.046501 | — |

**Every published quantity reproduces at the precision EMA printed it.** The CI
is the load-bearing one: it is a function of the estimate, the SE *and* the df,
so matching it to two decimals means the df matches too. That is the
Satterthwaite denominator df — the quantity with no other oracle — confirmed
indirectly but tightly.

### Data set II — 2×3×3 partial replicate, 24 subjects, balanced

| quantity | EMA published (SAS 9.1) | ReplicateBE.jl 1.0.15 | difference |
|---|---:|---:|---:|
| point estimate | 102.26 | 102.26439 | +0.0044 |
| 90% CI lower | 97.05 | 97.08212 | **+0.0321** |
| 90% CI upper | 107.76 | 107.72329 | **−0.0367** |
| within-subject CV%, reference | 11.5 | **11.55** | +0.05 |
| denominator df | *not published* | 22.540 | — |
| df implied by the published CI | 19.603 | | **−2.937** |

The estimate and the covariance parameters match. **The interval does not**:
it is narrower than published by about 0.035 percentage points at each end,
roughly seven times the ±0.005 rounding bound.

The whole difference is in the df. With `SE = 0.030317` — a value **three
independent implementations agree on exactly**, nlme, glmmTMB and
ReplicateBE.jl — the published interval requires `t = 1.72643`, i.e.
`df ≈ 19.60`. ReplicateBE reports `22.540`.

## The explanation is in the package's own stated scope

ReplicateBE.jl's validation claim, quoted:

> Satterthwaite degree of freedom (DF) estimate is equal with SAS/SPSS DF
> estimate for **full-replicated** basic bioequivalence balanced and unbalanced
> datasets (**2x2x4, 2x2x3**)

Both named designs are **two-sequence** designs. Data set I is 2×2×4 and is
covered. Data set II is a **three-sequence partial replicate** (`TRR`/`RTR`/
`RRT`) and is **not** covered.

So the observed pattern is exactly what the package claims: it agrees with SAS
where it says it does, and diverges where it never said it would. That is a
scope limitation honestly stated by its author, not a defect discovered here.

## What is NOT established

**Which of the two is right on the partial replicate.** `NOT_DETERMINED`, and
deliberately so:

- Three implementations agree the SE is 0.030317, which makes `df ≈ 19.60` the
  value consistent with SAS's published interval.
- But all three could share a difference from SAS that only shows up in this
  design.
- Resolving it needs a SAS run, which is the same thing
  `VAL-FDA-APPENDIX-C-001` already identifies as the shortest path.

**Nothing was tuned toward 19.60**, and nothing should be. The recovered value
is a diagnostic; SAS's actual df for this design remains unpublished.

## One more thing worth recording

On Data set I the fitted subject-by-formulation correlation is **exactly
1.000** — a boundary solution. `σ²_D = σ²_BT + σ²_BR − 2ρ√(σ²_BT σ²_BR)`
collapses to `(√σ²_BT − √σ²_BR)²` there, i.e. no subject-by-formulation
interaction beyond a scale difference.

SAS's `FA0(2)` is likewise constrained to the positive semi-definite boundary
and would reach the same edge. It matters for a future Python implementation:
**the optimum for real data can sit on the boundary of the parameter space**,
and an implementation that assumes an interior optimum — or that inverts a
Hessian without checking — will fail on exactly the data set that otherwise
validates it.

## Consequence

The oracle is **verified for fully replicate (2×2×4) and unverified for partial
replicate (2×3×3)**. Since FDA HVD supports both designs, that is not enough to
implement Appendix C against — see `VAL-FDA-APPENDIX-C-001`, which stays
`BLOCKED_WITH_PRECISE_REASONS` with this as one of the reasons.
