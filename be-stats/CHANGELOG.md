# Changelog

`__version__` is bumped on any change that can alter a computed result. An
analysis record stores it, because "which version produced this number" is the
first question asked of a result years later.

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
