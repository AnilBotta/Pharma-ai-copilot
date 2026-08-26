# Changelog

`__version__` is bumped on any change that can alter a computed result. An
analysis record stores it, because "which version produced this number" is the
first question asked of a result years later.

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

### Tier 1B is still open, and now for a better reason

The guidance contains **no worked dataset** — no input values and no published
answer anywhere in 54 pages. It states the algorithm and gives SAS code.
Obtaining it closed tier 1A and could never have closed 1B. That needs a
different source, and the gap is no longer "we could not get the document".

182 tests pass, 2 skipped.

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
| sWR² = 0 | `estimable = False`, `swr` and `cv_wr` are **`None`**, not 0.0 |

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
- **`m` is counted, not assumed.** A sequence that contributed no surviving
  subject absorbs no degree of freedom and contributes no term. Using the
  design's `m = 3` regardless would understate df and inflate the variance.

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
