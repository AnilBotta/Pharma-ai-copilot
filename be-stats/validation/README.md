# Validation

**Status: not validated. This engine must not be used to support a regulatory
submission.** The FDA *algorithm* is attested (tier 1A); no FDA *worked dataset*
has been reproduced (tier 1B), and 1B is what `VALIDATED` requires.

That sentence is the point of this directory. Everything in `tests/` shows the
code computes what the module documentation says it computes. Nothing in
`tests/` shows that what the documentation says is what a regulator expects.
Only an external reference answer can do that.

---

## The precedence of evidence

Agreed at statistical review. Higher tiers outrank lower ones, and a lower tier
never substitutes for a higher one.

| Tier | Source | Authority |
|---|---|---|
| **1A** | Regulator-published **algorithm** — the decision rule, thresholds and branch structure, from FDA final guidance including the NTI and highly-variable appendices | Highest. This is what the method *is* |
| **1B** | Regulator-published **worked dataset** — inputs and the published answer | Highest. This is what the method *produces* |
| 2 | Published textbook or reference table | Independent numerical validation |
| 3 | `PowerTOST` reference output / test fixture | **Implementation oracle only** |
| 4 | Simulations generated here | Supplemental verification only |

**Tier 1 is split because this package holds one half without the other.** An
attested algorithm says the engine branches where the regulator branches. A
reproduced worked dataset says the arithmetic lands where the regulator's
lands. Claiming "tier 1" without the letter would let the first pass for the
second, and only the second licenses a filing.

Current state:

| Evidence | Status |
|---|---|
| FDA regulatory algorithm source (1A) | **VERIFIED** — attested at statistical review with section references |
| FDA numeric worked dataset (1B) | **PENDING** — the guidance body has not been obtainable |
| Independent numeric cross-check (tier 3) | **PASSED** — two published `PowerTOST` cases |

`VALIDATED` requires 1B. Nothing here may support a submission.

### What "VERIFIED, via statistical review" means, and does not

This tooling could not retrieve the FDA guidance PDF — every URL tried returned
404 or served a download rather than readable text. The FDA constants and the
highly-variable decision rule were therefore supplied at statistical review
**together with their section references**, and `RegulatoryValue.verified_by`
records that chain of custody on every one of them.

A figure read from the primary document and a figure relayed by a qualified
reviewer are both `VERIFIED`, and an auditor is entitled to know which. That is
the entire reason the field exists. Obtaining the document and re-checking each
constant against it remains an open item.

**PowerTOST is not the regulatory authority.** It is an independent
implementation to cross-check against. Its usefulness is partly that its own
validation traces back to published tables — its `ct5.1` fixture corresponds to
the classical 2×2 crossover at 80–125% by exact calculation, derived from
Hauschke, Steinijans & Pigeot, and its `/tests` scripts exist to be compared
against those tables. That makes it an excellent tier-3 oracle and still not a
tier-1 source.

---

## Where the cases live

`validation/phase1/cases/*.json` — **numeric** cases: a scenario, an expected
number, a tolerance, a source. Run by
`tests/validation/test_golden_cases.py`.

`validation/phase1/algorithm/*.json` — **algorithm-conformance** cases: a stated
rule, the branches it must produce, and what it must refuse. Run by
`tests/validation/test_algorithm_conformance.py`.

JSON rather than Python in both directories, so the same file can drive the R
cross-check without being transcribed. Transcription is where golden values go
wrong.

The numeric directory is seeded with **tier 3 only**: two published `PowerTOST`
cases.
`test_golden_cases.py::test_tier_1b_numerical_coverage_is_absent_and_says_so`
fails the moment a tier-1B case is added, as a prompt to raise the validation
statuses in the same commit.

The algorithm directory holds one **tier 1A** case, `FDA-HVD-SWITCH-001`: the
FDA highly-variable method-selection rule, checked at 0.2939 / 0.2940 / 0.2941
and at the point where a derived threshold would disagree with the guidance
figure. A case file there must state how it was verified and what its evidence
does *not* cover; a case with no registered engine entry point fails, because a
case nobody runs is documentation rather than validation.

Measured on those two cases, and the basis for the stated tolerances:

| case | published | be-stats | delta |
|---|---|---|---|
| CV 0.20, ratio 0.95, 2x2, 80% | n=20, power 0.834680 | n=20, 0.834680 | 1.9e-07 |
| CV 12.5%, ratio 0.975, 90-111.11 | n=32, power 0.800218 | n=32, 0.800212 | 6.0e-06 |

Sample sizes agree exactly; the power deltas are this package's non-central t
approximation against PowerTOST's exact Owen's Q. The tolerance was set from
these measurements, not chosen beforehand.

---

## A golden value is a scenario, not a number

No expected value enters the executable suite until every one of these is
recorded with it. A sample size is meaningless without them, and two tools
"disagreeing" is nearly always two different scenarios.

```
design                  2x2 | parallel | replicate
CVw                     within-subject coefficient of variation
theta0                  assumed true T/R ratio
lower, upper            acceptance limits
alpha                   0.05
target_power
method                  exact TOST | non-central t | shifted normal
n_reported_as           total subjects | per sequence
minimum_subject_rule    applied or not
expected_n              the published answer
source                  the citation
```

Only then does `expected_n` become a golden value.

---

## Three claims retracted

**1. The sample-size table.** An earlier note here recorded that this engine
produces 8, 12, 20, 28, 40, 66 for CV 10–40% at ratio 0.95 and 80% power, and
observed that this "appears to agree" with the classical published tables. The
observation stands; its status does not. It was a comparison against
recollection, and it is retained only as an expectation for whoever performs
the tier-2 check — not as evidence, and not in any test.

**2. "EMA NTI at 15% CV requires 96 subjects."** This was stated in a pull
request summary as though it were a fact about the regulation. **It was not
defensible and is withdrawn.** It was an engine output under one unrecorded
scenario, and sample size is acutely sensitive to the assumed ratio, the power
target, the method, and whether the figure is total or per sequence.

For contrast, a published `PowerTOST` example for narrowed 90–111.11% limits at
CV 12.5%, assumed ratio 0.975, 80% power and a 2×2 design gives 32 subjects.
That does not make the earlier number wrong — it makes it *unqualified*, which
for this purpose is the same problem. The direction is the only part now
asserted in the suite: narrower limits cost subjects.

**3. "The HVD switching threshold is derived, and that is not cosmetic."** An
earlier section of this file argued that FDA's published `0.294` was
`cv_to_log_sd(0.30) = 0.293560` rounded, that the package should therefore
prefer the exact derivation, and that an AST-level test should prevent `0.294`
from being reintroduced as a numeric literal. **The reasoning was wrong and the
guard has been deleted.**

The arithmetic was correct. `sqrt(ln(1 + 0.30^2))` really is 0.293560, and the
difference from 0.294 really does decide the method for studies whose estimated
sWR falls in between. What was wrong was the conclusion drawn from it. FDA's
guidance states **two different things** that happen to sit 0.0005 apart:

| | question | quantity | when |
|---|---|---|---|
| `CV ≥ 30%` | is this drug *classified* highly variable? | assumed population CV | before the study |
| `sWR ≥ 0.294` | which *analysis* applies? | the estimated sWR | after the study |

`0.294` is not a rounded presentation of the first. It is the regulator's own
criterion for the second. Deriving it would have replaced FDA's rule with the
package's arithmetic — which is precisely the failure this codebase is
organised to avoid, arrived at from the opposite direction. A test forbidding
the regulator's number from appearing in the source was, in effect, a test
requiring the substitution.

Both values are now separate `RegulatoryValue`s in `spec.py` with separate
citations — III.C for the classification CV, Appendix G for the switching
threshold — and `conversions.py` exports no constants at all. The facts are
asserted in `tests/integration/test_fda_hvd_thresholds.py` and in the tier-1A
case above, including the row at sWR = 0.2937 that the earlier version would
have misrouted.

---

## Mathematical versus regulatory sample size

These are different kinds of statement and the engine keeps them apart:

```
mathematical_n   what the power calculation requires
regulatory_n     what the regulator requires regardless
recommended_n    max of the two, rounded up to an even total
```

FDA general PK BE guidance: not fewer than **12** evaluable subjects in a PK BE
study, and at least **24** for a highly variable drug product.

ICH M13A Q&A 2.1: **12 evaluable subjects for a crossover**, and **12 per
treatment group for a parallel design** — 12 and 24 respectively.

**The registry is keyed on (jurisdiction, framework, design family), never on
jurisdiction alone.** Two separate leaks are being prevented:

- *by design* — replicate and partial-replicate designs sit outside M13A's core
  scope, so a lookup for one returns `None` rather than the crossover figure;
- *by framework* — M13A covers immediate-release solid oral dosage forms.
  FDA has adopted it, so "12 per treatment group" **is** an FDA rule — but only
  within that scope. Writing `FDA_PARALLEL_MIN_PER_GROUP = 12` would apply an
  IR-solid-oral rule to an inhalation or topical study the document never
  addressed.

So FDA has **two** parallel floors, both true: 12 evaluable subjects under its
general guidance, and 24 under M13A. Neither is "the FDA rule".

**Which framework governs is the caller's to state.** This package is never told
the dosage form, so it cannot decide that M13A applies. `framework=None` means
"not stated" and resolves against general guidance only. The cost is deliberate
and worth naming: an unstated FDA parallel study returns 12 rather than M13A's
24, and an unstated EMA study returns `None`, because no separate EMA general
floor was cited at review. Under-applying a floor the caller never claimed is
recoverable; silently applying a document outside its scope is not.

*This replaces the earlier position that FDA + parallel was absent pending
confirmation. Confirmation arrived: M13A's parallel rule does apply under FDA,
scoped to M13A.*

---

## Replicate designs and reference variability (0.2.0)

**Estimation only. No bioequivalence decision is made anywhere in this layer**,
and `tests/integration/test_no_be_decision_in_this_release.py` enforces it two
ways: no public result type may carry a verdict-shaped field, and no module in
the layer may import the switching rule at all. A module that cannot see the
threshold cannot apply it.

| Capability | Status | Evidence |
|---|---|---|
| Replicate design validation | `IMPLEMENTED` | structural; the tests are the evidence |
| Partial-replicate sWR / CVwR | `IMPLEMENTED_UNVALIDATED` | tier 4 only — see below |
| Fully-replicate sWR | `NOT_IMPLEMENTED` | design validated, estimator declines |

### Why the fully replicated estimator is absent

FDA analyses the partial replicate through a general linear model and the fully
replicated design through a mixed model that estimates within-test and
within-reference variance jointly under a structured covariance. Both designs
give each subject two reference measurements, which makes it easy — and wrong —
to run the partial-replicate closed form over a `TRTR` dataset.

`FullyReplicateReferenceVarianceEstimator` therefore validates its data and
raises. The cost is that a TRTR study gets no sWR from this release. The cost of
substituting would be an sWR that looks ordinary, is compared against 0.294 in
the next release, and selects a regulatory method on a number nobody validated.

### Tier-4 evidence, and its limits

Two checks, both tier 4, neither regulatory:

1. **A hand-calculated fixture.** Six subjects, two per sequence, every
   reference pair expressed as a ratio. The expected variance is derived
   through the two-point identity `(d₁−d₂)²/2`, which never forms a mean — a
   different algebraic route than the estimator's, so agreement is evidence
   rather than a tautology.
2. **A 1200-study simulation.** Shows the estimator is unbiased for σ²WR, and
   that the sampling spread of the estimates matches `2σ⁴/df` at the degrees of
   freedom the result reports. The second is the stronger check: unbiasedness
   can survive a wrong denominator paired with a compensating error; the
   sampling variance pins `n − m` directly. Every tolerance is computed from
   the Monte Carlo standard error at the replicate count used, not chosen by
   widening until it passed.

Neither shows this is the estimator FDA specifies. That is tier 1B, and it is
still pending.

### Two things the tests found

**The result depended on how the input file was sorted.** The invariance tests
assert exact equality — not `approx` — and caught a one-bit difference under row
shuffling. Floating-point addition is not associative, so summing the same
reference differences in a different order gives a different last bit. The
estimator now uses `math.fsum`, which returns the correctly-rounded exact total
and is therefore permutation-invariant. Without it, a study re-exported with a
different sort order produces two different sWRs, differing around 1e-16:
invisible, and reproducible by nobody.

**`m` must be counted, not assumed.** A sequence whose every subject was
excluded contributes no deviation and absorbs no degree of freedom. Using the
design's `m = 3` regardless would understate the degrees of freedom and inflate
the variance, so `m` is the number of sequences that actually contributed and a
shortfall is recorded as a diagnostic.

---

## Degeneracy: refuse, do not rescue

For a validation-oriented statistical application, non-estimable is preferable
to a number obtained by numerical rescue. Currently refused:

- [x] residual variance exactly zero
- [x] fewer than one residual degree of freedom
- [x] all values identical within a sequence
- [x] non-positive measurement (no logarithm)
- [x] only one sequence present (treatment confounded with period)
- [x] duplicated subject
- [x] near-zero variance still analyses — only exact degeneracy is refused

Added in 0.2.0 for replicate designs:

- [x] missing reference replicate — subject excluded, `MISSING_REFERENCE_REPLICATE`
- [x] a subject with only one usable reference observation — same code; no `Dij`
      exists for it
- [x] zero within-reference variance — `estimable = False`, with `swr` and
      `cv_wr` returned as `None` rather than `0.0`, so nothing downstream can
      read a zero as precision
- [x] fewer than one reference degree of freedom — `INSUFFICIENT_REFERENCE_DF`

Still pending, and belonging to the fully replicated estimator:

- [ ] singular mixed-model covariance structure — the code
      (`SINGULAR_MODEL`) exists; the model it would describe does not

---

## What has to happen before "validated" is true

1. **Reference datasets, agreed before use** — tier 1 and tier 2, transcribed
   from the source with citations, never produced by this engine.
2. **Independent cross-implementation** — the same inputs through R in CI, with
   a stated and justified tolerance.
3. **Method equivalence for power** — where the non-central t approximation
   differs from exact Owen's Q, documented as a known difference rather than
   found later by a client.
4. **Lifecycle documents** — Validation Plan, URS, Functional Specification,
   IQ/OQ/PQ, traceability matrix, change control. `__version__` exists to make
   a result-affecting change visible.
5. **Supplier qualification** — scipy and any R used, with pinned versions.

---

## Scope of this version

**Implemented:** average bioequivalence for 2×2 crossover and parallel designs;
power and sample size; FDA and EMA standard intervals; EMA narrowed interval for
NTI **AUC**; product-specific overrides per endpoint. Since 0.2.0: replicate
design validation for TRR/RTR/RRT and TRTR/RTRT, and partial-replicate sWR and
CVwR — **estimation only, no decision**.

**Resolved but not implemented** — each raises `NotImplementedMethod` rather
than returning something plausible:

| Combination | Method | Phase |
|---|---|---|
| FDA + NTI | `FDA_NTI_RSABE` — fully replicated, σw0 = 0.10, Δ = 1/0.9, variance ratio limit 2.5, plus unscaled 80–125% | 2B |
| FDA + highly variable | `FDA_HVD_RSABE` — σw0 = 0.25, switch at sWR ≥ 0.294, point estimate constrained to 80–125% | 2A |
| EMA + highly variable | `EMA_HVD_ABEL` — expanding limits; a different procedure from RSABE, not a relabelling | 2C |

### The switching threshold is settled

**FDA's `sWR ≥ 0.294` is the normative rule.** It is stored as a `VERIFIED`
`RegulatoryValue` cited to Appendix G, applied to the *estimated* sWR, and must
not be recomputed. The 30% CV classification threshold is a separate `VERIFIED`
value cited to III.C. The open question recorded here through Phase 1 is closed;
how it was closed, and what the earlier answer got wrong, is retraction 3 above.

The decision rule itself is frozen as `spec.fda_hvd_method_for()` and covered by
the tier-1A case, so Phase 2A implements a rule that already exists rather than
deciding one while writing the estimator. Nothing consumes it yet.

**Requires specification** — `EMA + NTI + Cmax` raises `SpecificationRequired`.
EMA narrows Cmax only where Cmax itself matters for safety or efficacy, decided
per product: ciclosporin narrows both AUC and Cmax; colchicine narrows AUC and
leaves Cmax at 80.00–125.00. Neither default is safe, so the caller supplies a
`ProductOverride` from the applicable product-specific guidance.
