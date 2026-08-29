# VAL-FDA-APPENDIX-C-001

**Is there a trustworthy numerical oracle for FDA Appendix C?**

| | |
|---|---|
| Raised | PR #61, as the feasibility question itself |
| Status | see **Verdict** below |
| Method | `fda_replicate_standard_abe` |
| Implementation status | `NOT_IMPLEMENTED` — unchanged by this investigation |

This is not a discrepancy report. It is the record of an investigation run
*before* writing an implementation, on the principle PR #60 established: the
regulator's exact model is worth implementing only once there is evidence
capable of detecting a plausible-but-wrong version of it.

## The model, from the source

FDA, *Statistical Approaches to Establishing Bioequivalence*, May 2026,
Appendix C:

```sas
PROC MIXED;
CLASSES SEQ SUBJ PER TRT;
MODEL Y = SEQ PER TRT/ DDFM=SATTERTH;
RANDOM TRT/TYPE=FA0(2) SUB=SUBJ G;
REPEATED/GRP=TRT SUB=SUBJ;
ESTIMATE 'T vs. R' TRT 1 -1/CL ALPHA=0.1;
```

Two sentences in the same appendix bear directly on this investigation:

> In the Random statement, TYPE=FA0(2) could possibly be replaced by TYPE=CSH
> or UNR. In the Model statement, DDFM=SATTERTH could possibly be replaced by
> DDFM=KR2.

> Alternative software could also be used if same results are generated as in
> PROC MIXED in SAS.

The second is the licence for an external oracle **and its burden**: "same
results" is the bar, not "a similar model".

## The five covariance parameters, named

`TYPE=FA0(2)` is a factor-analytic structure with no diagonal addition:
`G = LL'` with `L` lower-triangular 2×2, so

```
L = [[l11,   0  ],        G = [[l11²,      l11·l21      ],
     [l21,  l22]]              [l11·l21,   l21² + l22²  ]]
```

Three free parameters spanning every symmetric 2×2 — but **positive
semi-definite by construction**. That is why FDA writes `FA0(2)` rather than
`UN`: `UN` lets an optimiser reach a non-positive-definite estimate and
`FA0(2)` cannot. The alternatives FDA permits, `CSH` and `UNR`, are likewise
constrained, which is consistent with the constraint being the point.

| parameter | meaning | source |
|---|---|---|
| `σ²_BT` | between-subject variance, **test** | `G[1,1] = l11²` |
| `σ²_BR` | between-subject variance, **reference** | `G[2,2] = l21² + l22²` |
| `σ_BTBR` | between-subject covariance of T and R | `G[1,2] = l11·l21` |
| `σ²_WT` | within-subject residual variance, **test** | `REPEATED/GRP=TRT` |
| `σ²_WR` | within-subject residual variance, **reference** | `REPEATED/GRP=TRT` |

Ordering follows Appendix C's own note that the `ESTIMATE` coefficients depend
on sort order, with the test code first.

The subject-by-formulation interaction is **not a sixth parameter**:

```
σ²_D = σ²_BT + σ²_BR − 2·σ_BTBR
```

EMA puts the same point in words — "the last three are combined to give the
subject × formulation interaction variance component".

## Missing data — answered by the guidance, not inferred

FDA section III, on missing data:

> a complete case analysis could be a general linear model as implemented in
> SAS PROC GLM, which removes all subjects with any missing observations …
> An available case analysis could be done using SAS PROC MIXED, **which uses
> all observed data**

So Appendix C is an **available case** analysis. Its inclusion rule is
therefore neither of the two already in this package, and is the most
permissive of the three:

| model | inclusion rule |
|---|---|
| FDA Appendix G (`sWR`) | needs **both** reference replicates; subject excluded otherwise |
| EMA Method A | all observed rows; incomplete subjects retained |
| **FDA Appendix C** | **all observed data** — available case |

The guidance adds that the approach "should be prespecified in the study
protocol or SAP", so this is a default, not a licence to choose after seeing
the data.

## Is there a published FDA worked dataset?

**No.** The May 2026 guidance publishes no numerical example for Appendix C —
consistent with tier 1B having been `PENDING` for every FDA method in this
package since PR #53.

**But there is published SAS output for this exact model**, from a different
regulator. EMA/618604/2008 Rev. 13 calls it **"Method C"** and attributes it to
the FDA guidance by name, transcribing the same `PROC MIXED` block. Its §3.3
records that "SAS (version 9.1, SAS Institute Inc., NC) was used in the
previous computations."

| | Data set I | Data set II |
|---|---|---|
| design | 4-period fully replicate, 77 subjects, 8 incomplete | 3-period partial replicate, 24 subjects |
| point estimate | 115.66 | 102.26 |
| 90% CI | 107.10, 124.89 | 97.05, 107.76 |
| within-subject CV%, reference | 47.3 | 11.5 |
| within-subject CV%, test | 35.3 | — |

Raw data is in the same annex and is already in this repository from PR #60
(`validation/ema/cases/ema_pkwp_qa_datasets.json`).

**What is *not* published: the standard error and the denominator degrees of
freedom.** That gap is the central difficulty of this whole investigation.

### How this evidence should be graded

It is a regulator-published worked example **of the FDA model**, published by
**EMA**. That is stronger than a peer-reviewed dataset and weaker than an
FDA-published example of FDA's own model. It is recorded as tier 1B with the
publishing authority named, never as "FDA published this".

## SAS feasibility

| route | verdict |
|---|---|
| **SAS OnDemand for Academics** | **Not appropriate.** Its licence prohibits commercial use, and work intended to support a regulatory submission is commercial. Ruled out on licence, not on capability. |
| A licensed SAS environment | Unknown — an organisational question, not a technical one. If one exists it could settle this investigation outright. |
| **Published SAS output** | **Available**, as above: SAS 9.1 PROC MIXED output for this model, on two datasets with published raw data. Partial — no SE, no df. |

No route may become a runtime dependency of `be-stats`, and none is proposed as
one.

## Recovering the unpublished df

EMA publishes the point estimate and the 90% CI but not the SE or the df. Given
a candidate implementation's SE, the df SAS must have used is recoverable:

```
half_width = t(0.95, df) · SE     ⟹     t = half_width / SE     ⟹     df
```

This is a **diagnostic, not a validated df**. It is worth exactly as much as
the candidate's SE: if that is wrong, the recovered df is meaningless. Its
value is asymmetric —

- an implausible answer (negative, or far outside `[n_subjects, n_obs]`, or no
  root at all) is **evidence the candidate's SE disagrees with SAS**;
- a plausible answer is **weak corroboration** that the SE and the df both line
  up.

It is the only lever available against an unpublished quantity, and it is
labelled as such everywhere it appears.

## The R candidates, fitted rather than assessed on paper

Four requirements. A package is not an oracle unless all four hold.

| package | 1 fixed | 2 G matrix | 3 R matrix | 4 Satterthwaite df | verdict |
|---|:--:|:--:|:--:|:--:|---|
| **nlme** 3.1.168 | ✅ | ✅ | ✅ | ❌ containment | **partial oracle** |
| **glmmTMB** 1.1.12 | ✅ | ✅ | ✅ | ❌ Wald *z* | **partial oracle** |
| lme4 1.1.37 + lmerTest 3.1.3 | ✅ | ✅ | ❌ one residual | ✅ | not an oracle |
| mmrm | ✅ | ❌ marginal only | ⚠️ | ✅ | not an oracle |

`mmrm` is the one judged from its documented design rather than by fitting: it
is a marginal model with no G side, and Appendix C's marginal covariance is a
*patterned* five-parameter matrix whose pattern differs by sequence. `mmrm`'s
structures are indexed by visit and would give an unpatterned ten-parameter
4×4 — a richer and different model.

`replicateBE`, the established R package for replicate bioequivalence,
implements EMA Methods A and B and **not** Method C, despite already depending
on `nlme` and `lmerTest`. That the leading R package in this exact domain stops
short of the FDA model is evidence about the ecosystem, not about anyone's
effort.

### The estimate and the SE have an oracle

| | published | nlme | glmmTMB |
|---|---:|---:|---:|
| Data set I estimate | 115.66 | 115.6588 | 115.6577 |
| Data set I SE | — | 0.046633 | 0.046507 |
| Data set II estimate | 102.26 | 102.2644 | 102.2644 |
| Data set II SE | — | 0.030317 | 0.030317 |

Two independent implementations — different languages, different optimisers —
reproduce EMA's published estimate to within **0.003 percentage points** on
both data sets, and agree with each other on the SE **exactly** on the balanced
data set and to **0.27%** on the unbalanced one.

### lme4 demonstrates the limitation rather than being accused of it

On the unbalanced Data set I, lme4's estimate is **115.7958** — off by
**0.136 percentage points**, with a singular fit — where nlme and glmmTMB land
within 0.002. That is the single-residual-variance restriction showing up as a
number, and it is exactly the size of error a plausible-but-wrong
implementation would produce.

### Satterthwaite df is the blocker

| | recovered df | package's own df | conditioning |
|---|---:|---:|---|
| Data set II (nlme SE) | **19.603** | 45 (containment) | well conditioned |
| Data set II (glmmTMB SE) | **19.603** | ∞ (Wald) | well conditioned |
| Data set II (lme4 SE) | 20.663 | — | well conditioned |
| Data set I (nlme SE) | 544 — **impossible** | 217 | ill conditioned, ±760 df per 0.1% of SE |

nlme and glmmTMB give the *same* SE on Data set II and therefore imply the
*same* SAS df of 19.60. lme4 — already known to fit the wrong structure —
implies 20.66. So the recovered df does not rest on one package's arithmetic,
and the one package that disagrees is the one that should.

**No R candidate produces Satterthwaite df for this model.** nlme reports
containment (45), glmmTMB reports none at all.

### lmerTest is the sharpest result in the investigation

lmerTest *does* compute a genuine Satterthwaite df. On Data set II it returns
**35.94**, against SAS's implied **19.60** — a factor of **1.83**.

`t(35.94) = 1.6890` against `t(19.60) = 1.7264` is a **2.2% narrower**
half-width. On a borderline study that is a different BE decision.

This is the failure mode the whole investigation exists to guard against. The
Satterthwaite implementation is correct; it is applied to a covariance
structure that is not Appendix C, and the result is a df that looks
principled, carries the right label, and is wrong by nearly a factor of two.
**An oracle cannot be accepted on the strength of the word "Satterthwaite" —
only on the strength of the model it is computed for.**

`t(19.6) = 1.7264` against `t(45) = 1.6794` is a **2.8% wider half-width**, and
against Wald's `1.6449` a **4.7%** one. At the boundary that is a different BE
decision.

## ReplicateBE.jl — the last candidate

Julia, GPL-3.0, pinned at **1.0.15** on **Julia 1.10.5**, in the validation
image only. `be-stats` does not depend on Julia and must never; running the
package and comparing numbers creates no derivative work, and none of its code
is copied.

> **1.0.15, not the 1.0.10 the documentation site serves.** 1.0.10 declares
> `DataFrames = "0.19, 0.20"`, which cannot resolve on Julia 1.10 —
> `SortingAlgorithms` forces `DataFrames ≥ 1.0` and the graph is
> unsatisfiable. 1.0.15 declares `DataFrames = "1"`.

### On the appendix numbering

Its documentation cites the FDA guidance by an **older appendix letter**. That
is a labelling difference and is evidence of nothing: the current May 2026
guidance carries this model at Appendix C and earlier editions lettered it
differently. The model was compared **term by term** against the current
Appendix C instead.

### Model equivalence, from source

| component | verdict | evidence |
|---|---|---|
| fixed SEQ + PER + TRT | **IDENTICAL** | sequence, period, formulation |
| subject-by-formulation G | **MATHEMATICALLY EQUIVALENT** | `gmat(σ) = Symmetric([σ₁ cov; cov σ₂])`, `cov = √(σ₁σ₂)·σ₃` |
| treatment-specific residuals | **IDENTICAL** | `rmat(σ, Z) = Diagonal(Z·σ)` |
| parameter count | **IDENTICAL** | five, in different coordinates |
| contrast and level | **IDENTICAL** | T vs R, `confint(level = 0.90)` |

The G matrix uses a **CSH** parameterisation — two variances and a correlation
— where FDA writes `FA0(2)` = `LL'`. Both span exactly the positive
semi-definite 2×2 cone with three free parameters: they differ in coordinates,
not in the model. And FDA **names CSH as an acceptable substitute**, so this is
a permitted parameterisation rather than merely an equivalent one.

### Satterthwaite, from source

`sattdf(data, gradc, A, C, L, lcl)` in `src/generalfunc.jl`:

```
rank 1:  df = 2·(L'CL)² / (∇C' · A · ∇C)
rank ≥2: vm[i] = 2λᵢ² / ((pᵢ'∇C)' A (pᵢ'∇C));  df = 2·Σvm / (Σvm − rank)
```

`A` is the information matrix of the variance parameters and `gradc` holds the
gradient of the contrast variance with respect to each of them. That is the
Satterthwaite construction proper — the same one SAS implements for
`DDFM=SATTERTH` — not a different quantity wearing the name. Boundary handling:
a guard on `vm[i] > 2.0` and a final `max(1, df)` floor.

**Structurally correct on inspection.** Which is exactly why inspection was not
enough: lmerTest also implements Satterthwaite correctly and returns 35.94
where SAS implies 19.60, because it computes it for a structure that is not
Appendix C. A correct formula on the wrong model gives a wrong df that looks
entirely principled. So the numbers were run as well.

## Verdict

**`BLOCKED_WITH_PRECISE_REASONS`.**

Established: the model, the parameterisation, the missing-data rule, two
regulator-published data sets, and a partial oracle for the estimate and the
standard error.

Missing, and each of them blocking:

1. **An independent Satterthwaite df.** No available implementation computes it
   for this covariance structure. One df value is recoverable indirectly, on
   one data set, and that is not a validated df.
2. **A published standard error.** Without it, SE and df cannot be separated —
   the published CI constrains only their product.
3. **Datasets covering the roles tier 3 requires.** Two exist, both broadly
   central. Synthetic cases for the unbalanced, heteroscedastic,
   unequal-subject-variance and near-boundary roles cannot be added, because
   generating their expected values needs the oracle that is missing.

### What would unblock it

- **One PROC MIXED run in a licensed SAS environment** on the two published
  data sets, reporting the SE and the Satterthwaite df. Shortest path; settles
  it outright.
- **Or** adding Julia and `ReplicateBE.jl` to the validation container and
  testing its claim that its "Satterthwaite degree of freedom (DF) estimate is
  equal with SAS/SPSS DF estimate for full-replicated basic bioequivalence
  balanced and unbalanced datasets". That claim is recorded here as a claim; it
  has not been verified. `ReplicateBE.jl` is GPL-3.0, which is fine for use as
  an oracle — running it and comparing numbers creates no derivative work —
  and would be a different question if its code were ever copied.

Either also makes the missing dataset roles reachable, because expected values
could then be generated for them.

See `VAL-FDA-APPENDIX-C-001.json` for the machine-readable record and
`appendix_c_investigation.json` (CI artifact) for the fitted numbers.
