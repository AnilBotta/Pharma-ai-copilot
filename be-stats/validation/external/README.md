# External validation — be-stats against PowerTOST

**One command:**

```bash
docker build -t be-stats-validation validation/external
docker run --rm -v "$PWD/..:/work" be-stats-validation
```

Without Docker, the Python half still runs and every comparison reports
`SKIPPED`:

```bash
PYTHONPATH=src python validation/external/harness.py
```

---

## Status

**Tier 3 is PASSED for all three methods.** `18 passed, 0 failed, 0 skipped`.
The image builds, PowerTOST 1.5-7 runs, and the CI job fails on any skip — so a
green run means the comparisons genuinely happened.

**With one finding that is not a failure and is not noise. See below.**

### It took three attempts, and each failure was informative

The image went to CI unbuilt, because neither Docker nor R was available where
it was written.

1. **Failed after 3m24s** — `install.packages(..., dependencies = TRUE)`. `TRUE`
   also installs **Suggests**; PowerTOST suggests `emmeans`, whose chain reaches
   `s2`, which needs Abseil C++ and cmake. Three minutes spent failing on a
   geospatial library nothing here uses. Fixed to
   `c("Depends", "Imports")`.
2. **Failed after 1m27s** — PowerTOST 1.5-7 installed correctly, and the version
   check then rejected it: *wanted 1.5-7, got 1.5.7*. CRAN writes `1.5-7`; R's
   `package_version` normalises the separator. A string comparison fails on the
   exact version it asked for. Fixed to compare as versions.
3. **Green in 3m30s.**

Two things behaved correctly while failing, which was the design intent:
`warn = 2` turned the install warning into an error rather than letting a
half-installed environment through, and the report step refused to invent a
report it did not have.

## The finding: RSABE near the switching threshold

`RSABE-002-BOUNDARY-NEAR/p_be_sabec` agreed **within the declared tolerance**
and is **4.61 standard errors apart**:

```
py = 0.87055   r = 0.85817   diff = 1.238e-02   tol = 1.549e-02   [4.61 sigma]
```

Every other Monte Carlo comparison sits between 0.23 and 2.09 sigma — ordinary
sampling noise. This one is not.

It passed because the declared tolerance is evaluated at the worst case
`p = 0.5`, which is a legitimate bound fixed before any run, and is about 40%
wider than a comparison at `p ≈ 0.86` deserves. A real procedural difference
can sit inside it.

**The tolerance was not tightened in response.** Retroactively narrowing a
tolerance because of what it produced is how a tolerance stops meaning
anything. Instead the report now states each Monte Carlo comparison's distance
in units of its own standard error and flags anything beyond 4 as a
`FINDING` — visible on every run, changing no pass or fail, so a person
decides.

**What it might be, none of which is established:**

- PowerTOST's FDA setting uses `est_method = "ISC"` (intra-subject contrasts)
  per `reg_const("FDA")`, which need not estimate sWR identically to Appendix
  G's closed form near the switch.
- `power.RSABE`'s documentation says its linearized criterion follows the SAS in
  FDA's **progesterone** guidance; this package follows *Statistical Approaches*
  Appendix G. Same constants, different documents.
- The scenario sits just above the 30% classification CV, so a large share of
  simulated studies land either side of `sWR = 0.294` — the region where any
  difference in how sWR is estimated has the most leverage.

**This should be resolved before FDA HVD RSABE is relied on**, notwithstanding
that its tier 3 reads PASSED.

## Two Phase-1 numbers were wrong, and the real agreement is far better

Comparing at full precision rather than against rounded published figures:

| | Phase 1 recorded | Actually measured |
|---|---|---|
| ABE-001 power | 1.9 × 10⁻⁷ | **1.4 × 10⁻¹⁰** |
| ABE-002 power | 6.0 × 10⁻⁶ | **1.7 × 10⁻¹³** |

Phase 1 compared against values quoted to six decimal places, and its second
case additionally truncated the upper limit to `1.1111`. Neither figure was a
measurement of the method difference.

So be-stats' non-central t approximation agrees with PowerTOST's exact Owen's Q
to about **1e-10** — three orders better than the package's own documentation
claimed. The tolerances here are still the conservative ones; there was no
reason to tighten them on one run.

## The hierarchy this must not invert

```
FDA guidance          the source of the rule
   ↓
be-stats              an implementation of it
   ↓
PowerTOST             an independent numerical reproduction
```

PowerTOST is an **implementation oracle**, not a regulatory authority. A
disagreement is a finding to investigate — it could be either side, or a
difference in what each is computing. It is never a reason to change be-stats
to match. The rule comes from the FDA document; that is what the tier-1A cases
in `validation/phase1/algorithm/` are for.

## What can and cannot be compared

This is the finding that shaped the whole design.

`PowerTOST` 1.5-7 offers, for the FDA scaled procedures, only
**simulation-based power** functions. `power.RSABE` and `power.NTID` take an
assumed CV, ratio, design and sample size and return the probability of a BE
decision over `nsims` simulated studies. Neither takes a dataset, and neither
returns sWR, a treatment contrast or a criterion value.

`be-stats` does the opposite: it analyses datasets.

So there is **no layer at which the two can be compared directly** for RSABE or
NTI, and the comparison is made at the highest layer both expose:

| Kind | Methods | How |
|---|---|---|
| `direct` | ordinary ABE | both are closed form — sample size and power compared as numbers |
| `constant` | FDA settings | `reg_const("FDA")` against this package's verified constants |
| `monte_carlo_power` | RSABE, NTI | the Python side simulates studies, applies the be-stats criterion, and reports the proportion passing; PowerTOST reports its own empirical power for the same scenario |

Each case records what it **cannot** establish in `not_cross_checkable`, so a
gap is written down rather than left for someone to notice. The main ones:

- **The overall `p(BE)`, for both scaled methods.** RSABE's is the mixed
  procedure, which needs the unscaled branch; NTI's needs criterion (b). Both
  are Appendix C, which is not implemented — see `APPENDIX_C_FEASIBILITY.md`.
- **The Howe intermediates** `x`, `bound_x`, `y`, `bound_y`. PowerTOST does not
  expose them. They are checked against the FDA SAS instead, in the tier-1A
  case `FDA-HVD-RSABE-CRITERION-001`.
- **The sWR switching threshold.** PowerTOST's `CVswitch` is on the CV scale;
  FDA's 0.294 is on the sWR scale. They are adjacent quantities on different
  scales and conflating them is precisely the confusion an earlier release had
  to correct, so no comparison is attempted.

Also worth knowing: PowerTOST's `power.RSABE` documentation says its linearized
criterion follows the SAS in **FDA's progesterone guidance**. This package
follows the May 2026 *Statistical Approaches* Appendix G. They are believed to
be the same construction — the constants match — but they are not the same
document, and a disagreement should be read with that in mind.

## Layout

```
validation/external/
  Dockerfile                  pinned R + PowerTOST + Python
  install_r_packages.R        pinned installs, and refuses on a version mismatch
  environment.lock.json       the pins, and an honest note on their status
  run_powertost.R             the R half — runs PowerTOST, compares nothing
  simulate.py                 simulates studies and applies the be-stats criterion
  harness.py                  case model, comparison, tolerances, report
  cases/*.json                one definition per scenario, read by BOTH sides
  APPENDIX_C_FEASIBILITY.md   why the Appendix C oracle is still blocked
```

One case definition, two readers. There are deliberately no separate R and
Python fixtures: two hand-maintained copies of one scenario drift, and the
drift looks like a numerical disagreement.

## Tolerances

Every comparison carries `absolute_tolerance`, `relative_tolerance` and a
mandatory `tolerance_basis`. A case with an empty basis is rejected at load
time, and a test asserts the basis is long enough to be a reason rather than a
gesture.

The rule is that a tolerance is **derived before the comparison runs**, never
widened afterwards to accommodate what it produced:

- **Sample size** — exactly zero. It is an integer; a disagreement means the
  power curves cross the target at different `n`, which is real.
- **ABE power** — from the differences actually measured, 1.9 × 10⁻⁷ and
  1.7 × 10⁻⁷, set at a small multiple. Phase 1 recorded 6.0 × 10⁻⁶ for the
  second and blamed the approximation; re-measuring while building this harness
  showed the truncated `1.1111` limit was doing almost all of it. The external
  case uses the exact `1/0.9` and records the corrected figure.
- **Constants** — exact, or one bit for a shared division.
- **Monte Carlo power** — `4 × sqrt(p(1−p)(1/n₁ + 1/n₂))`, evaluated at the
  worst case `p = 0.5` so it does not depend on the answer:
  `4 × sqrt(0.25 × (1/20000 + 1/100000)) = 0.01549`.

## Version pins: two tiers, on purpose

`environment.lock.json` separates them.

**Enforced** — `PowerTOST`. Its version can change a number, and a different
version is a different oracle. `install_r_packages.R` stops the build if the
snapshot resolves anything else.

**Recorded** — R itself and the transitive packages. Their versions come from
the dated snapshot and are reported into `powertost_results.json` under
`.environment.r_packages_resolved`, so the report captures what actually ran
rather than what was asked for.

Pinning every transitive patch version as well would fail builds over bumps
that cannot affect a result — a check that produces noise instead of
confidence, and one somebody eventually relaxes for the wrong reason. The
lockfile says which tier each entry is in and why.

## When may tier 3 be marked PASSED?

Not on one agreeing case. `TIER3_REQUIRED_ROLES` in `harness.py` names the case
roles each method needs, and **every one must PASS** — not merely not fail,
which `SKIPPED` would satisfy:

| Method | Required roles |
|---|---|
| `standard_abe` | central, narrow_limits |
| `fda_hvd_rsabe` | central, boundary_near, high_variability |
| `fda_nti` | central, unequal_variability |

A central case can agree while the boundary is wrong; a balanced case can agree
while unbalanced weighting is wrong; an equal-variability NTI case says nothing
about the criterion that compares σWT with σWR. Tests assert that every
required role has a case, and that one passing role does not promote a method.

Even with all of them green, this is **tier 3 only**. It is an independent
implementation agreeing, not a regulator-published number reproduced. Tier 1B
remains open, and `VALIDATED` needs it.

## CI

`.github/workflows/validation-r.yml`, as an optional `validation-r` job:
manual, on changes to the engine or this directory, and weekly. Inside that job
a `SKIPPED` is a **failure** — there, a missing R means a broken image. The
distinction between skipped and passed only buys anything for local runs.
