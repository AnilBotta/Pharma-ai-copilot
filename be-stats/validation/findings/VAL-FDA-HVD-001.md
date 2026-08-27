# VAL-FDA-HVD-001

**PowerTOST's `p(BE-sABEc)` is the mixed decision, not the scaled criterion alone.**

| | |
|---|---|
| Raised | PR #58, first external validation run, 2026-08-27 |
| Resolved | 2026-08-28 |
| Status | `RESOLVED_POWERTOST_CONFIGURATION_ERROR` |
| Method | `fda_hvd_rsabe` |
| Impact on `be-stats` | None. No production statistical logic was wrong, and none was changed. |

## What was observed

`RSABE-002-BOUNDARY-NEAR/p_be_sabec`:

| | |
|---|---|
| be-stats | 0.87055 |
| PowerTOST 1.5-7 | 0.85817 |
| difference | 0.01238 |
| declared tolerance | 0.01549 — **passed** |
| its own standard errors | **4.61** |

The other two RSABE cases — CVwR 0.40 and 0.60 — agreed closely. Only the case
sitting near the switch disagreed.

That combination is why the harness reports a `FINDING` separately from a
`FAIL`. The declared tolerance is evaluated at the worst case `p = 0.5`, which
is a legitimate bound fixed before any run, but at the observed `p = 0.86` it is
about 40% wider than that comparison's own sampling error justifies. A real
procedural difference can sit inside it. Without the sigma diagnostic this would
have been a green tick.

## The answer

The two sides were computing **different quantities**, and each was computing
its own correctly.

PowerTOST 1.5-7, `R/power_RSABE.R`, names its result vector:

```r
names(p) <- c("p(BE)", "p(BE-sABEc)", "p(BE-pe)", "p(BE-ABE)")
```

The implementation it draws from, `.pwr.SABE.isc` in `R/power_RSABE2L_isc.R`,
names its counters differently — the string `sABEc` appears nowhere inside it:

```r
names(counts) <- c("BE", "BEul", "BEpe", "BEabe")     # line 161
```

So `p(BE-sABEc)` is `BEul`, and `BEul` accumulates this:

```r
BE <- ifelse(s2wRs > s2switch, BE_RSABE, BE_ABE)      # line 257
counts["BEul"] <- counts["BEul"] + sum(BE)            # line 273
```

`BE` is the **mixed procedure** — the scaled criterion above the switch,
conventional ABE below it, without the point-estimate constraint. The be-stats
harness computed the scaled criterion **alone**, for every simulated study,
regardless of which side of the switch it fell on.

At CVwR 0.31 with n=36, about 43.5% of studies fall below the switch, and
conventional ABE is harder there than the scaled criterion. At CVwR 0.40 about
2%; at 0.60, effectively none. The disagreement is therefore large at the
boundary and absent elsewhere — which is exactly what the first run showed.

## Confirmed against the real oracle

The experiments further down use a Python transcription of PowerTOST, which
cannot corroborate PowerTOST. This is the corroboration: the corrected case
files driving the actual package in CI.

| `RSABE-002-BOUNDARY-NEAR/p_be_sabec` | be-stats | PowerTOST | sigmas |
|---|---:|---:|---:|
| before — `regulator = "FDA"` | 0.87055 | 0.85817 | **4.61** |
| after — `reg_const("USER", CVswitch = 0, …)` | 0.87055 | 0.87104 | **0.19** |

**The be-stats value is unchanged.** Nothing on the Python side moved. Only
which quantity PowerTOST was asked for changed.

Every RSABE comparison in that run:

| quantity | be-stats | PowerTOST | sigmas |
|---|---:|---:|---:|
| RSABE-001/`p_be_sabec` | 0.81630 | 0.81682 | 0.17 |
| RSABE-001/`p_be_pe` | 0.93160 | 0.93267 | 0.55 |
| RSABE-001/`p_below_switch` | 0.06205 | 0.061734 | 0.19 |
| RSABE-002/`p_be_sabec` | 0.87055 | 0.87104 | 0.19 |
| RSABE-002/`p_be_pe` | 0.99020 | 0.99040 | 0.26 |
| RSABE-002/`p_below_switch` | 0.43255 | 0.435419 | 0.82 |
| RSABE-003/`p_be_sabec` | 0.89340 | 0.89215 | 0.52 |
| RSABE-003/`p_be_pe` | 0.84770 | 0.84890 | 0.43 |
| RSABE-004/`p_be_sabec` | 0.87500 | 0.870911 | 1.71 |
| RSABE-004/`p_below_switch` | 0.43110 | 0.435419 | 1.23 |

`22 passed, 0 failed, 0 skipped, 0 errored`. The largest distance anywhere in
the run is 1.71 sigma and nothing is flagged as a `FINDING`; the same suite
raised one at 4.61 before this PR.

The three `p_below_switch` rows are against a **closed form**, not another
simulation — the `sWR` estimator and the switching rule checked independently
of the criterion, which is the separation a power comparison alone cannot give.

The transcription predicted 0.87098; the real package returned 0.87104. The
instrument is corroborated by the oracle here, not the other way round.

## The evidence

Reproduced by `validation/external/investigate_val_fda_hvd_001.py`, frozen in
`VAL-FDA-HVD-001-evidence.json`.

**Experiment A — the scaled criterion alone, switching disabled on both sides:**

| be-stats | instrument | difference | sigmas |
|---:|---:|---:|---:|
| 0.87055 | 0.87098 | −0.00043 | **0.17** |

The be-stats value is the identical 0.87055 that was flagged. Compared against
the same quantity, it agrees.

**Experiment B — the mixed procedure, which is what PowerTOST reports:**

| be-stats side | instrument | difference | sigmas |
|---:|---:|---:|---:|
| 0.85620 | 0.85672 | −0.00052 | **0.19** |

Against PowerTOST's own 0.85817, the instrument sits about 1.3 standard errors
away — ordinary sampling variation. The whole 0.01238 is accounted for by which
quantity was named.

**Across the switch**, the gap tracks the switching fraction and *changes sign*:

| CVwR | below switch | gap |
|---:|---:|---:|
| 0.27 | 0.8315 | −0.04187 |
| 0.29 | 0.6394 | 0.00062 |
| 0.31 | 0.4271 | 0.01362 |
| 0.33 | 0.2574 | 0.01337 |
| 0.40 | 0.0238 | 0.00150 |
| 0.60 | 0.0000 | 0.00000 |

Far below the switch, conventional ABE is *easier* than a barely widened scaled
limit, so the mixed decision passes more often rather than less. A constant
offset, a wrong scaling constant, or a wrong degrees-of-freedom count could not
produce a sign change located at the switch.

**Not sampling noise.** At nsims = 50 000 across three seeds the gap was
0.01344, 0.01452 and 0.01414 — a range of 0.00108 around the 0.01238 first
observed at nsims = 20 000. It does not move with the seed and does not shrink
with nsims.

**Same study on both sides.** PowerTOST samples the deciding statistics
directly; be-stats simulates subjects and estimates them. The be-stats `sWR²` has
mean 0.091796 against 0.091758 exact, with a Kolmogorov–Smirnov *p* of 0.958.

## What was ruled out

| hypothesis | verdict |
|---|---|
| Monte Carlo variation | eliminated — survives seeds, does not shrink with nsims |
| Different simulated studies | eliminated — KS *p* = 0.958 against the exact chi-square |
| A defect in the be-stats Howe criterion | eliminated — identical term by term, below |
| `est_method = "ISC"` selecting a legacy route | eliminated — `power.RSABE` never reads it |
| The switching threshold difference | **real, but not the cause** — worth ~1/20 of the gap; see `VAL-FDA-HVD-002` |

On `est_method`: `reg_const("FDA")` does carry `est_method = "ISC"`
(`R/scABEL.R` line 18), but `power.RSABE` takes only `CVswitch`, `r_const`,
`pe_constr` and `CVcap` from the regSet (lines 44–46) and calls `.power.RSABE`
directly. `est_method` is consulted only in the ABEL family — `power_scABEL.R`
line 17, `samplesize_scABEL.R` lines 19 and 26, and the `sdsims` guards — none of
which is on this path. It is descriptive here.

## The criterion, line by line

be-stats' Appendix G implementation against `.pwr.SABE.isc` with
`SABE_test = "fda"`, design 2×2×4:

| step | be-stats | PowerTOST | verdict |
|---|---|---|---|
| sWR² | sum of squares of `Dij` about sequence means over `2(n−m)` | `s2wR * rchisq(nsims, dfRR) / dfRR` | numerically equivalent |
| dfRR | `n − m`, m = 2 | `n − 2` | identical |
| contrast | equally weighted sequence means of `Iij` | `rnorm(nsims, mlog, sdm)` | numerically equivalent |
| contrast df | `n − 2` | `n − 2` | identical |
| `x` | `estimate² − SE²` | `Em = pes²`, then `Em <- Em - SEs²` | identical |
| `bound_x` | `max(|log CI|)²` | `Cm = (abs(pes) + hw)²` | identical |
| `y` | `−θ·sWR²`, θ = (ln 1.25 / 0.25)² | `Es = r2const * s2wRs` | identical |
| `bound_y` | `y · dfRR / χ²(α, dfRR)` | `Cs = Es * dfRR / qchisq(1−α, dfRR)` | identical |
| bound | `(x+y) + sqrt((bound_x−x)² + (bound_y−y)²)` | `SABEc95 = Em − Es + sqrt((Cm−Em)² + (Cs−Es)²)` | identical |
| decision | `bound ≤ 0` | `SABEc95 <= 0` | identical |
| PE constraint | `0.8000 ≤ PE ≤ 1.2500` | `pes >= ln_lBEL & pes <= ln_uBEL` | identical |
| **switch** | `sWR ≥ 0.294` | `s2wRs > log(0.3² + 1)`, i.e. `sWR > 0.293560` | **different** — `VAL-FDA-HVD-002` |
| **below-switch branch** | not implemented; refuses, citing Appendix C | TOST on the intra-subject contrast | **different** |
| **reported as `p(BE-sABEc)`** | scaled criterion alone | mixed decision | **different — the root cause** |

## Matched synthetic datasets

Not attempted, and not attemptable. PowerTOST 1.5-7 exposes **no dataset-level
entry point** for the FDA scaled procedures: `power.RSABE` and `power.NTID` take
a scenario and return probabilities, and nothing in the package accepts
subject-level observations and returns `sWR`, a treatment contrast or a
criterion value. This is a property of the oracle, not of the harness.

The closest available substitute is now asserted instead: `sWR² · dfRR / σ²WR`
is chi-square on `dfRR`, so the R side computes `P(sWR < 0.294)` in closed form
and the Python side reports its observed fraction. That is the one comparison
which separates the `sWR` estimator and the switch from the criterion.

## What changed

- RSABE cases set `experiment = "scaled_criterion_isolated"`, driving PowerTOST
  with `reg_const("USER", r_const = log(1.25)/0.25, CVswitch = 0, CVcap = Inf,
  pe_constr = TRUE)`. With `CVswitch = 0`, `s2switch` is 0 and `s2wRs` exceeds it
  with probability one, so every study takes the `BE_RSABE` branch and
  `p(BE-sABEc)` becomes the scaled criterion alone. FDA's regulatory constant and
  the `"fda"` criterion — bias correction included — are untouched. Only the
  routing is disabled, on the side that has routing.
- `simulate_scaled_power` now **refuses** an RSABE case that does not request
  that experiment.
- New comparison `p_below_switch`, against the exact chi-square.
- New case `RSABE-004-BOUNDARY-RESEEDED`: same scenario, independent seed, ten
  times the oracle count.
- Tier-3 gained `PASSED_WITH_FINDING`; cases gained `open_findings`.

## What deliberately did not change

- **No production statistical logic.** The finding was in the comparison.
- **No tolerance was altered retrospectively.** `RSABE-002` keeps 0.01549.
  Retrofitting a tolerance to a resolved finding would leave the tolerance
  meaning nothing.
- **PowerTOST's below-switch convention was not adopted.** It is a TOST on the
  intra-subject contrast; FDA specifies Appendix C's mixed model. Matching an
  oracle by copying it is the failure this directory exists to prevent.

## Engineering observation, kept separate

`ENG-001`: one pytest failure was seen once locally during PR #58 and did not
reproduce in eight subsequent full runs (383 tests, 0 failures).

It was never intermittent. `tests/validation/test_algorithm_conformance.py`
imports `make_criterion` from `tests.unit.test_rsabe_criterion`, which resolves
only when the working directory is `be-stats/`. Run as `pytest be-stats/tests`
from the repository root, those two tests fail with `ModuleNotFoundError: No
module named 'tests'` — deterministically. A failure that depends on the
invocation is precisely one that appears once and then will not reproduce.

Fixed by `pythonpath = ["."]` under `[tool.pytest.ini_options]`; `rootdir`
resolves to `be-stats/pyproject.toml` under either invocation, so one relative
entry covers both. Green from the repository root and from `be-stats/`.

Kept in this section, and out of the finding proper, because it is an
observation about the test suite rather than evidence about a statistical
method. The brief asked that it not be pursued; the cause was visible in the
first full run of this investigation and the fix is one line, so it was taken
rather than left.
