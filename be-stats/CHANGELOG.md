# Changelog

`__version__` is bumped on any change that can alter a computed result. An
analysis record stores it, because "which version produced this number" is the
first question asked of a result years later.

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
tier-3 implementation cross-check. **No tier-1 regulator worked example has
been reproduced**, so no method may be marked `VALIDATED` and nothing here may
support a submission. `tests/validation/` asserts both of those facts so the
gap cannot be forgotten.

### Notable corrections made during Phase 1

- **Zero within-subject variance** divided by zero and would have produced a
  zero-width 90% interval — an emphatic pass claiming precision the data do not
  contain. Now refused. Found by the test suite, not by inspection.
- **The HVD switching threshold is derived, not stored.** `cv_to_log_sd(0.30)`
  is 0.293560, against the commonly published 0.294 — a difference of 0.00044,
  which decides the method for a real range of studies. An AST-level test
  prevents 0.294 being reintroduced as a numeric literal. *Which of the two is
  normative is an open question for Phase 2A.*
- **"EMA NTI at 15% CV requires 96 subjects" was withdrawn.** It was stated as
  a fact about the regulation but was an engine output under an unrecorded
  scenario. Only the direction is now asserted: narrower limits cost subjects.
- **An assumed ratio on an acceptance boundary** now raises `NotPowerable` up
  front instead of iterating to a cap.

### Known gaps carried forward

1. The FDA guidance body has not been readable — every URL tried returned 404.
   Tier-1 golden cases cannot be written without it.
2. Whether ICH M13A's twelve-per-group parallel rule governs an **FDA** parallel
   study is unconfirmed, so no FDA parallel floor is registered. A study asking
   for one is told there is no confirmed minimum rather than given the EMA
   figure.
3. Power uses the non-central t approximation; exact Owen's Q is a follow-up,
   and the difference must be documented rather than discovered.
