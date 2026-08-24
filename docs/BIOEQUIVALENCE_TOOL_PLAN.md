# A bioequivalence statistics module for the PDP platform

Draft plan for discussion. Nothing here is built yet.

---

## 1. Context

The stage-gate platform tracks *whether* work is done. It has no opinion on
whether the work is statistically sound. For a generic or a 505(b)(2), the
single most consequential number in the whole development programme is a
bioequivalence verdict — and today that lives in a statistician's SAS output,
outside the system, unlinked to the gate that depends on it.

The proposal is a statistics module that (a) tells a team which BE approach
their product actually requires, (b) sizes the study, (c) runs the analysis
reproducibly, and (d) files the result as gate evidence with a full audit trail.

**One correction before anything is scoped.** The brief described three live
approaches — average, individual and population BE — citing the 1997/2001
framework. That framework was **replaced on 28 May 2026**. FDA issued a new
final *Statistical Approaches to Establishing Bioequivalence*, finalising the
December 2022 draft and superseding February 2001. Both the Federal Register
notice and RAPS's summary describe the new guidance as covering **average BE and
population BE**, reference-scaled average BE for NTI and highly variable drugs,
and **modified population BE** for in vitro work — with **individual BE absent
from both summaries**.

That materially shrinks the build. Individual BE is the hardest of the three to
implement and, on this evidence, is not something anyone is currently filing.
See §11 — this needs confirming against the guidance body before it is ruled out
for good.

---

## 2. What the regulations actually require now

### 2.1 The approaches that are live

| Approach | Compares | Where it is used |
|---|---|---|
| **Average BE (ABE)** | Means only — 90% CI of the T/R ratio within 80.00–125.00% | The workhorse. Systemically-acting orals, Cmax / AUC |
| **Reference-scaled ABE (RSABE)** | Mean, with limits widened in proportion to reference within-subject variability | Highly variable drugs (CV<sub>WR</sub> ≥ 30%). Requires a replicate design |
| **RSABE for NTI** | Mean *and* a variance comparison | Narrow therapeutic index drugs. **Three** criteria must all pass |
| **Population BE (PBE)** | Total variance — mean shift *and* change in variability | In vitro endpoints for locally-acting products where there is no useful plasma curve |
| **Modified (one-sided) PBE** | As PBE, but one-sided on the mean | Specific in vitro endpoints — e.g. drug in small particles |
| ~~Individual BE (IBE)~~ | Subject-by-formulation interaction | Not in the 2026 summaries. Treat as out of scope pending confirmation |

The NTI case is the one people get wrong. A test product must pass **all three**:
RSABE scaled to reference variability; **unscaled** ABE within 80.00–125.00%;
and the upper bound of the 90% CI on σ<sub>WT</sub>/σ<sub>WR</sub> ≤ **2.5**. A
tool that reports only the first has told a team the opposite of the truth.

### 2.2 Why particle size drives this

For orally inhaled and nasal drug products the drug acts locally, so there is no
meaningful concentration–time profile to compare. Regulators fall back on in
vitro surrogates, and particle/droplet size distribution is the dominant one
because it determines deposition site and therefore efficacy. A test product
must match the reference's **whole distribution**, not its average — which is
precisely why a variance-aware criterion (PBE) is used instead of a mean
comparison.

### 2.3 The nasal spray in vitro battery

FDA's draft *Bioavailability and Bioequivalence Studies for Nasal Aerosols and
Nasal Sprays for Local Action* (1999, reissued as a level 1 draft in 2003) is
**still draft and has not been withdrawn**. It specifies eight in vitro assays:

| # | Assay | Statistical treatment |
|---|---|---|
| 1 | Single actuation content (SAC) | PBE, at beginning and end of unit life |
| 2 | Droplet size distribution (laser diffraction) | PBE on D50 and span |
| 3 | Drug in small particles (< 9 µm) | **One-sided** PBE — test passes if similar to *or smaller than* reference |
| 4 | Spray pattern | PBE on ovality and area |
| 5 | Plume geometry | **No PBE** — equivalent if within 90–111% of reference |
| 6 | Drug particle size distribution (microscopy) | PBE on D50 and span |
| 7 | Priming and repriming | PBE |
| 8 | Dissolution (where applicable) | Profile comparison, not PBE |

Note assays 3 and 5 — a tool that applies two-sided PBE uniformly across the
battery produces wrong verdicts on two of the eight.

### 2.4 The PBE criterion

Structurally, the criterion penalises both a mean shift and an increase in
variability, scaled against the reference variance or a regulatory constant,
whichever is larger:

```
            (μT − μR)² + σ²TT − σ²TR
θ  =  ─────────────────────────────────
              max(σ²TR , σ²T0)
```

In practice the decision is made on the **linearised** form, and equivalence is
concluded when the **upper 95% confidence bound is below zero**:

```
η = (μT − μR)² + σ²TT − σ²TR − θP · max(σ²TR , σ²T0)   ≤ 0
```

The bound is obtained by **bootstrap**, which is why the engine must be
seed-controlled to be reproducible (§6).

> **The constants are deliberately not written here.** θ<sub>P</sub>,
> σ<sub>T0</sub> and the mean-difference limit differ by product class and
> sometimes by individual PSG — the budesonide PSG limit, for instance, is
> derived from allowing a 10% mean shift and a doubling of variance (0.01 →
> 0.02). They must be read out of the applicable guidance or PSG and entered as
> **configuration**, never hard-coded from memory. See §11.

### 2.5 FDA and EMA diverge

For the same nasal product, **FDA recommends PBE and EMA recommends ABE**. Any
tool serving both markets must run both and present them separately. Presenting
one number as "the" BE result is wrong for at least one of the two filings.

### 2.6 Known weaknesses worth surfacing, not hiding

PBE is criticised in the literature for poor statistical power once variability
rises (practically, from around 15% CV), which inflates the number of batches
and units required. Between-Batch Bioequivalence (BBE) has been proposed as an
alternative that compares the mean difference against reference *between-batch*
variability. A tool that shows the power curve alongside the verdict is far more
useful than one that only says pass/fail — the team's real question is usually
"how many units do we need to run", not "did this batch pass".

---

## 3. Which studies are feasible

Ordered by how well-specified the statistics are and how much the platform can
genuinely help.

**Straightforwardly feasible.**
- ABE, 2×2 crossover and parallel designs — TOST, 90% CI on log-transformed
  Cmax / AUC. Unambiguous, universally used, easy to validate against published
  datasets.
- Sample size and power for ABE.
- RSABE for HVD and the three-criteria NTI variant, on replicate designs
  (2×2×4, 2×2×3, 2×3×3).
- f2 similarity factor for dissolution profiles, including the bootstrap f2
  variant for variable profiles.

**Feasible, and the real differentiator.**
- PBE and one-sided PBE for the non-profile in vitro endpoints in §2.3, with
  bootstrap confidence bounds and per-endpoint configurable constants.
- Study sizing for in vitro BE — how many batches, how many units per batch —
  which is where teams actually lose money.

**Feasible but do later.**
- Cascade impactor **profile** comparison (grouped stages, chi-square ratio
  statistic and the EMA alternatives). The methodology is contested and the
  payoff is narrower.
- Virtual BE / PBPK simulation (the GastroPlus space). A different discipline;
  do not conflate it with this module.

**Do not build.**
- Individual BE, unless §11 shows it is still required somewhere.
- Anything that replaces a qualified statistician's sign-off. See §6.

---

## 4. What other software does, and where the gap is

| Tool | What it is used for | Notes |
|---|---|---|
| **SAS** (`PROC GLM`, `PROC MIXED`) | The de facto standard for the BE analysis itself | What FDA reviewers expect. `MIXED` for unbalanced/replicate designs |
| **Phoenix WinNonlin** (Certara) | The de facto standard for NCA — deriving Cmax/AUC from concentration data — with BE modules | ~30 years, explicitly trusted by FDA, PMDA, MHRA |
| **R** — `PowerTOST`, `replicateBE`, `sasLM`, `nlme` | Power/sample size (incl. `sampleN.RSABE`), replicate-design BE | Free, auditable, widely used as a cross-check. **`PowerTOST` ships reference datasets in `/tests` specifically so users can validate it** — a model worth copying |
| **PKanalix** (Lixoft/Simulations Plus) | NCA + BE, published as validated against WinNonlin and SAS | Cross-validation against the incumbents is the credibility play |
| **GastroPlus** | In silico / virtual BE via PBPK | Adjacent discipline, not this module |
| **Malvern MDRS** | Morphologically-directed Raman — particle size *and* chemical identity for nasal sprays | Instrument side; generates the data this module consumes |

**The gap.** Every mature tool above is strong on **in vivo PK** bioequivalence.
Almost none of them package the **in vitro PBE battery** for OINDPs as a guided
workflow — teams assemble it from bespoke SAS macros and spreadsheets, per
product, per PSG. That is the underserved space, it is exactly where the brief
is pointing, and it is where this platform already has the surrounding
machinery (evidence, controlled documents, audit) that a bare statistics package
does not.

Two secondary gaps worth taking: nobody ties the analysis to a **stage gate**,
and nobody makes the **FDA-vs-EMA divergence** visible in one place.

---

## 5. What to build, in order

**Phase 1 — the engine and its proof.** A pure, dependency-light Python module:
ABE/TOST, power and sample size. No UI. Every estimator ships with a reference
dataset and a known-correct answer, cross-checked against R in CI (§10).

**Phase 2 — RSABE.** HVD scaling and the NTI three-criteria gate, on replicate
designs. The NTI verdict must show all three sub-results, never a single
pass/fail.

**Phase 3 — in vitro PBE.** The §2.3 battery. Per-endpoint configuration of
θ<sub>P</sub>, σ<sub>T0</sub>, one- vs two-sided, and the 90–111% plume rule.
Seeded bootstrap. This is the differentiator.

**Phase 4 — the platform integration.** A BE analysis becomes a first-class
evidence type attached to a gate requirement, producing a versioned statistical
report as a controlled document.

**Phase 5 — study designer.** Given product class and target, recommend the
approach, the design, and the batches/units needed, with a power curve. This is
the part that saves real money.

**Phase 6 — dissolution.** f2, bootstrap f2, profile comparison.

---

## 6. Three rules the module must not break

**The model never computes a statistic.** The LLM explains what a criterion
means, which guidance applies, and what a result implies. Every number comes
from the deterministic engine. This is the same rule that already governs
citations in this codebase — *never allow the language model to create a
citation that does not exist in the evidence table* — extended to arithmetic. An
invented BE verdict is worse than an invented citation.

**Every analysis is reproducible bit-for-bit.** Bootstrap means a seed. An
analysis record stores: engine version, input dataset hash, every configuration
constant, the seed, and the outputs. Re-running it two years later during an
inspection must give the identical answer, or the record is worthless.

**The tool never says "bioequivalent" on its own authority.** It reports the
criterion, the bound, the inputs and the applicable guidance, and it names what
it did *not* assess. A verdict is a regulatory conclusion made by a qualified
person; the tool produces the evidence for that person. This is the same posture
the platform already takes with the readiness engine — a percentage never
unlocks a gate.

---

## 7. Architecture

**The backend has no scientific stack.** `backend/requirements.txt` has no
numpy, scipy, statsmodels or pandas.

**Correction to an earlier draft of this plan.** That draft recommended running
analyses "in the existing worker, not the request path", to keep a heavy
scientific stack out of the API function. That reasoning was wrong:
`vercel.json` declares **exactly one function**, `api/index.py`, and the worker
runs *inside it* via `/api/worker/tick` triggered by `pg_cron`. There is no
second host. Moving work to the worker does not move it out of the bundle.

**The stats engine should be a standalone, independently versioned package** —
and the reason is change control, not size. Under GAMP 5 you validate a system
in a defined configuration; a change requires impact assessment. If the engine
ships inside the web application, **every front-end release is a change to a
validated system**. Separating it means a React edit cannot invalidate a
statistical qualification.

That gives:

```
be-stats/                     ← standalone, versioned, independently validated
  src/be_stats/               ← pure computation, no web/database imports
  tests/                      ← unit + property tests
  validation/                 ← reference datasets, expected values, R cross-check
```

consumed by the platform as a pinned dependency (or a small service, decided at
Phase 4 — see below).

**Phase 1 is unblocked by the deployment question.** The engine and its
validation run in CI, not on Vercel. Whether numpy/scipy fit inside the 250 MB
function limit alongside langgraph, openai and psycopg is a **Phase 4** question
and must be **measured on a real deployment**, not estimated. If they do not
fit, the fallback is a separate small service for the engine — which the
change-control argument above already favours.

**Implementation.** Use numpy and scipy rather than hand-rolling special
functions. For submission-grade work "we used scipy, and here is our validation
against published reference values" is a far easier position to defend to an
auditor than "we implemented our own incomplete beta function". The mixed model
for replicate designs (Phase 2) is where a real library earns its keep.

---

## 8. How it fits the stage-gate model

This is the part no competing tool has, and it needs no new concepts:

- **Requirement** — "Demonstrate in vitro BE against the RLD" sits at the gate
  where it belongs, with `required_evidence_type: "data"`.
- **Evidence** — a completed analysis run attaches to that requirement, exactly
  as a research run does today. Changing the analysis supersedes any approval,
  which the evidence model already enforces.
- **Controlled document** — the statistical report enters the register,
  versioned, approved, with segregation of duties intact: whoever ran the
  analysis is not whoever approves it.
- **Audit** — every run, every configuration change, every re-run is already
  covered by `private.record_audit_event`.
- **Manager Agent** — can explain which criterion applies and why, and can
  *dispatch* an analysis for confirmation, but cannot approve its result. The
  proposal/confirmation mechanism already exists for exactly this.

---

## 9. Who this is for

- **Formulation scientist** — "how many units do I need to run?"
- **Biostatistician** — needs the method, the assumptions and the raw output,
  and needs to be able to disagree with it.
- **Regulatory affairs** — needs to know FDA and EMA differ here, and needs a
  report that can be attached to a submission dossier.
- **CEO / programme lead** — needs to know whether the gate can open.

The UI should serve the first and last without ever misleading the middle two.

---

## 10. Verification and validation

**Engineering verification** (every PR):
- Reference datasets with known answers for every estimator — FDA guidance
  worked examples, `PowerTOST`'s own test fixtures, published datasets.
- **Independent cross-implementation.** Compute the same result in R and assert
  agreement to a stated tolerance in CI. Two implementations that agree is the
  only cheap evidence that either is right.
- Property tests: PBE reduces to something ABE-like when variances are equal;
  wider test variance never improves the verdict; a one-sided criterion is never
  stricter than its two-sided counterpart.
- Reproducibility test: same inputs + same seed ⇒ identical outputs.

**Regulatory validation** (before anything is used to support a filing):
- The module is a computerised system. If its output supports a submission it
  needs documented IQ/OQ/PQ, a validation protocol and report, change control,
  and the audit trail the platform already provides.
- Until that exists, the module must be labelled — in the UI, not just in
  documentation — as **development decision-support, not a submission-ready
  analysis**. Shipping it unlabelled is the single biggest risk in this plan.

---

## 11. What I could not verify, and must be checked first

Honest gaps in the research behind this document:

1. **The FDA guidance body.** The Federal Register notice and RAPS summary were
   readable; the guidance PDF itself returned 404 at every URL tried, and the
   PMC paper was behind a CAPTCHA. **Everything in §2.1 about individual BE
   being dropped rests on two secondary summaries, not the primary text.** Get
   the PDF and confirm before scoping IBE out permanently.
2. **All numeric constants.** θ<sub>P</sub>, σ<sub>T0</sub> and the
   mean-difference limits for in vitro PBE are *not* stated in this document
   because I could not verify them from a primary source. They must come from
   the guidance and the applicable PSG. Do not let anyone — including me — put a
   remembered number into the engine.
3. **Bootstrap specifics** — replicate count and which percentile — likewise
   unverified.
4. Whether the 2026 guidance changes the nasal spray in vitro battery, given it
   absorbed material "previously included in product-specific guidances".

---

## 12. Decisions taken

| Question | Answer | What follows |
|---|---|---|
| Build order | **Phase 1 first** — ABE/TOST engine, power and sample size, with its validation harness | Product-class choice (§12.1) defers to Phase 3 |
| Grade | **Submission-grade *and* decision-support** | The expensive answer. See §12.2 |
| Markets | **FDA + EMA** | Both must be computed and shown separately from Phase 1 onward. See §12.3 |
| Statistician review | **Available** | Reference datasets and method choices go to review *before* the engine is trusted |

### 12.1 Still open, but not blocking

Which product class leads at **Phase 3** — nasal spray / OINDP (where PBE
matters and the market gap is) or orals (larger but crowded). Phase 1 is
product-class agnostic, so this can wait.

### 12.2 What "submission-grade" actually costs

This is the answer with the largest hidden cost, and it should be visible now
rather than discovered at Phase 4. Submission-grade means the engine is a
**computerised system supporting a regulatory decision**, which brings:

- **Validation lifecycle** — Validation Plan, User Requirements Specification,
  Functional Specification, **IQ / OQ / PQ** protocols and reports, and a
  **traceability matrix** linking each requirement to the test that proves it.
- **21 CFR Part 11** — audit trail, record integrity, and electronic signature
  controls where a result is signed. The platform already provides the audit
  trail and append-only records; signatures are the gap.
- **Change control** — every engine change needs impact assessment and, for
  anything touching a calculation, revalidation of the affected scope. This is
  the reason for the standalone package in §7.
- **Frozen, versioned outputs** — an analysis must reproduce identically years
  later. Engine version, input hash, every constant, and the bootstrap seed are
  part of the record.
- **Supplier/tool qualification** — numpy, scipy and any R used for
  cross-checking need documented justification.

Two consequences worth deciding early:

1. **The decision-support build is the same engine with a different label.** Do
   not build twice. Ship one engine; gate the *claim* — an analysis is marked
   "development decision-support" until it is run under a qualified
   configuration, and the UI says which it is. Every result carries its grade.
2. **Budget the validation work as its own stream**, roughly comparable to the
   engineering. If that is not acceptable, decision-support only is a legitimate
   product and a quarter of the work.

### 12.3 FDA and EMA diverge inside Phase 1, not just Phase 3

The earlier draft treated the FDA/EMA split as a Phase 3 concern (PBE vs ABE for
nasal). It is not — it reaches into the ABE workhorse itself:

- **Narrow therapeutic index.** EMA narrows the acceptance interval to
  **90.00–111.11%**. FDA instead applies RSABE plus a variance comparison.
  Same drug, structurally different tests.
- **Highly variable drugs.** Both widen, but by different mechanisms — EMA's
  scaled ABE for Cmax with a cap, FDA's RSABE.
- **Cmax criteria and rounding conventions** differ in detail.

So the Phase 1 engine must carry a **regulatory profile** (`FDA` | `EMA`) from
the first commit, and results must be reported per profile. Retrofitting this
later would touch every estimator. *(These specifics need confirming against the
current EMA guideline — see §11; they are stated here to be checked, not
assumed.)*

---

## 13. Superseded questions

1. **Which product class first?** Nasal spray / OINDP is where PBE matters and
   where the market gap is. Orals with ABE is the larger market but the crowded
   one. This decides Phase 3 vs Phase 1 priority.
2. **Submission-grade or decision-support?** These are different products. The
   second is perhaps a quarter of the work and carries a fraction of the risk;
   the first needs a validation package and a change-control regime.
3. **FDA only, or FDA + EMA?** Adds the ABE-for-nasal path and a comparison view.
4. **Is a statistician available to review the engine?** I can cross-validate
   against R, but a domain review before anyone trusts an output is not
   optional.

---

## Sources

- [Federal Register — Statistical Approaches To Establishing Bioequivalence, 29 May 2026](https://www.federalregister.gov/documents/2026/05/29/2026-10705/statistical-approaches-to-establishing-bioequivalence-guidance-for-industry-availability)
- [FDA guidance page — Statistical Approaches to Establishing Bioequivalence](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/statistical-approaches-establishing-bioequivalence)
- [RAPS — FDA finalizes two guidances for industry on establishing bioequivalence](https://www.raps.org/resource/fda-finalizes-two-guidances-for-industry-on-establishing-bioequivalence.html)
- [FDA — Bioavailability and Bioequivalence Studies for Nasal Aerosols and Nasal Sprays for Local Action](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/bioavailability-and-bioequivalence-studies-nasal-aerosols-and-nasal-sprays-local-action)
- [Quantics — Bioequivalence: Interpreting the FDA Guidances for a Nasal Spray](https://www.quantics.co.uk/blog/bioequivalence-interpreting-the-fda-guidances-for-a-nasal-spray/)
- [Drug Development & Delivery — Between-Batch Bioequivalence (BBE)](https://drug-dev.com/nasal-spray-bioequivalence-between-batch-bioequivalence-bbe-an-alternative-statistical-method-to-assess-in-vitro-bioequivalence-of-nasal-product/)
- [Performance Properties of the Population Bioequivalence Approach for In Vitro Delivered Dose for OIPs (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3889535/)
- [Certara — The reference-scaled average bioequivalence (RSABE) approach](https://www.certara.com/blog/reference-scaled-average-bioequivalence-2/)
- [CRAN — PowerTOST: Power and Sample Size for (Bio)Equivalence Studies](https://cran.r-project.org/web/packages/PowerTOST/index.html)
- [Certara — Phoenix WinNonlin](https://www.certara.com/software/phoenix-winnonlin/)
- [PAGE — Validation of NCA and bioequivalence results of PKanalix vs Phoenix WinNonlin and SAS](https://www.page-meeting.org/Abstracts/validation-of-non-compartmental-analysis-nca-and-bioequivalence-results-of-pkanalix-with-respect-to-phoenix-winnonlin-and-sas/)
- [Malvern Panalytical — MDRS and nasal sprays: advancing bioequivalence assessment](https://www.malvernpanalytical.com/en/learn/knowledge-center/insights/advancing-bioequivalence-assessment)
