# VAL-FDA-APPENDIX-C-004

**The denominator df difference against ReplicateBE.jl is a boundary effect,
and appears only at the boundary.**

Raised by PR #62. Closes the question PR #61 left open. **Resolved** —
`COVARIANCE_PARAMETERIZATION_DIFFERENCE`. No computed value changes.

## What that classification means here — and what it does not

It means a **boundary numerical and parameterisation difference between two
implementations of the same regulatory model**, which take the ρ → 1 limit
through different coordinates and so disagree about the last three significant
figures of a Hessian that is singular at that point.

It does **not** mean:

- that FDA's required covariance model differs from what either implementation
  fits;
- that the two implementations are fitting different regulatory models;
- anything at all about the **positive-correlation interior domain**, where the
  two agree to 1e-6 on all five covariance parameters and are demonstrably
  fitting the same model.

This needs saying because the label is shared with
[VAL-FDA-APPENDIX-C-003](VAL-FDA-APPENDIX-C-003.md), where the difference *is*
structural — the oracle cannot represent part of FDA's model at all. Here it is
numerical, in a region both implementations can represent. Same label,
materially different severity.

## The open question

On EMA Data set I, `be-stats` gives a denominator df of **207.7350** and
ReplicateBE.jl gives **208.0811** — a difference of 0.35, or 0.17%. Every other
quantity agreed to six decimals.

PR #61's hypothesis was that Data set I sits exactly on the correlation
boundary (ρ = 1.000) and the two implementations parameterise that limit
differently. It could not be confirmed, because one dataset cannot tell a
boundary effect from a general one.

## What was ruled out first

The Satterthwaite df needs the Hessian of the REML objective. An early version
obtained it by **second differences of the objective**, which divides by `h²`
and loses most of its significant figures — an obvious suspect for a 0.17%
error.

It was replaced with central differences of an **analytic gradient**, with
closed-form `dV/dθ`. **The df did not move.** So the difference is not
differencing error, and the hypothesis survived its first real test by not
being explained away.

## The evidence

Nine synthetic full-replicate cases, eight at interior optima and one built to
land on the correlation boundary.

| | fitted ρ | be-stats df | ReplicateBE df | Δ |
|---|---|---|---|---|
| interior cases A, C, F, G, H, I | 0.38–0.42 | *n* − 2 exactly | same | **< 1e-3** |
| boundary case E | 1.000000 | 111.3107 | 111.6010 | **−0.2903** |
| **EMA Data set I** | 1.000000 | 207.7350 | 208.0811 | **−0.3461** |

Same sign, same order of magnitude, same condition. The synthetic boundary case
reproduces the real one, and every interior case agrees to four decimal places.

**The difference appears at the boundary and only at the boundary.** The
hypothesis is confirmed.

*(Cases B and D are excluded for an unrelated reason — see
[VAL-FDA-APPENDIX-C-003](VAL-FDA-APPENDIX-C-003.md) — and are not counted
either way.)*

## Mechanism

**`be-stats`**: `G = LL'` with `θ = (l₁₁, l₂₁, l₂₂, log σ²_WT, log σ²_WR)`.
ρ = 1 is `l₂₂ = 0`, an *ordinary interior point* of ℝ⁵. The optimiser reaches
it unaided — `l₂₂ = 2.7 × 10⁻⁷` on Data set I — and no bound is applied. The
REML Hessian is near-singular there, so `satterthwaite_df` uses a
pseudo-inverse.

**ReplicateBE**: CSH coordinates with the correlation behind a link. ρ = 1
sends its parameter to infinity.

Two different delicate limits of the same quantity, approached from opposite
directions. Neither is wrong, and both are fitting FDA's model; they disagree
about the last three significant figures of a Hessian that is singular at the
point in question.

## Why the tolerance is stated in df, not in percent

df matters only through the *t* quantile it selects, and the same absolute
difference means very different things at 22 df and at 208.

    t(0.95, 207.7350) = 1.652263
    t(0.95, 208.0811) = 1.652259

A relative difference of 2.6 × 10⁻⁶, moving the 90% interval by under 10⁻⁴
percentage points. The test asserts that **consequence** as well as the
difference: the two quantiles must agree to 1e-3 relative, bounding the effect
on a confidence limit well under the 0.01 percentage points the comparison gate
allows.

## What is still not established

**Which implementation is closer to SAS at the boundary — `NOT DETERMINED`.**

EMA published Data set I's interval to two decimals and both implementations
reproduce it: 107.10 and 124.89 either way. The difference is four orders of
magnitude below the published precision, so the published output cannot
discriminate — and does not need to. Settling it would need a SAS run
reporting the df directly, the same shortest path
[VAL-FDA-APPENDIX-C-001](VAL-FDA-APPENDIX-C-001.md) identifies.

## Consequence

Accepted and bounded. **The boundary is not an edge case to be avoided**: the
only regulator-published Appendix C result available sits on it, so an
implementation that refused boundary solutions would refuse the one dataset
that validates it.
