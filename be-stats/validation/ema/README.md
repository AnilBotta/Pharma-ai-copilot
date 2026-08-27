# EMA highly variable drugs — tier 1B

This is the first method in the package with **tier 1B** evidence: a regulator's
own worked example, with raw data and published results, reproduced.

## What the regulator published

**EMA/618604/2008 Rev. 13**, *Questions & Answers: Positions on specific
questions addressed to the Pharmacokinetics Working Party*, in the section on
analysing replicate-design bioequivalence studies, compares three models on two
data sets and prints the results. The annex contains the raw data for both.

`cases/ema_pkwp_qa_datasets.json` is that annex, transcribed. Every row carries
the value, the log value the document printed, the formulation, the period and
the sequence; `log(DATA)` and the printed `logDATA` agree to 5e-7, which is the
rounding the document itself applied.

| | Data set I | Data set II |
|---|---|---|
| design | 4-period fully replicate (`ABAB`/`BABA`) | 3-period partial replicate (1/2/3) |
| subjects | 77, **8 with missing periods** | 24, all complete |
| observations | 298 | 72 |
| Method A point estimate | 115.66 | 102.26 |
| Method A 90% CI | 107.11, 124.89 | 97.32, 107.46 |
| reference CV% (Model A/B) | 47.0% | 11.2% |
| reference CV% (Model C) | 47.3% | 11.5% |

Sequence coding differs between the two, and both are transcribed as printed:
Data set I uses letters where `A` is the **test** and `B` the reference, so
`ABAB` is `TRTR`; Data set II uses `1` = `TRR`, `2` = `RTR`, `3` = `RRT`.

## The limits table

Section 4.1.10 of the guideline prints its own table of widened limits, which
is a second, independent piece of tier-1B evidence:

| Within-subject CV (%) | Lower | Upper |
|---:|---:|---:|
| 30 | 80.00 | 125.00 |
| 35 | 77.23 | 129.48 |
| 40 | 74.62 | 134.02 |
| 45 | 72.15 | 138.59 |
| ≥50 | 69.84 | 143.19 |

All five rows reproduce to the two decimals published.

## Why this matters more than another PowerTOST case

Tier 3 shows that an independent implementation computes the same number. Tier
1B shows that the number is the one the **regulator** published. PR #59 is the
standing reminder of the difference: an oracle can be driven with the wrong
component definition and agree with itself all day.

For EMA, the tier-1B evidence is also what settles a question tier 3 could not
have. `ReplicateDataset` excludes subjects missing a reference replicate,
because FDA's sWR needs both. Data set I contains eight incomplete subjects,
and EMA's published result can only be reproduced by **keeping** them — which
is how the difference between FDA's inclusion rule and EMA's stopped being a
matter of opinion.

## What is still not established

- **The cap reading.** The guideline states the maximum as the pair
  69.84 – 143.19%; the formula at CVwR = 50% gives 69.83678 – 143.19102. The
  stated pair is applied. See `validation/findings/VAL-EMA-ABEL-002.md`.
- **Tier 3 for the whole procedure.** PowerTOST's `scABEL` is a deterministic
  check of the limits; its power functions report a quantity that is not the
  one it appears to be. See `validation/findings/VAL-EMA-ABEL-001.md`.
