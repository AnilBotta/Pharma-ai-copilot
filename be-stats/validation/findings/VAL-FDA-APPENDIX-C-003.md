# VAL-FDA-APPENDIX-C-003

**ReplicateBE.jl cannot represent a negative subject-by-formulation
correlation, which FDA's `FA0(2)` permits.**

Raised by PR #62, on the first gating run of the nine synthetic full-replicate
cases. **Resolved** — `COVARIANCE_PARAMETERIZATION_DIFFERENCE`. No computed
value in `be-stats` changes.

## What was observed

Seven of the nine cases agree with the oracle to 1e-6 on all five covariance
parameters, on the standard error and on the denominator df. Two do not:

| case | be-stats ρ | ReplicateBE ρ | ΔSE | Δdf |
|---|---|---|---|---|
| B | −0.022567 | 7.0 × 10⁻¹⁴ | +0.94% | −0.47 |
| D | −0.096563 | 2.4 × 10⁻¹⁵ | +3.16% | −1.05 |
| all others | ≥ 0 | agrees to 1e-6 | < 0.01% | < 1e-3 |

The two disagreeing cases are **exactly** the two where this package fits a
negative subject-by-formulation correlation. Nothing else separates them: B is
unbalanced and incomplete, D is balanced and complete.

## Cause

Those two oracle values are not small numbers. They are **zero as a link
function can express it**. ReplicateBE parameterises the correlation through
`rholink = :psigmoid`, whose range excludes negative values, so reaching zero
requires sending its parameter to −∞ — and 1e-14 is what the optimiser returns
when it tries. Two unrelated datasets landing fourteen orders of magnitude
below every other case is a parameter running to its limit.

FDA's model has no such limit. `TYPE=FA0(2)` is `G = LL'` with
`L = [[l₁₁, 0], [l₂₁, l₂₂]]`, so `σ_BTBR = l₁₁·l₂₁` and `l₂₁` is unconstrained
in sign. A negative subject-by-formulation covariance is **inside** the model
FDA specifies — and inside the `CSH` and `UNR` alternatives FDA names as
acceptable substitutes.

The constraint is the oracle's, not the model's.

## How the disagreement was adjudicated

Not by reading ReplicateBE's source, and not by preferring our own answer.

Case D is balanced, complete and interior, so PR #62's identity applies:
Appendix C reduces exactly to the **classical subject-level analysis** — the
one-sample analysis of per-subject (mean log T − mean log R), averaged over
sequences. That route contains no mixed model, no REML, no optimiser, no
covariance structure and no Satterthwaite formula.

| route | standard error |
|---|---|
| classical subject-level | 0.12720778 |
| be-stats | 0.12720778 |
| ReplicateBE.jl | 0.12331506 |

A third route sharing code with neither implementation agrees with `be-stats`
to eight decimal places and differs from the oracle by 3.2%.

Case B is incomplete, so the identity does not apply and no third route exists
for it. Its exclusion rests on the same pinned ρ, and on the pattern holding
across both cases rather than being fitted to one.

## What was not done

**No tolerance was loosened.** The gate is unchanged at 0.01 percentage points
on each confidence limit. Admitting B and D would have needed roughly 0.6
percentage points — wide enough to admit a genuine defect as well.

**No case was dropped for disagreeing.** The exclusion criterion is a
conjunction of two *measured* properties — `be-stats` ρ clearly below zero
**and** the oracle's ρ collapsed below its link's limit — and a test asserts
that exactly the cases meeting it are excluded. A case where the oracle merely
fitted a small positive correlation would still be compared.

**The criterion is reversible.** If a future ReplicateBE release reported a
negative ρ, these two cases would re-enter the comparison automatically.

## Consequence

The oracle is usable for fully replicate designs whose fitted
subject-by-formulation correlation is non-negative. That covers EMA Data set I
— the regulator-published case — and seven of the nine synthetic ones.

It does not cover negative-correlation fits. No oracle available to this
project can check those, and the honest statement is that they rest on the
classical identity where it applies and on nothing else where it does not.

Related: [VAL-FDA-APPENDIX-C-002](VAL-FDA-APPENDIX-C-002.md),
[VAL-FDA-APPENDIX-C-004](VAL-FDA-APPENDIX-C-004.md).
