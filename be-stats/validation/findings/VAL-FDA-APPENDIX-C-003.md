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

## This is an oracle domain limitation, not a `be-stats` defect

No production number changed as a result of this finding, and none should.

## The three models, stated separately

| | negative subject-by-formulation covariance |
|---|---|
| **FDA Appendix C** | **permitted.** `TYPE=FA0(2)` is `G = LL'` with `L = [[l₁₁, 0], [l₂₁, l₂₂]]`, so `σ_BTBR = l₁₁·l₂₁` and **`l₂₁` is unconstrained in sign** — as it also is under the `CSH` and `UNR` alternatives FDA names |
| **be-stats** | **can fit it.** Implements that parameterisation directly; does so on cases B and D |
| **ReplicateBE.jl 1.0.15** | **cannot represent it.** The correlation sits behind `rholink = :psigmoid`, whose range excludes negative values |

Those two oracle values are not small numbers. They are **zero as a link
function can express it**: reaching zero requires sending the link's parameter
to −∞, and 1e-14 is what the optimiser returns when it tries. Two unrelated
datasets landing fourteen orders of magnitude below every other case is a
parameter running to its limit.

So in this region **the two implementations are not fitting the same model** —
the oracle is fitting a constrained one. Its disagreement is uninformative
about `be-stats`, and it must not be treated as an adjudicating oracle there.

This says nothing about the positive-correlation domain, where the two agree
to 1e-6 on all five covariance parameters and are demonstrably fitting the same
regulatory model.

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

**Case D: `independent_oracle_status = ADJUDICATED`** — be-stats supported.

This is an **independent algebraic / structural cross-check**, sharing no code
with the REML implementation. It is explicitly **not tier 1A**, which in this
package means conformance to a *regulator's* stated algorithm or decision rule.
No regulator states this identity; it is a property of the model that happens
to be true and happens to be checkable.

## Case B: `independent_oracle_status = UNRESOLVED`

Case B is **incomplete**, so the balanced-data identity does not reach it, and
ReplicateBE cannot represent its negative correlation. **No independent check
on this fit exists anywhere in this project.**

It is held out of the tier-3 gate for the same structural reason as case D and
supported by **none** of the same evidence. It is **not** claimed to be
externally validated, and it is **not** treated as a pass — it is a standing
validation limitation.

Resolving it needs an oracle whose covariance parameterisation admits negative
subject-by-formulation correlation *and* which handles available-case missing
data — or a SAS PROC MIXED run on this dataset.

`test_case_b_has_no_independent_oracle_and_is_not_claimed_to` asserts the three
facts that make it unresolved, so a future change satisfying any of them
surfaces as a failure prompting this finding to be revisited, rather than
passing unnoticed.

## What was not done

**No tolerance was loosened.** The gate is unchanged at 0.01 percentage points
on each confidence limit. Admitting B and D would have needed roughly 0.6
percentage points — wide enough to admit a genuine defect as well.

**No case was dropped for disagreeing.** The criterion is a conjunction of two
*measured* properties — `be-stats` ρ clearly below zero **and** the oracle's ρ
collapsed below its link's limit — and a test asserts that exactly the cases
meeting it fall outside the gate. A case where the oracle merely fitted a small
positive correlation would still be compared.

**No case was deleted.** Both remain in the suite, both are still fitted by the
oracle in every CI run, and both are still reported.

**The criterion is reversible.** If a future ReplicateBE release reported a
negative ρ, these two cases would re-enter the gate automatically.

## Consequence

ReplicateBE.jl is a tier-3 implementation oracle **within the covariance domain
it can represent**: fully replicate designs whose fitted subject-by-formulation
correlation is non-negative. That covers EMA Data set I — the regulator-published
case — and seven of the nine synthetic ones, and there the live comparison
**gates**.

It does not cover negative-correlation fits. There it is structurally fitting a
different, constrained model, and is neither an oracle nor evidence of a defect.
Those fits rest on the algebraic identity where it applies (case D) and are
recorded as **UNRESOLVED** where it does not (case B).

Related: [VAL-FDA-APPENDIX-C-002](VAL-FDA-APPENDIX-C-002.md),
[VAL-FDA-APPENDIX-C-004](VAL-FDA-APPENDIX-C-004.md).
