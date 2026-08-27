# Changelog

`__version__` is bumped on any change that can alter a computed result. An
analysis record stores it, because "which version produced this number" is the
first question asked of a result years later.

---

## 0.6.0 — EMA highly variable drugs (ABEL), and the first tier-1B evidence

The EMA reference-scaled route, implemented as a **separate method** from FDA's
RSABE. No FDA logic changed; no Appendix C was implemented.

### The source was established before any code was written

The obvious risk here was assuming the 2010 guideline had been superseded.
**ICH M13A** came into effect on 25 January 2025 and did supersede parts of it
— but only for non-replicate designs. EMA/531548/2024 is explicit:

> After 25 January 2025, the EMA Guideline on the investigation of
> bioequivalence (CPMP/EWP/QWP/1401/98 Rev. 1) pertaining to specific topics
> not addressed in ICH M13A will continue to apply

and names "BE studies with highly variable drugs (replicate design)" among
them. They are a Tier 3 topic for the future **M13C**, which does not exist
yet. Precedence is recorded in `provenance.py`: M13A → 4.1.10 → the PKWP Q&A →
product-specific guidance.

### The rule, as the regulator states it

| | |
|---|---|
| trigger | **CVwR > 30%**, strictly, on the **CV scale** |
| endpoint | **Cmax only** — AUC stays 80.00–125.00% "regardless of variability" |
| limits | `[U, L] = exp[±k·sWR]`, `k = 0.760` |
| cap | 69.84 – 143.19%, applied as the **stated pair** |
| and | GMR within 80.00–125.00%, required **in addition** |
| designs | 3-period or 4-period replicate crossover |

The trigger is **not** `sWR ≥ 0.294` and is never converted into one. On the sWR
scale EMA's boundary is 0.293560 — a *different number* from FDA's stated
0.294, with real studies in between. That is `VAL-FDA-HVD-002` seen from the
other side, and it is why the constants live in separate tables.

### Tier 1B — the first in this package

EMA published two replicate data sets **with their results**, and the annex has
the raw data. Both reproduce:

| | Data set I | Data set II |
|---|---|---|
| design | 4-period, 77 subjects, **8 incomplete** | 3-period partial replicate, 24 subjects |
| point estimate | **115.66** (published 115.66) | **102.26** (published 102.26) |
| 90% CI | **107.11, 124.89** (107.11, 124.89) | **97.32, 107.46** (97.32, 107.46) |
| CVwR | **46.96%** (published 47.0%) | **11.17%** (published 11.2%) |

All five rows of the guideline's own limits table reproduce to the two decimals
it prints.

**Tier 1B settled something no oracle could have.** `ReplicateDataset` excludes
subjects missing a reference replicate — correct for FDA's sWR. Data set I has
eight incomplete subjects, and EMA's published result can only be reproduced by
**keeping** them. Row-level validation is now shared (`validate_subject_rows`,
a pure refactor); the *inclusion rule* is not, and must not be.

### EMA specifies a model that can be implemented faithfully

The Q&A names **Method A** "guideline recommended": `proc glm`, all terms
fixed, one variance component. That is ordinary least squares — no REML, no
variance components, nothing to fail to converge — so unlike FDA's Appendix C
it reproduces exactly. `replicate_abe.py` still records Appendix C and still
refuses.

So the ordinary branch **decides** here rather than refusing. EMA runs the same
model either way and only moves the limits; there was no need to invent an
approximation, because the regulator specified something implementable.

### Separation, enforced

`FdaHvdResult` and `EmaHighlyVariableResult`. Separate constants, citations and
modules. Tests assert that mutating an EMA constant cannot move an FDA decision
and vice versa, that neither module imports the other, and that the one shared
helper — `linear_model`, a design matrix and a least-squares solve — knows no
regulator. The point-estimate range is 80.00–125.00% on both sides and is
stored twice on purpose.

### Two findings, both raised before any comparison ran

- **`VAL-EMA-ABEL-001`** (`PREEMPTED`). PowerTOST's `p(BE-ABEL)` is the *mixed*
  decision, not the ABEL criterion — the same trap as `p(BE-sABEc)`, in both
  routes. And `power.scABEL` routes for EMA to `power.scABEL1`, which documents
  four "purely empirical" adaptations. A tuned approximation is not an oracle,
  so **`scABEL` — which is deterministic** — is the primary one instead.
- **`VAL-EMA-ABEL-002`** — status `RESOLVED`, classification
  `ACCEPTED_ORACLE_DIVERGENCE`. EMA states the cap as the pair 69.84–143.19 and
  its table gives the ≥50% row as exactly that; the formula at CVwR = 50% gives
  69.83678–143.19102. `be-stats` applies the stated pair, as it does for FDA's
  0.294. The 0.0032 percentage-point divergence was **predicted before the
  comparison ran**, and the capped cases assert it rather than widening a
  tolerance to absorb it.

### Status and classification are separate fields

They answer different questions:

| field | question |
|---|---|
| `status` | does anyone still need to work on this — `OPEN` / `PREEMPTED` / `RESOLVED` |
| `classification` | what turned out to be true, when `RESOLVED` |

**`RESOLVED` is not the same as "the numbers now agree."** An
`ACCEPTED_ORACLE_DIVERGENCE` is understood, decided, and *permanent*. So a
resolved finding still qualifies its method's tier-3 row: `open_findings` on a
case is now `standing_findings`, and the report says `STANDING FINDING` rather
than `OPEN FINDING`. Calling a resolved divergence "open" made the report claim
an investigation was outstanding when none was.

The old field name is **refused** rather than silently accepted — a case left
on it would quietly stop qualifying its method, which is a silent upgrade from
`PASSED_WITH_FINDING` to `PASSED`.

### The first `VALIDATED` capabilities in the package

The EMA stages live in the existing `Capability` enum rather than a table of
their own. Three are `VALIDATED` on tier-1B evidence:

| capability | evidence |
|---|---|
| `ema_hvd_reference_variability` | CVwR 47.0% and 11.2%, both reproduced |
| `ema_replicate_method_a` | 115.66 (107.11, 124.89) and 102.26 (97.32, 107.46) |
| `ema_abel_limit_calculation` | all five rows of the 4.1.10 table |

`VAL-EMA-ABEL-002` does **not** qualify the limit calculation: the tier-1B
table is what *confirms* the stated reading, since all five rows reproduce
under it. The finding records a difference from an **oracle**, and an oracle
does not outrank the regulator.

**`ema_hvd_endpoint_decision` and the method itself stay
`IMPLEMENTED_UNVALIDATED`.** Every part has tier-1B evidence and the whole does
not: no EMA publication carries one end-to-end highly variable Cmax example
running CVwR > 30% → widened limits → Method A 90% CI → GMR constraint → a
stated verdict. Validated components assembled by unvalidated wiring is exactly
the failure this ladder exists to make visible.

A test also asserts that **no FDA capability claims `VALIDATED`**, so the
asymmetry stays a fact about the documents rather than something a later edit
erodes.

### Tier 3 is deterministic for this method

`scABEL` simulates nothing, so EMA's central quantity is checked **exactly**
rather than statistically — stronger than any amount of agreeing simulation.
Uncapped cases agree to 0.00000; capped cases differ by exactly the predicted
0.00322 / 0.00102.

`numpy` is now a declared dependency. It always arrived with scipy and was used
through it; Method A imports it by name, so it is declared by name.

---

## 0.5.2 — VAL-FDA-HVD-001 explained

**No new regulatory methods. No engine behaviour changed, and none needed to
change.** This release is an investigation and its result.

### The 4.61-sigma finding was a mismatch of quantities

`RSABE-002-BOUNDARY-NEAR/p_be_sabec` had be-stats at 0.87055 and PowerTOST at
0.85817. Both were right. They were not computing the same thing.

PowerTOST's element named `p(BE-sABEc)` is `counts["BEul"]`, which accumulates

```r
BE <- ifelse(s2wRs > s2switch, BE_RSABE, BE_ABE)     # power_RSABE2L_isc.R:257
```

— the **mixed decision**, conventional ABE below the switch, without the
point-estimate constraint. The harness compared it against the **scaled
criterion alone**, computed for every simulated study. At CVwR 0.31 about 43.5%
of studies fall below the switch; at 0.40 about 2%; at 0.60 none. Which is
exactly why one case disagreed and two agreed.

Classified `RESOLVED_POWERTOST_CONFIGURATION_ERROR`: the harness drove the
oracle with a component definition that did not mean what its name suggested.

### The evidence

- **Experiment A** — the scaled criterion alone, switching disabled on both
  sides: 0.87055 against 0.87098, **0.17 sigma**. The be-stats figure is the
  same one that was flagged.
- **Across the switch**, the gap tracks the switching fraction to zero — 0.0015
  at CVwR 0.40, exactly 0.00000 at 0.60 — and *changes sign* near CVwR 0.29,
  where conventional ABE becomes easier than a barely widened scaled limit. No
  constant offset or wrong constant produces a sign change located at the switch.
- **Not noise**: at nsims 50 000 across three seeds the gap was 0.01344, 0.01452
  and 0.01414. It neither moves with the seed nor shrinks with nsims.
- **Same study on both sides**: be-stats' `sWR²` against the exact scaled
  chi-square gives a Kolmogorov–Smirnov *p* of 0.958.

### The criterion itself is identical, term by term

`x`, `bound_x`, `y`, `bound_y`, the criterion bound and the decision all map
one-to-one onto PowerTOST's `Em`, `Cm`, `Es`, `Cs` and `SABEc95`, bias
correction included, with `dfRR = n − 2` on both sides. Recorded as a table in
`VAL-FDA-HVD-001.md`.

### What changed

- RSABE cases run PowerTOST with `reg_const("USER", CVswitch = 0, …)`, keeping
  FDA's `r_const` and the `"fda"` criterion and disabling only the routing, so
  `p(BE-sABEc)` is the scaled criterion alone.
- `simulate_scaled_power` **refuses** an RSABE case that does not ask for that.
- New comparison `p_below_switch`, against the exact chi-square rather than
  against another simulation — the one check that separates the `sWR` estimator
  and the switch from the criterion.
- New case `RSABE-004-BOUNDARY-RESEEDED`: same scenario, independent seed, ten
  times the oracle count.
- `validation/findings/` — frozen, machine-readable finding records, with the
  investigation script that reproduces them.
- Tier 3 gained **`PASSED_WITH_FINDING`**; cases gained `open_findings`; the
  report cannot render a qualified pass as a plain one, and a test asserts the
  phrase "fully validated" appears nowhere in it, not even inside a negation.

### What deliberately did not change

- **No production statistical logic.** The finding was in the comparison.
- **No tolerance was altered retrospectively.** `RSABE-002` keeps the 0.01549
  derived before the first run.
- **PowerTOST's below-switch convention was not adopted.** It is a TOST on the
  intra-subject contrast; FDA specifies Appendix C's mixed model, which
  `replicate_abe.py` still records and still refuses to approximate.

### A second, permanent divergence: VAL-FDA-HVD-002

PowerTOST derives the switch as `log(CVswitch² + 1)` with `CVswitch = 0.3`,
i.e. **sWR > 0.293560**. FDA Appendix G states **sWR ≥ 0.294**. This is the
exact distinction settled in 0.1.1, and be-stats follows the regulator.

Worth about 0.005 in switching probability and under 0.001 in power — roughly a
twentieth of the difference that raised `VAL-FDA-HVD-001`, and never a candidate
explanation for it. It is `ACCEPTED_ORACLE_DIVERGENCE`: no run will close it,
and it is what keeps the FDA HVD tier-3 row at `PASSED_WITH_FINDING`.

### ENG-001 was not intermittent

The pytest failure seen once in 0.5.1 and never reproduced depends on the
invocation, not on chance: `test_algorithm_conformance.py` imports from
`tests.unit.test_rsabe_criterion`, which resolves only when the working
directory is `be-stats/`. Fixed with `pythonpath = ["."]`.

---

## 0.5.1 — a reproducible external validation environment

**No new regulatory methods. No engine behaviour changed.** `validation/external/`
is a Docker-based tier-3 cross-check against R and PowerTOST 1.5-7, driven from
one case definition read by both sides.

```bash
make validate          # Docker + R + PowerTOST
make validate-python   # no R: every comparison reports SKIPPED
```

### Tier 3: PASSED for ABE and NTI, PASSED_WITH_FINDING for FDA HVD

> **Corrected in 0.5.2.** This entry originally read "Tier 3 is PASSED for all
> three methods", with the finding noted underneath. For a 4.61-sigma
> difference the qualification belongs in the heading, not below it — a reader
> skimming headings would have taken away the wrong summary. `PASSED_WITH_FINDING`
> is now a status the harness can express, and the FDA HVD row carries it.
> See `VAL-FDA-HVD-001`.

`18 passed, 0 failed, 0 skipped` in CI. The image builds, PowerTOST 1.5-7 runs,
and the job fails on any skip — so green means the comparisons happened.

**With one finding.** See below; it is not a failure and it is not noise.

A missing R environment still reports `SKIPPED`, never `PASS`, and a test
asserts it. That is what a local run without Docker produces.

### Three build attempts, each failure informative

The image went to CI unbuilt, because neither Docker nor R was available where
it was written.

1. **Failed, 3m24s.** `install.packages(..., dependencies = TRUE)` also
   installs **Suggests**; PowerTOST suggests `emmeans`, whose chain reaches
   `s2`, needing Abseil C++ and cmake. Three minutes spent failing on a
   geospatial library nothing here uses. Fixed to `c("Depends", "Imports")`.
2. **Failed, 1m27s.** PowerTOST 1.5-7 installed correctly and the version check
   then rejected it: *wanted 1.5-7, got 1.5.7*. CRAN writes `1.5-7`; R's
   `package_version` normalises the separator, so a string comparison fails on
   the exact version requested. Fixed to compare as versions — correct rather
   than lenient, since `1.5.8` still fails.
3. **Green, 3m30s.**

Two things behaved correctly while failing: `warn = 2` turned the install
warning into an error rather than letting a half-installed environment through,
and the report step refused to invent a report. The job also produced three red
steps for one root cause; "Show the report" is now informational so the real
error is not buried.

### The finding: RSABE near the switching threshold

`RSABE-002-BOUNDARY-NEAR/p_be_sabec` agreed **within tolerance** and is
**4.61 standard errors apart**:

```
py = 0.87055   r = 0.85817   diff = 1.238e-02   tol = 1.549e-02   [4.61 sigma]
```

Every other Monte Carlo comparison sits between 0.23 and 2.09 sigma. This one
is not sampling error.

It passed because the declared tolerance is evaluated at the worst case
`p = 0.5` — a legitimate bound fixed before any run, and about 40% wider than a
comparison at `p ≈ 0.86` deserves.

**The tolerance was not tightened in response.** Narrowing a tolerance because
of what it produced is how a tolerance stops meaning anything. Instead the
report now states each Monte Carlo comparison's distance in units of its own
standard error and flags anything beyond 4 as a `FINDING` — visible on every
run, changing no pass or fail.

Candidate explanations, none established: PowerTOST's FDA setting uses
`est_method = "ISC"`; its `power.RSABE` follows the SAS in FDA's *progesterone*
guidance rather than Appendix G; and the scenario straddles `sWR = 0.294`,
where any difference in estimating sWR has most leverage.

**This should be resolved before FDA HVD RSABE is relied on**, notwithstanding
the PASSED tier 3.

### Two Phase-1 numbers were wrong, and the agreement is far better

Comparing at full precision rather than against six-decimal published figures:

| | Phase 1 recorded | Actually measured |
|---|---|---|
| ABE-001 power | 1.9 × 10⁻⁷ | **1.4 × 10⁻¹⁰** |
| ABE-002 power | 6.0 × 10⁻⁶ | **1.7 × 10⁻¹³** |

be-stats' non-central t approximation agrees with PowerTOST's exact Owen's Q to
about **1e-10** — three orders better than this package's own documentation
claimed. The tolerances were left conservative; one run is not a reason to
tighten them.

### Version pins now have two tiers

`PowerTOST` is **enforced** — its version can change a number, and a different
version is a different oracle. R and the transitive packages are **recorded**:
resolved by the dated snapshot and reported into the results JSON under
`.environment.r_packages_resolved`, so the report captures what ran rather than
what was requested.

Pinning every transitive patch would fail builds over bumps that cannot affect
a result — noise rather than confidence, and a check somebody eventually
relaxes for the wrong reason.

### The scaled procedures cannot be compared directly — at all

The finding that shaped the design. `PowerTOST` 1.5-7 offers, for the FDA
scaled procedures, only **simulation-based power** functions: `power.RSABE` and
`power.NTID` take assumed inputs and return the probability of a BE decision
over `nsims` studies. Neither takes a dataset; neither exposes sWR, a treatment
contrast, or a criterion value. `be-stats` does only the opposite.

So the comparison happens at the highest layer both expose — the probability
the criterion passes — with the Python side simulating studies and applying the
be-stats decision to each. That exercises the whole pipeline, and it is weaker
than comparing a criterion against a criterion. Both facts are recorded.

Per-component comparison is possible and is what the cases do:
`p(BE-sABEc)` and `p(BE-pe)` for RSABE; `p(BE-sABEc)` and `p(BE-sratio)` for
NTI — PowerTOST's `power.NTID` implements all three NTI criteria and reports
each separately.

What each case **cannot** establish is recorded in `not_cross_checkable`:

- the overall `p(BE)` for either method — RSABE's is the mixed procedure and
  NTI's needs criterion (b); both are Appendix C;
- the Howe intermediates, which PowerTOST does not expose — checked against the
  FDA SAS in the tier-1A case instead;
- the sWR switching threshold: PowerTOST's `CVswitch` is on the CV scale and
  FDA's 0.294 is on the sWR scale. Conflating them is the confusion 0.1.1 had
  to correct, so no comparison is attempted.

### Tolerances are derived before the comparison, never widened after

Every comparison carries a mandatory `tolerance_basis`; a case without one is
rejected at load. Sample size is exact. ABE power uses the differences actually
measured. Monte Carlo power uses `4 × sqrt(p(1−p)(1/n₁ + 1/n₂))` at the worst
case `p = 0.5`, so the tolerance does not depend on the answer.

### Re-measuring corrected a Phase-1 attribution

Phase 1 recorded a 6.0 × 10⁻⁶ power difference on the narrowed-limits scenario
and put it down to the non-central t approximation against exact Owen's Q.
**That was wrong.** The Phase-1 case uses `upper_limit = 1.1111`, truncated to
four places, and the truncation dominates. With the exact `1/0.9`, be-stats
gives 0.8002181715 against the same published 0.800218 — a difference of
**1.7 × 10⁻⁷**, the same order as the other case's 1.9 × 10⁻⁷, which is what
the same approximation should produce.

Nothing was ever failing: the Phase-1 tolerance of 1e-4 covered either value.
The *explanation* was wrong, and a claim about where a numerical difference
comes from is exactly the kind of thing this package is supposed to get right.
The Phase-1 case is left alone — a truncated limit is a legitimate scenario —
with the correction recorded beside it, and a test now computes both numbers so
the attribution cannot drift again.

### Tier 3 needs more than one agreeing case

`TIER3_REQUIRED_ROLES` names the roles each method needs — central,
boundary-near, high-variability, unequal-variability — and all must **PASS**,
not merely not fail. Tests assert every required role has a case and that one
passing role does not promote a method.

### Appendix C: investigated, still blocked

`APPENDIX_C_FEASIBILITY.md` records what was checked. `nlme` 3.1-170 expresses
the covariance structure exactly (`pdSymm` random, `varIdent` residuals) but
**the word "Satterthwaite" does not appear anywhere in its manual** — it uses
containment df, which lands directly on the CI width that criterion (b) tests.
`lme4`+`lmerTest` has Satterthwaite but one residual variance; `glmmTMB` has
both structures but not Satterthwaite inference.

No package examined meets all four requirements, so **Appendix C stays
blocked** and nothing is implemented in Python on the strength of a near miss.

### Also

- `.github/workflows/validation-r.yml` — an optional `validation-r` job. The
  ordinary suite stays pure Python and needs neither Docker nor R.
- A `Makefile`, so the cross-check is one command.
- A PowerShell scripting bug wrote the oracle call for five cases as an empty
  array (`$args` is an automatic variable). Caught by the harness's own test
  asserting every case names its oracle arguments.

383 tests collected, 0 failures, 6 skipped.

---

## 0.5.0 — FDA narrow therapeutic index: two criteria of three

FDA's NTI procedure from Appendix F. **No EMA ABEL.** **No Appendix C.**

**FDA NTI is not a narrowed acceptance interval.** There is no 90.00–111.11%
anywhere in it — that is EMA's approach to the same drug class. FDA requires a
fully replicate study and *three separate criteria*, all of which must pass:

| | Appendix F | Status |
|---|---|---|
| a | 95% upper bound for `(μT−μR)² − θσ²WR` ≤ 0, with σw0 = 0.10 | **computed** |
| b | the **unscaled** 80.00–125.00% limits must also pass | **not computed** |
| c | upper limit of the 90% equal-tails CI for σWT/σWR ≤ 2.500 | **computed** |

So every endpoint comes back `NOT DECIDED`, however comfortably (a) and (c)
pass. Criterion (b) is the unscaled analysis of a fully replicate study, which
is Appendix C's mixed model — the same refusal as the previous release, for the
same reason. **Two of three criteria are not a verdict**: an endpoint never
tested against the unscaled limits is untested under this procedure, neither
bioequivalent nor inequivalent.

### The design gate runs first

III.B: *"For NTI drugs, a fully replicate crossover design should be used."* A
2×2, a partial replicate or a parallel study raises `NtiDesignError` before any
arithmetic — there is no fallback to ordinary average BE. A structural test
asserts the gate is literally the first call in `assess_nti_endpoint`.

A partial replicate gives each subject *one* test measurement, so criterion (c)
would have no numerator at all.

### sWT, and one estimator

The reference variance is #55's, unchanged, with `m = 2`. sWT is the same
estimator applied to the subject's two **test** observations — the shared
`sum_of_squared_deviations` now serves both, so there is one implementation of
the formula rather than two that look alike. A test asserts it by swapping the
roles: a study whose test differences equal another's reference differences
gives the same number from the two estimators.

**sWT is an interpretation, and is recorded as one.** Appendix F step 1 states
the closed form for sWR only; step 4 names sWT without restating how to compute
it. The symmetric reading is what Appendix C's `REPEATED / GRP=TRT` residual
structure produces, and it is flagged in the provenance rather than presented
as transcription.

### Criterion c: the F interval, not an approximation

```
[ (sWT/sWR) / sqrt(F_{α/2}(v1,v2)), (sWT/sWR) / sqrt(F_{1−α/2}(v1,v2)) ]
```

`F_p(v1,v2)` has probability `p` to its **right** — `scipy.stats.f.isf`, not
`f.ppf`. The wrong tail gives an interval that is still ordered, still positive
and roughly the reciprocal of the right answer. `v1` belongs to sWT and `v2` to
sWR; they differ whenever a subject is missing one of its four measurements.

No normal approximation, no Wald interval on log variance, no bootstrap.

**`sWR = 0` makes the ratio undefined, not infinite.** The previous release
established that a zero reference variance is a legitimate estimate. It is also
a denominator here. The criterion becomes unavailable with
`REFERENCE_SD_ZERO_VARIANCE_RATIO_UNDEFINED`, and the endpoint is not decided —
rather than reporting infinity, or "very large, therefore fails", which the
guidance does not authorise.

### One Howe helper, shared on evidence

`howe.py` is new, and the two procedures were compared line by line before
sharing anything. Appendix F's and Appendix G's SAS are **identical except for
`theta`**:

```
x=estimate**2-stderr**2                     ← same
boundx=(max((abs(lower)),(abs(upper))))**2  ← same
theta=((log(1.11111))/0.1)**2               ← DIFFERS from ((log(1.25))/0.25)**2
y=-theta*s2wr                               ← same
boundy=y*dfd/cinv(0.95,dfd)                 ← same
critbound=(x+y)+sqrt(((boundx-x)**2)+((boundy-y)**2))  ← same
```

So the helper takes `theta` as an argument and knows nothing about drug class,
with a wrapper per procedure supplying its own constants and its own citation.
Not a generic routine with a `mode="nti"` flag. The comparison is recorded in
the validation case, and a test asserts exactly one line differs.

### A precision discrepancy — not a contradiction

Appendix F's prose states `Δ = 1/0.9 (approximately=1.11111)`, and its SAS
example writes `theta=((log(1.11111))/0.1)**2` — the five-decimal approximation
the prose itself offers.

**This is not the guidance contradicting itself, and it does not affect the
algorithm**, which is identical either way. It is example code printing a
constant to five places. Two values are now kept, in different roles:

```
normative_constant_source:  Appendix F prose — Delta = 1/0.9
example_code_literal:       Appendix F SAS   — 1.11111
implementation_choice:      use normative 1/0.9
```

`FDA_NTI_CONSTANTS["delta"]` holds the ratio. `FDA_NTI_SAS_EXAMPLE_DELTA` holds
the literal, deliberately **outside** the constants dict so it can never be
iterated as a regulatory value, and `fda_nti_theta_sas_example()` computes what
the example would give. Neither is rounded into the other.

Carried through θ the difference is **1.898 × 10⁻⁵** relative — small enough to
sound like rounding. Criterion (a) has a boundary, so "too small to matter" is a
claim rather than a fact, and a near-boundary test exhibits a case where it
matters: at `sWR² = 0.0020272284` the same data **pass** under the prose
constant and **fail** under the example literal. The band is about 4 × 10⁻⁸ wide
in sWR², so the case is contrived on purpose — which is what makes the assertion
sharp. A structural test also confirms no decision path can reach the example
value.

Worth noting this points the opposite way to the highly-variable case, where the
regulator's stated value was itself the rounded one (`sWR = 0.294`, not the
derived `0.293560`). Each constant is decided from its own text rather than from
a general preference for exact arithmetic.

### Citations do not travel with implementations

The sWR estimator is shared with the highly-variable procedure and its own
`provenance()` cites Appendix G. An NTI decision does not rest on Appendix G, so
`FdaNtiResult.provenance()` does not delegate — it cites **Appendix F step 1**,
which states the same closed form. A test caught this and now prevents it,
checking the citation form rather than the words, since the provenance
legitimately explains in prose that the estimator is shared.

### Also

- `satterthwaite_df` returns the single-component collapse exactly. Evaluating
  `2t²/(2t²/v)` in floating point printed `21.999999999999996` degrees of
  freedom in a report. The identity is applied instead, and a test evaluates
  the general expression and confirms it reproduces `v`.
- `TestVarianceResult` → `WithinTestVarianceResult`: pytest was collecting it
  as a test class.

### Validation state

| | Status |
|---|---|
| `FDA_NTI_DESIGN_VALIDATION` | `IMPLEMENTED` |
| `FDA_NTI_REFERENCE_SCALED_CRITERION` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_NTI_VARIABILITY_RATIO` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_NTI_UNSCALED_ABE` | **`NOT_IMPLEMENTED`** |
| `FDA_NTI_RSABE` (the method) | **`NOT_IMPLEMENTED`** |
| `EMA_HVD_ABEL` | `NOT_IMPLEMENTED` |

The method stays `NOT_IMPLEMENTED` while one criterion is structurally
unavailable — a test asserts that too.

**Tier 1A — passed.** `FDA-NTI-CRITERIA-001` covers the design gate, all three
criteria, all eight combinations, both closed boundaries, the F-tail
convention, the constants and their discrepancy, and the zero-reference case.

**Tier 1B — pending.** No worked dataset in the guidance.

**Tier 3 — pending.** R is not available here.

336 tests pass, 6 skipped.

---

## 0.4.0 — FDA highly variable drugs: the scaled branch decides

For each PK endpoint:

```
validated replicate dataset -> sWR -> switch at 0.294
     sWR >= 0.294  ->  FDA HVD RSABE       -> decided, every component shown
     sWR <  0.294  ->  method selected     -> NOT DECIDED, and here is why
```

**Only one of the two branches decides, and that is deliberate.**

Appendix G step 1a routes an endpoint below the threshold to the two one-sided
tests procedure without naming a model. **Appendix C names one**, and it is not
the Appendix G intermediate: a mixed model on the subject-period observations
with fixed effects for sequence, **period** and treatment, an unstructured 2×2
subject-by-formulation covariance (`RANDOM TRT/TYPE=FA0(2) SUB=SUBJ`),
treatment-specific residual variances (`REPEATED/GRP=TRT SUB=SUBJ`) and
Satterthwaite degrees of freedom from all five covariance parameters.

This package has scipy and numpy. No mixed-model fitter here supports
group-specific residual variances or Satterthwaite df — statsmodels' `MixedLM`
does neither, and it is not installed — and there is **no oracle available to
check a from-scratch REML fit against**: no SAS, no R. An unverifiable mixed
model does not fail loudly; it converges and returns a confidence interval of
entirely plausible width, which becomes a bioequivalence verdict.

So the unscaled branch refuses, with
`REPLICATE_ABE_MODEL_NOT_IMPLEMENTED` and the model it would have to fit.
`replicate_abe.py` records that specification.

**No FDA NTI. No EMA ABEL.** Both remain `NOT_IMPLEMENTED`, and a test asserts
that implementing the highly-variable route did not turn NTI into a
configuration flag.

### The method is chosen per endpoint

Appendix G step 1 determines BE "for the individual PK parameter(s)". So AUC
may take ordinary average BE while Cmax is reference-scaled, from the same
subjects. Classifying a study on its worst endpoint and scaling everything
would hand the well-behaved endpoint an acceptance region it has not earned.
`assess_study` is a loop over `assess_endpoint` for exactly this reason.

### The contrast weights sequences, not subjects

FDA's `estimate 'average' intercept 1 seq 0.3333 0.3333 0.3333` averages the
three **sequence means**. With equal group sizes that is the subject mean; with
unequal ones it is not, and dropouts make sequences unequal in almost every
real study. A hand-calculated 3/2/1 fixture asserts the engine produced the
equal-sequence-weight estimate and *not* the subject mean — both are computed
in the test so the difference is visible rather than argued.

`subject_weighted_mean()` is exported solely so that comparison can be made.
Nothing in the package calls it.

### Two designs, two contrast estimators

The shared sWR formula did **not** license a shared contrast. FDA fits the
partial replicate with `PROC GLM` and the fully replicated design with
`PROC MIXED ... ddfm=satterth`, so they are separate classes.

The Satterthwaite degrees of freedom are **computed**, not assumed.
`satterthwaite_df` implements the general formula; FDA's model here carries a
single residual variance component, for which it collapses to the residual
degrees of freedom exactly, for any coefficient. A test asserts the collapse
rather than asserting `n - 2` — and the general form keeps working if a later
model gains a second component.

### Howe's Approximation I, component by component

`x`, `bound_x`, `y`, `bound_y` and `critbound` are all fields on
`ScaledCriterion`, because each has a plausible-looking wrong version that
raises nothing:

- `x` losing its `- SE²` biases the criterion toward failing, most in the
  smallest studies;
- `bound_x` taking the upper limit rather than the larger **absolute** limit is
  wrong exactly when the interval straddles zero;
- **`bound_y` taking the wrong chi-square tail.** SAS's `cinv(0.95, df)` is the
  inverse CDF — `stats.chi2.ppf`, not `stats.chi2.isf`. At 20 df the two differ
  by roughly a factor of three, and the mistake keeps the sign and the ordering
  intact. The direction is self-checkable and a test checks it: `bound_y` must
  be closer to zero than `y`, which makes it a *lower* bound on the reference
  variance — less scaling, the conservative way.

### Both criteria, never one boolean

Appendix G step 3 requires the scaled bound `<= 0` **and** the T/R ratio within
`[0.8000, 1.2500]`. `RsabeResult` exposes each separately and derives `passes`
from both. All four logical combinations are tested, including the one that
matters: a comfortably passing scaled criterion with a ratio of 1.40 still
fails. Criterion B is the stop on reference scaling, which otherwise widens the
acceptance region without limit as reference variability grows.

Both boundaries are closed and tested at ±1 in the last place.

### Two subject counts, two degrees of freedom

A subject missing its **test** measurement has no `Iij` and may still have both
reference replicates. It was `ADVISORY` in 0.2.0 because sWR did not need it;
it is an `EXCLUSION` from the contrast now — the same code at a different
severity, disambiguated by `model` in the diagnostic context.

So `n_for_swr` and `n_for_treatment_contrast` are separate fields and can
legitimately differ, as are `reference_variance_df` and
`treatment_contrast_df`. Appendix G scales `bound_y` by the **reference
variance's** degrees of freedom while the interval behind `bound_x` uses the
contrast's; one generic `df` would make them equal by construction.

### One TOST implementation, and it is now actually shared

`abe.abe_from_log_contrast()` takes a contrast somebody else estimated and
forms the interval and the containment decision. `analyse_crossover` and
`analyse_parallel` were refactored to route through it, so the abstraction is
live rather than speculative — Phase 1's golden cases confirm no number moved.
The private `_interval` helper is gone; a structural test asserts there is
exactly **one** `stats.t.ppf` in the package and none at all in `hvd.py`.

It is kept despite the unscaled branch refusing, because Appendix C — when
implemented — must produce a contrast, an SE and degrees of freedom and hand
them to it rather than forming an interval of its own.

### `EXPERIMENTAL` was the wrong answer, and it is gone

An earlier draft of this release ran TOST on the Appendix G `ilat` contrast for
the unscaled branch and marked the capability `EXPERIMENTAL`.

**A status field does not travel with a number.** The caveat sat in
`CAPABILITY_VALIDATION`; the verdict sat in `standard_abe_result` and looked
exactly like one computed from the right model. `FDA_HVD_UNSCALED_BRANCH` is
`NOT_IMPLEMENTED` now, the branch refuses, and no capability in the package
carries `EXPERIMENTAL` — a test asserts that too.

### Validation state

| | Status |
|---|---|
| `FDA_HVD_METHOD_SELECTION` | `IMPLEMENTED` |
| `FDA_HVD_RSABE` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_HVD_TREATMENT_CONTRAST` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_HVD_UNSCALED_BRANCH` | **`NOT_IMPLEMENTED`** |
| `FDA_NTI_RSABE` | `NOT_IMPLEMENTED` |
| `EMA_HVD_ABEL` | `NOT_IMPLEMENTED` |

**Tier 1A — passed.** `FDA-HVD-RSABE-CRITERION-001` covers the criterion, both
boundaries, the conjunction, the chi-square direction and which degrees of
freedom scale which term.

**Tier 1B — pending.** The guidance has no worked dataset and cannot close it.

**Tier 3 — pending.** PowerTOST would be a reasonable implementation oracle;
R is not available here, so no cross-implementation check has been run on the
criterion. A test asserts that gap is recorded rather than implied. This is the
next external priority.

`VALIDATED` requires 1B. Nothing here may support a submission.

270 tests pass, 4 skipped.

---

## 0.3.0 — the guidance was obtained and read

The FDA guidance had been unreadable through every route this tooling had:
every URL 404'd or served a download rather than text. It was supplied
directly, and read section by section. Four things changed, and two of them
were wrong before.

### The fully replicated estimator was withheld for a bad reason

0.2.0 refused to estimate sWR for `TRTR`/`RTRT`, reasoning that FDA's use of
`PROC MIXED` for four-period studies implied a different variance estimator,
and that substituting the partial-replicate closed form would be our arithmetic
standing in for the regulator's method.

**Appendix G gives the calculation once, for both designs**, distinguished only
by the sequence count:

> "I = number of sequences m used in the study [m = 3 for partially replicate
> design: TRR, RTR, and RRT; m = 2 for fully replicate design: TRTR and RTRT]"

The GLM/MIXED distinction is real and applies to the *treatment contrast*,
where a four-period design needs Satterthwaite degrees of freedom. Not to sWR.
Both SAS examples reach sWR identically — the partial takes `s2wr = ms/2` from
a one-way ANOVA of `dlat` on sequence, the fully replicated takes
`s2wr = estimate/2` from the residual covariance parameter of the same model.

So `FullyReplicateReferenceVarianceEstimator` now estimates, with `m = 2`. A
`TRTR` study that got nothing from 0.2.0 gets an sWR from 0.3.0. **The caution
was misplaced**: it was inferred from a sentence about which SAS procedure to
use, not from the specification of the quantity.

### An over-specific citation

Every FDA citation read `"final, 29 May 2026"`. The document's cover gives only
**May 2026**, and no page inside names a day. The precise date came from
recollection. Now `"final, May 2026"` — what the guidance itself says. An
over-specific citation is worse than a coarse one, because it looks checked.

### The same guidance uses 0.294 twice, with different boundaries

Section III.A, for in vitro permeation testing of topical products:

> "the reference-scaled average BE approach is used for the endpoint only if it
> has a sWR > 0.294. The regular average BE approach … is used for the endpoint
> with sWR ≤ 0.294."

Appendix G puts the boundary case on the *other* side. Same number, same
document, opposite treatment at exactly 0.294, different products. Recorded as
`FDA_IVPT_NOTE`, consumed by nothing, with a test that stops it being tidied
away as a duplicate — this is the M13A scoping lesson arriving from a third
direction.

### Everything else was confirmed

- `sWR < 0.294 → TOST`, `sWR ≥ 0.294 → reference-scaled` — stated in **both**
  III.C and Appendix G, which agree on the boundary.
- HVD classification: "%CV … 30 percent or greater and … not considered NTI
  drugs".
- σW0 = 0.25, θ = [ln(1.25)/σW0]², point estimate within [0.8000, 1.2500].
- NTI: σW0 = 0.10, Δ = 1/0.9, and **three** criteria — scaled bound, *plus*
  unscaled 80.00–125.00%, *plus* the 90% equal-tails CI for σWT/σWR ≤ 2.500.
  Two constants added for the criteria that were implicit.
- Minimums: "The number of evaluable subjects in a PK BE study should not be
  less than 12. For highly variable drug products, a minimum of 24 subjects are
  recommended" — cited now to II.A rather than to the document at large.
- The R1/R2 assignment. FDA states it as explicit SAS conditions on sequence
  and period; the engine derives it from the sequence name in ascending period
  order. They agree for all five sequences, which is now a test.

### Chain of custody

`verified_by` moves from `"statistical review, with section references"` to
`"primary document, read at the cited section"` for every FDA constant.
**The M13A figures do not move** — that is a different document, and it has not
been obtained. Both claims are `VERIFIED`; they are not the same claim, and the
field exists to say which.

### Two rules I invented, removed at independent review

The guidance was reviewed independently against this branch. It confirmed the
fully-replicate correction, the HVD threshold, the Appendix G constants, the
NTI criteria and the R1/R2 mappings — and found two places where the estimator
was enforcing rules Appendix G does not contain. Both are the same failure as
deriving `0.294` from a 30% CV: locally sensible reasoning substituted for the
regulator's specification.

**`m` was being computed from the data.** The estimator set
`m = len(grouped)` — the sequences still holding a subject after exclusions —
reasoning that an empty sequence absorbs no degree of freedom and that SAS
would behave the same way on an empty `CLASS` level.

But `m` is not an arithmetic question. Appendix G names it: *"m = 3 for
partially replicate design: TRR, RTR, and RRT; m = 2 for fully replicate
design: TRTR and RTRT"*. A three-sequence study in which one sequence
contributes nobody is **not that design**, and analysing it as a two-sequence
one reports an sWR for a study that was not run, on degrees of freedom
belonging to a different design.

`m` now comes from `ReplicateDesign.regulatory_sequence_count`, and a missing
required sequence returns non-estimable with
`REQUIRED_SEQUENCE_HAS_NO_CONTRIBUTING_SUBJECTS`. The result carries
`regulatory_m` and `contributing_sequences` side by side, so a reader sees the
disagreement without reading diagnostics. The ambiguous `n_sequences` name is
gone — that name is what allowed the mistake.

**Zero variance was being refused.** `sWR² = 0` returned non-estimable with
`swr` and `cv_wr` as `None`, so that nobody could read a zero as a perfectly
reproducible product.

That was a regulatory rejection rule invented inside a measurement. Appendix G
defines a quantity; for data where every subject's two reference observations
agree exactly, the quantity is zero. Refusing to report it meant this estimator
deciding which datasets are allowed an answer.

The estimate is now returned, with a `ZERO_REFERENCE_VARIANCE` diagnostic at a
new `DATA_QUALITY` severity — arithmetically sound, data suspect, nothing
excluded and nothing refused. The judgement stays where the evidence is: a
genuine integrity problem (duplicated subject-period rows) is refused at
dataset validation on its own grounds, and the downstream average BE analysis
already refuses its own degenerate variance. Tests now distinguish structurally
valid references that happen to agree from malformed data, which the old
behaviour conflated.

Non-estimable is reserved for cases where the quantity genuinely does not
exist: fewer than one degree of freedom, or a missing required sequence.

### A stale second chain of custody

`spec.py` moved its constants to primary-document verification;
`reference_variance.py` kept its own string saying the PDF could not be
retrieved. Two chains for one formula, and the stale one was the false one. It
now imports `VIA_PRIMARY_DOCUMENT` rather than restating it.

### Tier 1B is still open, and now for a better reason

The guidance contains **no worked dataset** — no input values and no published
answer anywhere in 54 pages. It states the algorithm and gives SAS code.
Obtaining it closed tier 1A and could never have closed 1B. That needs a
different source, and the gap is no longer "we could not get the document".

189 tests pass, 2 skipped.

---

## 0.2.0 — replicate data and reference variability

**The foundation for FDA highly-variable analysis, and deliberately not the
analysis.** This release answers one question: given a valid FDA replicate
dataset, can the engine identify the design, validate its structure, build the
reference replicates correctly, estimate sWR and CVwR, and say whether those
quantities are estimable? It contains no bioequivalence verdict, and a test
fails the build if one appears.

Nothing in Phase 1 moves. `0.2.0` rather than `0.1.2` because the surface grew,
not because a result changed.

### New

- `ReplicateObservation` / `ReplicateDataset` — one row per measurement, and a
  dataset that validates subject, sequence, period, treatment, endpoint,
  duplicates, completeness, reference replication and positivity.
- `ReplicateSequence` (TRR / RTR / RRT / TRTR / RTRT) and `ReplicateDesign`.
  **The sequence name is the specification**: `TRR.expected_treatment(2)` reads
  the letter. Nothing is inferred from row order — not the sequence, not the
  period, and above all not which reference measurement is R1.
- `PartialReplicateReferenceVarianceEstimator` — FDA Appendix G:
  `sWR² = ΣᵢΣⱼ(Dij − D̄ᵢ.)² / 2(n − m)` with `Dij = Rij1 − Rij2` on the log
  scale. `CVwR` through the package's single canonical conversion.
- `Iij = Tij − (Rij1 + Rij2)/2` exposed and checkable. **Nothing consumes it**;
  PR #56 will.
- `DiagnosticCode` — typed identifiers, not free text. A reason that cannot be
  counted, filtered or asserted on is not a reason.
- `Capability` and `CAPABILITY_VALIDATION`, separate from `Method`.

### Refuses rather than approximates

| Situation | Behaviour |
|---|---|
| TRTR / RTRT | design validated, dataset built, **estimator raises** |
| TRT, TRRR, RRTR, mixed designs | `UnsupportedDesign`, naming what *is* supported |
| sequence/period/treatment mismatch | subject excluded with `SEQUENCE_TREATMENT_MISMATCH` |
| duplicate period | subject excluded; no winner chosen |
| sWR² = 0 | ~~`estimable = False`~~ **reversed in 0.3.0** — reported, flagged `DATA_QUALITY` |

**The fully replicated estimator is not written, on purpose.** FDA analyses
that design with a mixed model; the partial-replicate closed form is not that
model. Running it anyway would produce an sWR that looks ordinary, gets
compared against 0.294 in the next release, and selects a regulatory method on
a number nobody validated — the same class of substitution 0.1.1 corrected.

### Every dropped subject is a finding

`subjects_received`, `subjects_used`, `subjects_excluded` and
`exclusion_reasons` travel on the result and are asserted to add up. Complete-
case deletion without a record is the quiet failure of every replicate
analysis: 24 go in, 22 reach the estimator, the report says 24.

A subject missing its **test** measurement is `ADVISORY`, not an exclusion — sWR
comes from the references alone, and dropping it would discard evidence for a
contrast this release does not compute. It becomes an exclusion in #56.

### Found while building this

- **The result depended on how the input file was sorted.** The invariance
  tests assert exact equality and caught a 1-ULP difference under row shuffling:
  floating-point addition is not associative, so `sum` over the same values in a
  different order differs in the last bit. Now `math.fsum` throughout, which
  returns the correctly-rounded exact total and is permutation-invariant. A
  study re-exported with a different sort order would otherwise have produced
  two sWRs — invisible, and reproducible by nobody.
- ~~**`m` is counted, not assumed.**~~ **Reversed in 0.3.0** — `m` is Appendix
  G's per-design constant, and a missing required sequence refuses rather than
  becoming a smaller design. See above.

### Validation state

| | Status |
|---|---|
| `FDA_HVD_REPLICATE_DATA_VALIDATION` | `IMPLEMENTED` |
| `FDA_HVD_REFERENCE_VARIANCE` | `IMPLEMENTED_UNVALIDATED` |
| `FDA_HVD_RSABE` | `NOT_IMPLEMENTED` |
| `FDA_NTI_RSABE` | `NOT_IMPLEMENTED` |

Data validation is `IMPLEMENTED` — a new status meaning "implemented, with no
external numeric claim to validate": it either enforces the design definitions
or it does not, and the tests decide that. Reference variance produces a
number, so it stays `IMPLEMENTED_UNVALIDATED` until tier 1B.

Evidence added: a hand-calculated six-subject fixture (mathematical, tier 4),
and a 1200-study simulation showing the estimator is unbiased for σ²WR and that
its sampling spread matches χ² on the degrees of freedom it reports — which
pins `n − m` rather than merely displaying it. Both tier 4. Neither validates
anything against a regulator.

161 tests pass.

---

## 0.1.1 — corrections before the freeze

Applied at statistical review of 0.1.0, before merge. No estimator arithmetic
changed; two *routing* answers did, and both were wrong in 0.1.0.

### The FDA switching threshold is the regulator's, not ours

0.1.0 derived FDA's highly-variable switching threshold as
`cv_to_log_sd(0.30) = 0.293560`, marked it `DERIVED`, and enforced with an
AST-level test that `0.294` must never appear in `src/` as a numeric literal.

**That was wrong, and the guard has been deleted.** FDA states two different
things 0.0005 apart: within-subject **CV ≥ 30%** *classifies* a drug as highly
variable (III.C), and estimated **sWR ≥ 0.294** *selects the analysis*
(Appendix G). The second is not a rounded display of the first — it is the
regulator's criterion, applied to an estimate. Deriving it substituted this
package's arithmetic for FDA's rule, and the test forbidding `0.294` was in
effect a test *requiring* that substitution.

- `conversions.py` now exports **no constants at all** — only the conversion.
  A test asserts it, because a regulatory number there would be a float without
  provenance.
- `FDA_HVD_CONSTANTS` and `FDA_NTI_CONSTANTS` in `spec.py` carry both figures as
  separate `VERIFIED` `RegulatoryValue`s with separate citations, plus σw0,
  the point-estimate constraint, and the NTI constants.
- `spec.fda_hvd_method_for(swr)` freezes the decision rule. Nothing consumes it
  yet; Phase 2A implements a rule that already exists.
- `RegulatoryValue.verified_by` is new. A figure read from the primary document
  and one relayed by a qualified reviewer are both `VERIFIED`, and an auditor is
  entitled to know which. Every FDA constant here records
  *"statistical review, with section references"*, because this tooling could
  not retrieve the guidance PDF.

### Regulatory minimums are scoped by framework, not only by region

0.1.0 registered no FDA parallel floor, on the grounds that whether M13A's
twelve-per-group rule governs an FDA parallel study was unconfirmed. It is
confirmed — **and scoped**. FDA has adopted M13A, so the rule applies within
M13A's scope: immediate-release solid oral dosage forms.

The registry key gains a `Framework`, so FDA now has two parallel floors, both
true: **12** evaluable subjects under its general PK BE guidance, **24** under
M13A. Neither is "the FDA rule", and `FDA_PARALLEL_MIN_PER_GROUP = 12` is
exactly the global constant this shape exists to prevent.

Which framework governs is the caller's to state — this package is never told
the dosage form. `framework=None` resolves against general guidance only, never
M13A. The cost is deliberate: an unstated FDA parallel study now returns 12
rather than 24, and an unstated EMA study returns `None`, since no separate EMA
general floor was cited.

### Validation evidence, stated by tier

Tier 1 is split, because this package holds one half without the other:

| Evidence | Status |
|---|---|
| FDA regulatory **algorithm** (1A) | **VERIFIED** — attested at review with section references |
| FDA numeric **worked dataset** (1B) | **PENDING** — guidance body still not obtainable |
| Independent numeric cross-check (3) | **PASSED** — two `PowerTOST` cases |

`VALIDATED` requires 1B. An attested algorithm is not a reproduced result.
`validation/phase1/algorithm/FDA_HVD_SWITCH_001.json` is the first 1A case,
checked at 0.2939 / 0.2940 / 0.2941 and at sWR = 0.2937 — the study 0.1.0 would
have misrouted.

94 tests pass across `tests/unit`, `tests/integration` and `tests/validation`.

---

## 0.1.0 — Phase 1 freeze

**Scope frozen: conventional average bioequivalence.** No replicate designs, no
reference scaling. Phase 2 work must not move a result in this release.

### Implemented

- Average BE for 2×2 crossover and parallel designs — TOST, 90% CI on the log
  scale, decision by interval containment.
- Power and sample size — non-central t approximation, named on every result.
- `resolve_be_spec()` — decides the *method* before any arithmetic, so a
  jurisdiction/class/endpoint combination that needs a different procedure
  refuses rather than returning a plausible interval.
- FDA and EMA standard intervals; EMA narrowed interval for **AUC** of an NTI
  drug; product-specific overrides per endpoint.
- Regulatory minimum subject counts, **keyed by design family** — ICH M13A
  gives 12 evaluable subjects for a crossover but 12 *per group* for a parallel
  design, which is 24.
- Provenance on every regulatory number: value, document, section, document
  version, verification status. `BeSpec.provenance()` answers "why 0.90".
- Validation status per method, with an opt-in `require_validated()` gate.

### Refuses rather than approximates

| Combination | Resolves to | Phase |
|---|---|---|
| FDA + NTI | `FDA_NTI_RSABE` | 2B |
| FDA + highly variable | `FDA_HVD_RSABE` | 2A |
| EMA + highly variable | `EMA_HVD_ABEL` | 2C |
| EMA + NTI + Cmax | `SpecificationRequired` — product decides | — |

### Validation state

**`IMPLEMENTED_UNVALIDATED`.** Two published `PowerTOST` cases reproduce — both
sample sizes exactly, power within 1.9 × 10⁻⁷ and 6.0 × 10⁻⁶ — which is a
tier-3 implementation cross-check. **No regulator worked dataset has been
reproduced**, so no method may be marked `VALIDATED` and nothing here may
support a submission. `tests/validation/` asserts both of those facts so the
gap cannot be forgotten. *(0.1.1 renamed this gap tier 1B, and added tier-1A
algorithm coverage which does not close it.)*

### Notable corrections made during Phase 1

- **Zero within-subject variance** divided by zero and would have produced a
  zero-width 90% interval — an emphatic pass claiming precision the data do not
  contain. Now refused. Found by the test suite, not by inspection.
- ~~**The HVD switching threshold is derived, not stored.**~~ **Reversed in
  0.1.1 — see above.** The measurement was right (`cv_to_log_sd(0.30)` is
  0.293560 against FDA's 0.294, and the 0.00044 gap decides the method for a
  real range of studies); the conclusion was not. 0.294 is the regulator's
  criterion, and this release derived it away.
- **"EMA NTI at 15% CV requires 96 subjects" was withdrawn.** It was stated as
  a fact about the regulation but was an engine output under an unrecorded
  scenario. Only the direction is now asserted: narrower limits cost subjects.
- **An assumed ratio on an acceptance boundary** now raises `NotPowerable` up
  front instead of iterating to a cap.

### Known gaps carried forward

1. The FDA guidance body has not been readable — every URL tried returned 404 or
   served a download rather than text. Tier-1**B** cases cannot be written
   without it. *0.1.1 note:* tier 1A is now covered by attestation at review,
   which is a different and lesser claim, recorded as such on every constant via
   `RegulatoryValue.verified_by`.
2. ~~Whether ICH M13A's twelve-per-group parallel rule governs an **FDA**
   parallel study is unconfirmed.~~ **Resolved in 0.1.1:** it does, scoped to
   M13A's dosage forms. The registry key gained a framework rather than gaining
   a global FDA constant.
3. Power uses the non-central t approximation; exact Owen's Q is a follow-up,
   and the difference must be documented rather than discovered.
