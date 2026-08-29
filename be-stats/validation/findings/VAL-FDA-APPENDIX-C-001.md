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

## Verdict

See `VAL-FDA-APPENDIX-C-001.json` for the machine-readable record and
`appendix_c_investigation.json` (CI artifact) for the fitted numbers.
