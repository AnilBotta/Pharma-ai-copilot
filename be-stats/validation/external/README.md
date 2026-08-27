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

## Status, plainly

**Nothing here has been cross-checked yet.** Neither Docker nor R was available
where this was written, so the image has never been built and
`run_powertost.R` has never executed. Every comparison currently reports
`SKIPPED` and every method's tier 3 is `PENDING`.

That is the correct output for this state, and it is the reason `SKIPPED` and
`PASS` are different words. A harness that reported green because it had
nothing to compare would be worse than no harness.

What *has* been run: the Python side of every case, and 29 tests of the harness
itself in the ordinary suite.

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
