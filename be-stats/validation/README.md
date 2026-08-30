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
| FDA regulatory algorithm source (1A) | **VERIFIED** — read from the primary document at the cited sections |
| FDA numeric worked dataset (1B) | **PENDING** — and the guidance does not contain one; see below |
| Independent numeric cross-check (tier 3) | **PASSED** — two published `PowerTOST` cases |

`VALIDATED` requires 1B. Nothing here may support a submission.

### The guidance has now been read

It was supplied directly, after every URL this tooling tried returned 404 or
served a download rather than readable text. Every FDA constant in the package
has been checked against the section it cites, and
`RegulatoryValue.verified_by` now reads **"primary document, read at the cited
section"** for all of them.

**The M13A figures did not move.** ICH/FDA M13A Q&A is a different document and
has not been obtained, so those minimums still read "statistical review, with
section references". Both are `VERIFIED`; they are not the same claim, and
`verified_by` exists precisely so an auditor can tell them apart. A test
asserts the split rather than trusting this paragraph.

### Why tier 1B is still open — and not for want of the document

**The guidance contains no worked dataset.** Fifty-four pages, the full
algorithm, the constants and SAS code — and nowhere an input value paired with
a published answer. Obtaining it closed tier 1A completely and could never have
closed 1B.

That reframes the open item. It was recorded as "obtain the FDA guidance". It
should have been "find a source that publishes numbers", which is a different
search: an FDA product-specific guidance with a worked example, an ICH or EMA
example dataset, or a peer-reviewed reproduction.

### What reading it changed

Two things in the code were wrong, and neither was caught by the tests:

**The fully replicated estimator was withheld for a bad reason.** 0.2.0 refused
to estimate sWR for `TRTR`/`RTRT`, inferring from "PROC MIXED should be used
for fully replicate (four-way) BE studies" that the design needed a different
variance estimator. Appendix G gives the calculation once for both designs and
distinguishes them only by `m` — 3 for the partial replicate, 2 for the fully
replicated. The mixed model applies to the treatment contrast, not to sWR, and
both SAS examples reach sWR by the same route. Implemented in 0.3.0.

The caution was reasonable; the inference was not. It came from a sentence
about which procedure to run, not from the specification of the quantity.

**The citations carried a date the document does not.** They read "final, 29
May 2026"; the cover gives only May 2026 and no page names a day. Now "final,
May 2026". An over-specific citation is worse than a coarse one because it
looks checked.

### And one thing found by reading it end to end

Section III.A applies **the same 0.294** to in vitro permeation testing of
topical products — with a *strict* inequality: scaled only if `sWR > 0.294`,
unscaled at `sWR ≤ 0.294`. Appendix G puts the boundary case on the other side.

Same number, same document, opposite treatment at exactly 0.294, different
products. Recorded as `FDA_IVPT_NOTE`, wired into nothing, and guarded by a
test — because a global "the 0.294 rule" would be wrong for one of the two.
That is the M13A scoping lesson arriving from a third direction.

### Tier 3 has been run (0.5.1)

`validation/external/` holds a Docker-based cross-check against R and
PowerTOST 1.5-7, driven from one canonical case definition read by both sides.
See its own README for the design; the parts that matter here:

| Method | Tier 1A | Tier 1B | Tier 3 |
|---|---|---|---|
| `standard_abe` | — | pending | **PASSED** |
| `fda_hvd_rsabe` | passed | pending | **PASSED**, with a finding |
| `fda_nti` | passed | pending | **PASSED** |

`18 passed, 0 failed, 0 skipped`. **Tier 3 is not tier 1B**: an independent
implementation agreeing is not a regulator-published number reproduced, and
`VALIDATED` still needs the latter.

- **One finding.** `RSABE-002-BOUNDARY-NEAR/p_be_sabec` agreed within tolerance
  at **4.61 standard errors** — more than sampling error explains, where every
  other comparison sits between 0.23 and 2.09. The tolerance was *not* tightened
  after the fact; the report now flags it on every run. It should be resolved
  before FDA HVD RSABE is relied upon.
- **`SKIPPED` is not `PASS`**, and a test asserts it. In the CI job a skip is a
  *failure*, because there a missing R means a broken image.
- **The scaled procedures cannot be compared directly at all.** PowerTOST's
  `power.RSABE` and `power.NTID` are simulation-based *power* functions; they
  analyse no dataset and expose no criterion value. The comparison is made at
  the highest common layer — the probability the criterion passes — with the
  Python side simulating studies and applying the be-stats decision to each.
- **Tier 3 needs more than one agreeing case.** Each method names required case
  roles (central, boundary-near, high-variability, unequal-variability) and all
  must pass before it may be marked `PASSED`.

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

**Both figures in that table are artefacts, and 0.5.1 established the real
ones.** They were computed against published values quoted to six decimal
places, and the second additionally truncates the upper limit to `1.1111`.
Neither measured the method difference.

Run against PowerTOST at full precision:

| | recorded above | actually measured |
|---|---|---|
| CV 0.20 case | 1.9 × 10⁻⁷ | **1.4 × 10⁻¹⁰** |
| CV 12.5% case | 6.0 × 10⁻⁶ | **1.7 × 10⁻¹³** |

So the non-central t approximation agrees with exact Owen's Q to about
**1e-10** — three orders better than the 6.0e-06 this file used to attribute to
it.

The case files are left as they stand: a truncated limit is a legitimate
scenario and the 1e-4 tolerance always covered it, so nothing was ever failing.
What was wrong was the explanation. `validation/external/cases/` carries the
re-measured figures.

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
| Partial-replicate sWR / CVwR (`m = 3`) | `IMPLEMENTED_UNVALIDATED` | tier 1A + tier 4 — see below |
| Fully-replicate sWR / CVwR (`m = 2`) | `IMPLEMENTED_UNVALIDATED` | tier 1A + tier 4 |

### One formula, two designs

Appendix G gives the sWR calculation once and distinguishes the designs only by
the sequence count — `m = 3` for TRR/RTR/RRT, `m = 2` for TRTR/RTRT. The
`PROC GLM` / `PROC MIXED` split in the guidance applies to the **treatment
contrast**, where a four-period design needs Satterthwaite degrees of freedom;
it does not apply to sWR. Both SAS examples reach sWR the same way.

Two estimator classes are kept anyway, because the accepted design differs and
because the analyses genuinely diverge at the next step — which belongs to the
release that computes the contrast.

*0.2.0 had the fully replicated estimator decline, on the opposite reading. See
"What reading it changed" above.*

### Tier-4 evidence, and its limits

Two checks, both tier 4, neither regulatory:

1. **A hand-calculated fixture.** Six subjects, two per sequence, every
   reference pair expressed as a ratio. The expected variance is derived
   through the two-point identity `(d₁−d₂)²/2`, which never forms a mean — a
   different algebraic route than the estimator's, so agreement is evidence
   rather than a tautology.
2. **Simulations, 1200 studies each, for both designs.** They show each
   estimator is unbiased for σ²WR, and that the sampling spread matches
   `2σ⁴/df` at the degrees of freedom the result reports. The second is the
   stronger check: unbiasedness can survive a wrong denominator paired with a
   compensating error; the sampling variance pins `n − m` directly. Every
   tolerance is computed from the Monte Carlo standard error at the replicate
   count used, not chosen by widening until it passed.

   The fully replicate simulation gives the **test** measurements twice the
   within-subject variability of the reference ones. sWR must be blind to them,
   and an estimator that pooled the two would land far outside the tolerance.
   That mistake is only possible in the four-period design, which is why the
   asymmetry is there.

Simulation shows an implementation matches its own definition. Tier 1A now
shows that definition is the regulator's — including the R1/R2 assignment,
checked against the explicit SAS conditions for all five sequences. What
remains missing is 1B: a regulator's *number* to reproduce.

### Two things the tests found

**The result depended on how the input file was sorted.** The invariance tests
assert exact equality — not `approx` — and caught a one-bit difference under row
shuffling. Floating-point addition is not associative, so summing the same
reference differences in a different order gives a different last bit. The
estimator now uses `math.fsum`, which returns the correctly-rounded exact total
and is therefore permutation-invariant. Without it, a study re-exported with a
different sort order produces two different sWRs, differing around 1e-16:
invisible, and reproducible by nobody.

**~~`m` must be counted, not assumed.~~ Reversed in 0.3.0 at independent
review.** The argument here was that a sequence whose every subject was
excluded absorbs no degree of freedom, so `m` should be the number that
actually contributed.

That is an arithmetic argument, and `m` is not an arithmetic question. Appendix
G names it per design — 3 for TRR/RTR/RRT, 2 for TRTR/RTRT. A three-sequence
study in which one sequence contributes nobody is **not that design**, and
analysing it as a two-sequence one reports an sWR for a study that was not run.
`m` comes from `ReplicateDesign.regulatory_sequence_count`, and a missing
required sequence returns non-estimable with
`REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS`.

---

## FDA narrow therapeutic index drugs (0.5.0)

| Capability | Status |
|---|---|
| `FDA_NTI_DESIGN_VALIDATION` | `IMPLEMENTED` |
| `FDA_NTI_REFERENCE_SCALED_CRITERION` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_NTI_VARIABILITY_RATIO` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_NTI_UNSCALED_ABE` | **`NOT_IMPLEMENTED`** |
| `FDA_NTI_RSABE` (the method) | **`NOT_IMPLEMENTED`** |

**No endpoint is decided.** Two of the three criteria are computed; the third
needs Appendix C. The method stays `NOT_IMPLEMENTED` while a criterion is
structurally unavailable, and `passes` is `None` rather than `False` — an
endpoint never tested against the unscaled limits is untested under this
procedure, not failing it.

### FDA NTI is not a narrowed interval

The most consequential thing to get wrong here. **90.00–111.11% is EMA's**
approach to the same drug class. FDA does not narrow the acceptance range; it
requires a fully replicate design and adds criteria:

| | Appendix F step 5 |
|---|---|
| a | 95% upper bound for `(μT−μR)² − θσ²WR` ≤ 0, σw0 = 0.10, Δ = 1/0.9 |
| b | the **unscaled 80.00–125.00%** limits must ALSO pass |
| c | upper limit of the 90% equal-tails CI for σWT/σWR ≤ 2.500 |

A test asserts the limits carried are 80.00 and 125.00 and explicitly not 90.00
and 111.11.

### The design gate

III.B requires a fully replicate crossover. A 2×2, a partial replicate or a
parallel study raises before any arithmetic, with no fallback to ordinary
average BE — a structural test asserts the gate is the first call in
`assess_nti_endpoint`. A partial replicate gives each subject one test
measurement, so criterion (c) would have no numerator.

### sWT is an interpretation

Appendix F step 1 gives the closed form for **sWR only**. Step 4 names sWT
without restating how to compute it. What is implemented is the same estimator
applied to the subject's two test observations — the symmetric reading, and
what Appendix C's `REPEATED / GRP=TRT SUB=SUBJ` residual structure produces.

Recorded as an interpretation in the provenance and in the case file's
`limitation`, not presented as transcription. It is the one place in this
procedure where the engine is reading between two lines of the guidance.

### Criterion c, and the tail that is easy to get wrong

```
[ (sWT/sWR) / sqrt(F_{α/2}(v1,v2)),  (sWT/sWR) / sqrt(F_{1−α/2}(v1,v2)) ]
```

`F_p(v1,v2)` has probability `p` to its **right** — `scipy.stats.f.isf`, not
`f.ppf`. The wrong tail yields an interval that is still ordered, still
positive, and roughly the reciprocal of the right one.

`sWR = 0` makes the ratio undefined. Not infinite, not "very large therefore
fails" — the criterion becomes unavailable and the endpoint is not decided.
The guidance states no rule for this case, so the engine does not invent one.

### One Howe helper, shared only after a line-by-line comparison

Appendix F's and Appendix G's SAS are identical except for `theta`. That was
checked before anything was shared, it is recorded as evidence in
`FDA-NTI-CRITERIA-001`, and a test asserts exactly one line differs. The helper
takes `theta` as an argument; each procedure wraps it with its own constants and
its own citation. There is no `mode="nti"` flag.

### A precision discrepancy in Appendix F — not a contradiction

The prose states `Δ = 1/0.9 (approximately=1.11111)`; the SAS example writes
`theta=((log(1.11111))/0.1)**2`, which is the approximation the prose itself
offers.

**This is not the guidance contradicting itself and it does not affect the
algorithm**, which is the same either way. Calling it a contradiction would
misrepresent the document. It is a precision discrepancy between a stated
constant and an example-code approximation, and both are kept, in different
roles:

| | |
|---|---|
| `normative_constant_source` | Appendix F prose — Δ = 1/0.9 |
| `example_code_literal` | Appendix F SAS — 1.11111 |
| `implementation_choice` | use normative 1/0.9 |

`FDA_NTI_CONSTANTS["delta"]` is the ratio. `FDA_NTI_SAS_EXAMPLE_DELTA` is the
literal, held **outside** the constants dict so it cannot be iterated as a
regulatory value, with `fda_nti_theta_sas_example()` beside it. Neither is
rounded into the other, and a structural test confirms no decision path can
reach the example value.

**Why it is recorded rather than waved through.** The difference in θ is
1.898 × 10⁻⁵ relative, which sounds like rounding. Criterion (a) has a
boundary, so "too small to matter" is a claim, not a fact — and a near-boundary
test exhibits a case where it is false: at `sWR² = 0.0020272284` the same data
pass under the prose constant and fail under the example literal. The band is
roughly 4 × 10⁻⁸ wide in sWR², so the case is contrived; the contrivance is
what makes the assertion sharp.

Note this points the *opposite* way to the highly-variable case, where the
regulator's stated value was itself the rounded one. Each is decided from its
own text, not from a general preference for exact arithmetic.

### Citations do not travel with implementations

The sWR estimator is shared with the highly-variable procedure and cites
Appendix G in its own record. An NTI decision rests on Appendix F step 1, which
states the same form, so `FdaNtiResult.provenance()` does not delegate. A test
caught this — checking the citation form rather than the words, since the
provenance legitimately explains in prose that the estimator is shared.

### Tiers

| Tier | FDA NTI |
|---|---|
| 1A | **PASSED** — `FDA-NTI-CRITERIA-001` |
| 1B | **PENDING** — no worked dataset in the guidance |
| 3 | **PENDING** — R unavailable |

---

## FDA highly variable drugs: the decision (0.4.0)

| Capability | Status |
|---|---|
| `FDA_HVD_METHOD_SELECTION` | `IMPLEMENTED` |
| `FDA_HVD_TREATMENT_CONTRAST` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_HVD_RSABE` (the method) | `IMPLEMENTED_UNVALIDATED` |
| `FDA_HVD_UNSCALED_BRANCH` | **`NOT_IMPLEMENTED`** — see below |

**Only the scaled branch decides.** An endpoint with `sWR < 0.294` gets its
sWR, its selected method and its treatment contrast, and then
`decided = False` with `REPLICATE_ABE_MODEL_NOT_IMPLEMENTED`.

### What the tiers say

**Tier 1A — passed.** `FDA-HVD-RSABE-CRITERION-001` records Appendix G steps 2
and 3 against the primary document: the SAS lines, both criteria and their
conjunction, both closed boundaries, the chi-square direction, and which
degrees of freedom scale which term.

**Tier 1B — pending, and the guidance cannot close it.** No worked dataset
exists in the document.

**Tier 3 — pending, and the next external priority.** PowerTOST would be a
reasonable implementation oracle for the criterion; R is not available in this
environment, so no cross-implementation check has been run. The Phase-1 power
and sample-size figures remain the only tier-3 evidence in the package. A test
asserts this gap is recorded in the case file rather than left to be noticed.

`VALIDATED` requires 1B, so `FDA_HVD_RSABE` does not get it from algorithm
conformance alone.

| Tier | RSABE |
|---|---|
| 1A | **PASSED** |
| 1B | **PENDING** |
| 3 | **PENDING** |

### Why the unscaled branch refuses

Appendix G step 1a routes `sWR < 0.294` to the two one-sided tests procedure
without naming a model. **Appendix C names one**, and it is not the Appendix G
intermediate:

```
PROC MIXED;
CLASSES SEQ SUBJ PER TRT;
MODEL Y = SEQ PER TRT / DDFM=SATTERTH;
RANDOM TRT / TYPE=FA0(2) SUB=SUBJ G;
REPEATED / GRP=TRT SUB=SUBJ;
ESTIMATE 'T vs. R' TRT 1 -1 / CL ALPHA=0.1;
```

Fitted on the **subject-period observations**, with a **period** term, an
unstructured 2×2 subject-by-formulation covariance, and **separate residual
variances for T and R** — five covariance parameters, and Satterthwaite degrees
of freedom derived from all five.

Appendix G's `Iij` is a different model: no period term, one residual variance,
no subject-by-formulation covariance. It is the right quantity for the scaled
criterion — FDA forms `x` and `bound_x` from exactly it — and it is not this.

**Why it is not implemented rather than approximated.** This package has scipy
and numpy. Fitting the model above means writing a REML objective over five
parameters, an optimiser that respects the boundary behaviour of a
factor-analytic structure, the asymptotic covariance of the variance components
and a Satterthwaite calculation from all of them — with **no oracle available
here to check it against**. No SAS, no R, no statsmodels (whose `MixedLM`
supports neither group-specific residual variances nor Satterthwaite df
anyway).

An unverifiable mixed model does not fail loudly. It converges, and returns an
interval of entirely plausible width, which becomes a verdict.

**And `EXPERIMENTAL` was not an adequate hedge.** A draft of this release ran
TOST on the `ilat` contrast and marked the capability `EXPERIMENTAL`. A status
field does not travel with a number: the caveat sat in `CAPABILITY_VALIDATION`
while the verdict sat in the result and looked like any other. No capability in
the package carries `EXPERIMENTAL` now, and a test asserts it.

`replicate_abe.py` records the specification so the next implementer starts
from the model rather than from the appendix. `analyse_replicate_abe()` raises
with it. When it is built, it must produce a contrast, an SE and degrees of
freedom and hand them to `abe_from_log_contrast` — not form an interval of its
own.

### The Satterthwaite claim is scoped to Appendix G

"Satterthwaite reduces to the residual degrees of freedom" is true of Appendix
G's `ilat = seq` model, which has **one** variance component — no `RANDOM`, no
`REPEATED`. `satterthwaite_df` implements the general formula and a test
asserts the collapse across several coefficients and dfs rather than asserting
`n − 2`.

It is **not** true of Appendix C, which has five components — but the way it
fails is worse than simple disagreement, and 0.7.0 pinned it down.

For a **balanced, complete** fully replicate design with an **interior**
optimum, Appendix C's Satterthwaite df is `n − 2` **exactly**. Measured to 1e-7
on seven synthetic cases. The contrast collapses onto the subject-difference
statistic, and the whole mixed model reduces to the classical subject-level
analysis — estimate and standard error agreeing to 8 decimal places.

So `n − 2` is not merely a plausible wrong answer here. It is the **right**
answer, on the tidy data anyone would reach for while developing, and it stops
being right exactly where the tidiness stops:

| condition | df |
|---|---|
| balanced, complete, interior | `n − 2` exactly |
| incomplete (available case) | departs — 28.41 against 28 on case B |
| on the correlation boundary | jumps to the within-subject scale — 111 against 38 on case E, and **208 against 75** on EMA Data set I |

A shortcut that hard-coded `n − 2` would therefore pass every balanced test
written for it and be wrong by a factor of nearly three on the one dataset a
regulator has published. That is the strongest argument in this package for
computing the df from the fitted covariance rather than labelling one.

### Things that would not have raised

Every one of these produces a number of the right shape and the wrong value,
and each has a test:

| Mistake | Consequence |
|---|---|
| subject-weighted contrast instead of equal sequence weights | wrong whenever sequences are unequal, i.e. after any dropout |
| `chi2.isf(0.95, df)` instead of `chi2.ppf(0.95, df)` | `bound_y` about 3× too far from zero at 20 df; sign and ordering intact |
| `x = estimate²` without `− SE²` | biased toward failing, most in the smallest studies |
| `bound_x` from the upper limit rather than the larger absolute limit | wrong exactly when the interval straddles zero |
| one shared `df` field | the reference variance's df silently used for the contrast |
| dropping criterion B | reference scaling widens without limit as variability grows |
| a study-level HVD classification | the better-behaved endpoint inherits a scaled region |

### Row-order invariance, carried forward

Shuffled rows, renamed subjects, reordered sequence groups and reversed period
order all leave the selected method, sWR, the contrast, both degrees of
freedom, the scaled bound and the final decision **bit-identical**. No
tolerance is granted: every quantity is a closed form over `math.fsum`, so a
permutation cannot move a bit, and a tolerance would be where a real
order-dependence could hide. The fully replicated design reaches its degrees of
freedom through the Satterthwaite formula rather than an iterative fit, so the
same holds there.

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
- [x] fewer than one reference degree of freedom — `INSUFFICIENT_REFERENCE_DF`
- [x] a required design sequence with no contributing subject —
      `REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS`. `m` is Appendix G's
      constant and is never reduced to fit what survived
- [ ] ~~zero within-reference variance~~ — **not refused, and deliberately so.**
      See below.

### Zero reference variance is an estimate, not a refusal

0.2.0 returned non-estimable for `sWR² = 0`, with `swr` and `cv_wr` as `None`,
so that nobody could read a zero as a perfectly reproducible product. That was
removed at independent review, and rightly.

**Appendix G contains no such rule.** It defines a quantity; for data where
every contributing subject's two reference observations agree exactly, that
quantity is zero. Refusing to report it meant the estimator deciding which
datasets are allowed an answer — a regulatory rejection invented inside a
measurement, which is the failure this package is organised against.

The estimate is now returned with `ZERO_REFERENCE_VARIANCE` at `DATA_QUALITY`
severity: arithmetically sound, data suspect, nothing excluded and nothing
refused. The judgement stays where the evidence is —

- a genuine integrity problem (duplicated subject-period rows, a
  sequence/treatment mismatch) is refused at **dataset validation** on its own
  evidence, and never reaches the estimator;
- the downstream **average BE** analysis already refuses its own degenerate
  within-subject variance (`abe._reject_zero_variance`).

Two independent checks, each on its own grounds, rather than one estimator
guessing. Tests distinguish structurally valid references that happen to agree
from malformed data — a distinction the old behaviour collapsed.

*The rest of this checklist concerns Phase 1's 2×2 crossover analysis, where
the refusal is on its own evidence and stands.*

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
| — | *(empty as of 0.7.0)* | |

*`FDA_HVD_RSABE` left this table in 0.4.0, `EMA_HVD_ABEL` in 0.6.0, and
`FDA_NTI_RSABE` in 0.7.0 when Appendix C supplied its third criterion.*

An empty table is a good place to be and a bad place to lose a safety
mechanism, so `NotImplementedMethod` is exercised by a test that marks a method
unimplemented rather than by waiting for one to be.

### Appendix C support is uneven, and saying so is the point

`FDA_REPLICATE_STANDARD_ABE` was split in 0.7.0 rather than implemented as one
capability, because a single status would have to say one thing about two
situations that differ:

| capability | status | why |
|---|---|---|
| `FDA_REPLICATE_STANDARD_ABE_FULL` | `IMPLEMENTED_UNVALIDATED` | reproduces EMA's published SAS Method C output; cross-checked against ReplicateBE.jl **within the covariance domain that oracle can represent**; and supported by an independent algebraic identity for balanced complete interior fits |
| `FDA_REPLICATE_STANDARD_ABE_PARTIAL` | `NOT_IMPLEMENTED` | no trustworthy oracle. The oracle that works on the fully replicate design differs from published SAS by 2.94 denominator df here, on a design its own validation claim never covered — see `VAL-FDA-APPENDIX-C-002` |

The partial replicate branch refuses: `decided = False`, `passes = None`, and
the diagnostic `APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED`. The arithmetic
would produce a number; there is nothing to check it against, and the correct
partial replicate Satterthwaite df remains **NOT DETERMINED**. Neither of the
two candidate values appears anywhere in the package, and an AST test enforces
that.

**FDA HVD therefore supports the two branches unevenly**, and the module
docstring states it in those terms rather than as "Appendix C is implemented":
the scaled branch (`sWR ≥ 0.294`) decides for both replicate designs; the
unscaled branch decides for fully replicate given the raw observations, and
refuses for partial replicate.

#### Why FULL is not `VALIDATED`, with more evidence than two that are

`EMA_REPLICATE_METHOD_A` and `EMA_ABEL_LIMIT_CALCULATION` are `VALIDATED`.
Appendix C FULL reproduces a regulator's published output on the *same dataset*
to the *same printed precision*, and additionally carries a tier-3 oracle and
an algebraic identity that neither of those has. It still sits below them, and
the reason is worth stating because it looks like an oversight otherwise.

The bar is a **regulator's own published output for the procedure being
claimed**. Appendix C is FDA's procedure and FDA has published no worked
example of it. What exists is EMA's published output for a model EMA
transcribes and attributes to FDA by name — excellent evidence that the
arithmetic is right, and not the same thing as FDA validating FDA's own model.

`test_no_fda_capability_claims_validated` enforces this, and it earned its
place: it caught an attempt to promote FULL during PR #62. What would move it
is an FDA-published worked example, or a SAS PROC MIXED run on published
inputs. Not another oracle, and not more synthetic cases.

#### The tier-3 oracle is domain-limited, and that is a finding not a caveat

ReplicateBE.jl is a tier-3 oracle **within the covariance domain it can
represent**. PR #62 established the limit empirically: FDA's `FA0(2)` permits a
negative subject-by-formulation covariance through the sign of `l₂₁`, and
ReplicateBE 1.0.15 puts the correlation behind a link whose range excludes
negative values. Where `be-stats` fits a negative correlation the oracle is
fitting a *different, constrained* model and cannot adjudicate.

Those cases stay in the suite, are still fitted by the oracle on every CI run,
and are still reported — they are simply not gated on. Where the independent
algebraic identity reaches them it adjudicates instead (case D, which it
supports). Where it does not, the status is **`UNRESOLVED`**, not pass: case B
is incomplete and has no independent check anywhere in this project. That is a
standing validation limitation recorded in `VAL-FDA-APPENDIX-C-003`.

That identity is **independent algebraic / structural conformance evidence**,
not tier 1A. Tier 1A here means conformance to a *regulator's* stated algorithm
or decision rule, and no regulator states this identity.

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
