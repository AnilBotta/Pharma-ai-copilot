# Validation

**Status: not validated. This engine must not be used to support a regulatory
submission.**

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
| 1 | Regulator-published worked method or example — FDA final guidance, including the appendices for NTI and highly variable drugs | Highest. This is what the method *is* |
| 2 | Published textbook or reference table | Independent numerical validation |
| 3 | `PowerTOST` reference output / test fixture | **Implementation oracle only** |
| 4 | Simulations generated here | Supplemental verification only |

**PowerTOST is not the regulatory authority.** It is an independent
implementation to cross-check against. Its usefulness is partly that its own
validation traces back to published tables — its `ct5.1` fixture corresponds to
the classical 2×2 crossover at 80–125% by exact calculation, derived from
Hauschke, Steinijans & Pigeot, and its `/tests` scripts exist to be compared
against those tables. That makes it an excellent tier-3 oracle and still not a
tier-1 source.

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

## Two claims retracted

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

---

## Mathematical versus regulatory sample size

These are different kinds of statement and the engine keeps them apart:

```
mathematical_n   what the power calculation requires
regulatory_n     what the regulator requires regardless
recommended_n    max of the two, rounded up to an even total
```

FDA: not fewer than **12** evaluable subjects in a PK BE study, and at least
**24** for a highly variable drug product. Supplied with citations at review.

**EMA's minimum is deliberately unset.** It was not supplied with a citation, so
`regulatory_minimum_n` is `None` and `regulatory_minimum_basis` says so. An
unconfirmed constant that looks like a confirmed one is the failure this
package is organised to avoid. Confirming it is an open item.

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

Pending, and belonging to Phase 2 because they concern replicate designs:

- [ ] singular mixed-model covariance structure
- [ ] missing reference replicates
- [ ] a subject with only one usable reference observation where sWR needs
      replication

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
NTI **AUC**; product-specific overrides per endpoint.

**Resolved but not implemented** — each raises `NotImplementedMethod` rather
than returning something plausible:

| Combination | Method | Phase |
|---|---|---|
| FDA + NTI | `FDA_NTI_RSABE` — fully replicated, σw0 = 0.10, Δ = 1/0.9, variance ratio limit 2.5, plus unscaled 80–125% | 2B |
| FDA + highly variable | `FDA_HVD_RSABE` — σw0 = 0.25, switch at sWR ≥ 0.294, point estimate constrained to 80–125% | 2A |
| EMA + highly variable | `EMA_HVD_ABEL` — expanding limits; a different procedure from RSABE, not a relabelling | 2 |

**Requires specification** — `EMA + NTI + Cmax` raises `SpecificationRequired`.
EMA narrows Cmax only where Cmax itself matters for safety or efficacy, decided
per product: ciclosporin narrows both AUC and Cmax; colchicine narrows AUC and
leaves Cmax at 80.00–125.00. Neither default is safe, so the caller supplies a
`ProductOverride` from the applicable product-specific guidance.
