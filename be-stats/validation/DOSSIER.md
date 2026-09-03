<!-- GENERATED FILE. Do not edit.
     Regenerate with:  python -m be_stats.dossier.render
     Source of truth:  be_stats.dossier and be_stats.spec -->

# Statistical validation dossier

`be-stats` 0.7.0

This document is generated from the canonical capability matrix. It
states what this engine can do, what has been checked, against whose
authority, and what remains unresolved.

**Nothing here promotes anything.** A status changes only through the
release gate, with a named reviewer recording the transition.

---

## Method catalogue

The user-facing view. Three states, one qualification each.

| method | regulator | design | endpoints | status | qualification |
|---|---|---|---|---|---|
| Average bioequivalence, conventional 80.00-125.00% interval | FDA / EMA | 2x2 crossover, parallel group | all endpoints | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: no regulator-published numerical output has been reproduced through this path. |
| FDA reference-scaled average BE for highly variable drugs | FDA | fully replicate crossover, partial replicate crossover | all endpoints | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: the regulator's stated algorithm is conformed to, and no regulator-published worked example of it exists to reproduce. |
| FDA narrow therapeutic index procedure, all three criteria | FDA | fully replicate crossover | all endpoints | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: the regulator's stated algorithm is conformed to, and no regulator-published worked example of it exists to reproduce. |
| EMA average bioequivalence with expanding limits | EMA | fully replicate crossover, partial replicate crossover | Cmax | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: no regulator-published numerical output has been reproduced through this path. |
| EMA narrowed 90.00-111.11% interval for NTI drugs | EMA | 2x2 crossover, fully replicate crossover | AUC, Cmax | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: the regulator's stated algorithm is conformed to, and no regulator-published worked example of it exists to reproduce. |
| FDA Appendix C mixed model, fully replicate design | FDA | fully replicate crossover | all endpoints | IMPLEMENTED - VALIDATION PENDING | Implemented, and validation is pending: a regulator's published output has been reproduced for the model, and not by the regulator whose procedure this is. |
| FDA Appendix C mixed model, partial replicate design | FDA | partial replicate crossover | all endpoints | NOT IMPLEMENTED | Not implemented - external SAS oracle evidence pending. |

---

## Capability matrix

Every method and capability, with the status it currently holds. The
status column is read from `be_stats.spec`; it is not stored here and
not stored twice anywhere.

**`implementation` and `validation` are two axes.** A row that says
`implemented` says the code runs. Whether anybody may rely on it is
the next column and only the next column.

| capability | regulator | implementation | validation | evidence tier | decides |
|---|---|---|---|---|---|
| `AVERAGE_BE_2X2` | both | implemented | implemented_unvalidated | tier_3 | yes |
| `FDA_HVD_RSABE` | FDA | implemented | implemented_unvalidated | tier_1a | yes |
| `FDA_NTI_RSABE` | FDA | implemented | implemented_unvalidated | tier_1a | yes |
| `EMA_HVD_ABEL` | EMA | implemented | implemented_unvalidated | tier_1b | yes |
| `EMA_NTI_NARROW_ABE` | EMA | implemented | implemented_unvalidated | tier_1a | yes |
| `FDA_HVD_REPLICATE_DATA_VALIDATION` | FDA | implemented | implemented | tier_1a | no |
| `FDA_HVD_REFERENCE_VARIANCE` | FDA | implemented | implemented_unvalidated | tier_1a | no |
| `FDA_HVD_TREATMENT_CONTRAST` | FDA | implemented | implemented_unvalidated | tier_1a | no |
| `FDA_HVD_METHOD_SELECTION` | FDA | implemented | implemented | tier_1a | no |
| `FDA_HVD_UNSCALED_BRANCH` | FDA | implemented | implemented_unvalidated | tier_1b | yes |
| `FDA_REPLICATE_STANDARD_ABE_FULL` | FDA | implemented | implemented_unvalidated | tier_1b | yes |
| `FDA_REPLICATE_STANDARD_ABE_PARTIAL` | FDA | not_implemented | not_implemented | none | no |
| `FDA_NTI_DESIGN_VALIDATION` | FDA | implemented | implemented | tier_1a | no |
| `FDA_NTI_REFERENCE_SCALED_CRITERION` | FDA | implemented | implemented_unvalidated | tier_1a | no |
| `FDA_NTI_VARIABILITY_RATIO` | FDA | implemented | implemented_unvalidated | tier_1a | no |
| `FDA_NTI_UNSCALED_ABE` | FDA | implemented | implemented_unvalidated | tier_1b | no |
| `EMA_HVD_DESIGN_GATE` | EMA | implemented | implemented | tier_1a | no |
| `EMA_HVD_VARIABILITY_ELIGIBILITY` | EMA | implemented | implemented | tier_1a | no |
| `EMA_HVD_REFERENCE_VARIABILITY` | EMA | implemented | validated | tier_1b | no |
| `EMA_REPLICATE_METHOD_A` | EMA | implemented | validated | tier_1b | no |
| `EMA_ABEL_LIMIT_CALCULATION` | EMA | implemented | validated | tier_1b | no |
| `EMA_ABEL_PE_CONSTRAINT` | EMA | implemented | implemented_unvalidated | tier_1a | no |
| `EMA_HVD_ENDPOINT_DECISION` | EMA | implemented | implemented_unvalidated | tier_1a | yes |

### Known limitations

**`AVERAGE_BE_2X2`** - Average bioequivalence, conventional 80.00-125.00% interval

- The two one-sided tests procedure on a 2x2 crossover or a parallel design. A REPLICATE design routed to ordinary average BE is a different model - FDA Appendix C - and is a separate capability with its own status.
- No regulator-published worked dataset has been reproduced through this path, so it stands at IMPLEMENTED_UNVALIDATED despite being the most conventional analysis in the package.

**`FDA_HVD_RSABE`** - FDA reference-scaled average BE for highly variable drugs

- Tier 1A only: FDA's stated algorithm is conformed to, and FDA has published no worked numerical example of it. The tier-3 PowerTOST agreement is engineering evidence, not regulatory authority.
- Below the sWR switch the endpoint routes to ordinary average BE, which on a partial replicate design is not implemented and returns NOT DECIDED rather than a verdict.

**`FDA_NTI_RSABE`** - FDA narrow therapeutic index procedure, all three criteria

- Tier 1A only. FDA publishes the three criteria and no worked dataset carrying all three through to a verdict.
- All three criteria must hold. A caller reading only the scaled criterion is reading a third of the procedure.
- Requires a FULLY replicate design; a partial replicate study is refused before any arithmetic runs.

**`EMA_HVD_ABEL`** - EMA average bioequivalence with expanding limits

- Three of its four component capabilities are VALIDATED on tier-1B evidence and the METHOD is not. No EMA publication carries one end-to-end example from CVwR > 30% through widened limits and the Method A interval to a stated verdict, so the wiring between validated parts is itself unvalidated.
- Cmax only. AUC stays at 80.00-125.00% regardless of variability.

**`EMA_NTI_NARROW_ABE`** - EMA narrowed 90.00-111.11% interval for NTI drugs

- Applies to AUC by default. For Cmax the narrowed interval applies only where Cmax itself matters for safety, efficacy or therapeutic drug monitoring - a per-product decision the engine refuses to guess.
- EMA narrows the interval; FDA does not. The two NTI procedures are different procedures and neither is a parameterisation of the other.

**`FDA_HVD_REPLICATE_DATA_VALIDATION`** - Recognise and validate an FDA replicate design

- Structural. It enforces the design definitions and produces no number a regulator could disagree with, which is why its status is IMPLEMENTED rather than IMPLEMENTED_UNVALIDATED.

**`FDA_HVD_REFERENCE_VARIANCE`** - Estimate the within-subject reference variance and CVwR

- Produces sWR, which selects the analysis. No FDA-published worked dataset has been reproduced through it.
- Subjects without two reference measurements are excluded and reported; the count that reaches the estimator is not the count that entered the study.

**`FDA_HVD_TREATMENT_CONTRAST`** - Estimate mu_T - mu_R from the sequence means of Iij

- The Appendix G contrast, which absorbs period within a subject and is NOT the Appendix C model. The two must never be substituted for one another.
- Needs a complete subject; Appendix C does not. The two models run on different subject sets and each reports its own.

**`FDA_HVD_METHOD_SELECTION`** - Apply FDA's sWR = 0.294 switch to one endpoint

- The boundary case sWR = 0.294 selects reference scaling, which is what III.C and Appendix G both state. Section III.A uses the same number with the opposite inequality for in vitro permeation testing, and this switch is wrong for that context.

**`FDA_HVD_UNSCALED_BRANCH`** - Ordinary average BE for a replicate design below the switch

- The status is the weaker of the two situations it covers. A FULLY replicate study with raw observations is decided; a PARTIAL replicate study is refused, and so is a fully replicate one supplied only as reduced contrasts.
- A caller reading IMPLEMENTED here must not infer that every HVD study below the switch receives a verdict.

**`FDA_REPLICATE_STANDARD_ABE_FULL`** - FDA Appendix C mixed model, fully replicate design

- The tier-1B numbers are EMA-published, for a model EMA transcribes and attributes to FDA by name. Excellent evidence that the arithmetic is right; NOT FDA validating FDA's own model, and never to be described as the latter. That is why the status is IMPLEMENTED_UNVALIDATED despite the evidence.
- The tier-3 ReplicateBE.jl agreement holds only within the covariance domain that oracle can represent. A negative subject-by-formulation correlation, which FA0(2) permits, is outside it - see VAL-FDA-APPENDIX-C-003.
- Requires the raw subject-period observations; the model is available-case and cannot be fitted from reduced contrasts.

**`FDA_REPLICATE_STANDARD_ABE_PARTIAL`** - FDA Appendix C mixed model, partial replicate design

- NOT IMPLEMENTED. The obstacle is evidentiary rather than arithmetical: the same code would converge and return a plausible interval, and the correct Satterthwaite denominator degrees of freedom for this design remain NOT DETERMINED.
- Candidate values exist and none is treated as the answer. They are recorded in the blocker record with what each one does and does not establish, and no constant in this package holds one.

**`FDA_NTI_DESIGN_VALIDATION`** - Enforce a fully replicate design before any NTI arithmetic

- Structural. The gate either enforces III.B or it does not.

**`FDA_NTI_REFERENCE_SCALED_CRITERION`** - Appendix F criterion (a): the reference-scaled mean criterion

- One of three criteria. Passing it is not passing the procedure.

**`FDA_NTI_VARIABILITY_RATIO`** - Appendix F criterion (c): the 90% F interval for sWT / sWR

- An equal-tails F interval at alpha = 0.1, not a normal approximation.
- Undefined when sWR is exactly zero. That is a refusal, not a pass and not infinity.

**`FDA_NTI_UNSCALED_ABE`** - Appendix F criterion (b): the unscaled 80.00-125.00% limits

- Computed through Appendix C, and therefore inherits Appendix C's evidence and its requirement for raw observations.
- NTI's design gate already requires a fully replicate design, so unlike the HVD branch there is no partial replicate case here.

**`EMA_HVD_DESIGN_GATE`** - Which replicate designs EMA 4.1.10 permits, with a reason

- Structural; no number for a regulator to dispute.

**`EMA_HVD_VARIABILITY_ELIGIBILITY`** - CVwR > 30%, strictly, on the CV scale, Cmax only

- Compared on the CV scale and never converted to an sWR boundary. EMA's threshold on that scale is 0.293560..., which is a different number from FDA's stated 0.294, and studies exist between them.

**`EMA_HVD_REFERENCE_VARIABILITY`** - CVwR from the reference measurements alone

- Validated against the two annexed EMA data sets. Both are four-period; no published three-period example exists.

**`EMA_REPLICATE_METHOD_A`** - EMA Method A: the all-fixed-effects ANOVA the Q&A recommends

- Validated on both annexed data sets including the unbalanced one, whose eight incomplete subjects must be retained for the published result to come out.
- Method A is EMA's recommendation and is not FDA's Appendix C. The two are different models and neither substitutes.

**`EMA_ABEL_LIMIT_CALCULATION`** - The widened limits exp(+/- 0.760 sWR), capped as stated

- The cap is applied as the regulator STATES it, 69.84-143.19%, not as the formula recomputes it. PowerTOST keeps the unrounded pair; be-stats follows EMA. See VAL-EMA-ABEL-002.

**`EMA_ABEL_PE_CONSTRAINT`** - The GMR must additionally fall within 80.00-125.00%

- A containment test on a number produced elsewhere. No EMA-published example exercises the constraint on its own, so it stays unvalidated even though the limits either side of it are validated.

**`EMA_HVD_ENDPOINT_DECISION`** - The two EMA criteria combined into one endpoint verdict

- Every PART has tier-1B evidence and the WHOLE does not. Validating the components does not validate the wiring between them, and this is exactly where correct pieces could be assembled into a wrong verdict.

---

## Regulatory decision routing matrix

Which test applies, before any data is read. A combination with no
row does **not** fall back to the conventional interval - see the
unsupported row at the end.

| route | regulator | drug class | endpoints | method |
|---|---|---|---|---|
| `FDA_STANDARD` | FDA | standard | all | standard_abe |
| `FDA_HVD` | FDA | highly_variable | all | fda_hvd_rsabe |
| `FDA_NTI` | FDA | narrow_therapeutic_index | all | fda_nti_rsabe |
| `EMA_STANDARD` | EMA | standard | all | standard_abe |
| `EMA_HVD_ABEL` | EMA | highly_variable | all | ema_hvd_abel |
| `EMA_NTI_AUC` | EMA | narrow_therapeutic_index | AUC | ema_nti_narrow_abe |
| `EMA_NTI_CMAX` | EMA | narrow_therapeutic_index | Cmax | none (SpecificationRequired) |
| `EMA_NTI_OTHER` | EMA | narrow_therapeutic_index | other | none (SpecificationRequired) |
| `UNSUPPORTED` | any | any | n/a | none (NotApplicable) |

### `FDA_STANDARD`

- **input classification** - A drug that is neither highly variable nor narrow therapeutic index. Note that the classification is an INPUT: this engine does not infer 'highly variable' from an observed CV, because FDA's classification and FDA's analysis switch are two different rules using two different quantities.
- **design required** - crossover, parallel
- **decision rule** - The 90% confidence interval for the T/R geometric mean ratio must fall entirely within 80.00-125.00%.
- **refusal behaviour** - Insufficient degrees of freedom yields decided=false, passes=null, with diagnostics naming the excluded subjects. Never passes=false.
- **refusal codes** - `QUANTITY_NOT_ESTIMABLE`

### `FDA_HVD`

- **input classification** - A drug declared highly variable - within-subject variability of 30% or greater and not an NTI drug.
- **design required** - replicate, partial_replicate
- **decision rule** - The estimated sWR selects the analysis. sWR >= 0.294 applies reference-scaled average BE, whose upper 95% bound on (muT-muR)^2 - theta.sWR^2 must be <= 0, AND the point estimate must fall within 0.8000-1.2500. sWR < 0.294 routes the endpoint to ordinary average BE under Appendix C's mixed model.
- **refusal behaviour** - A non-replicate design is refused outright. Below the switch on a PARTIAL replicate design the endpoint is NOT DECIDED - Appendix C is not implemented for that design and no verdict is produced. It never falls back to the Appendix G contrast, which is a different model.
- **refusal codes** - `FDA_HVD_DESIGN_REQUIRED`, `APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED`, `APPENDIX_C_REQUIRES_RAW_OBSERVATIONS`, `QUANTITY_NOT_ESTIMABLE`

### `FDA_NTI`

- **input classification** - A drug declared narrow therapeutic index.
- **design required** - replicate
- **decision rule** - ALL THREE Appendix F criteria must hold: (a) the 95% upper bound for (muT-muR)^2 - theta.sigma_WR^2 <= 0; (b) the ordinary unscaled 80.00-125.00% interval; (c) the upper limit of the 90% equal-tails interval for sigma_WT/sigma_WR <= 2.500. FDA ADDS criteria; it does not narrow the interval.
- **refusal behaviour** - Anything but a fully replicate crossover is refused before any arithmetic runs. If any single criterion is not estimable the endpoint is NOT DECIDED rather than failed.
- **refusal codes** - `FDA_NTI_FULL_REPLICATE_REQUIRED`, `APPENDIX_C_REQUIRES_RAW_OBSERVATIONS`, `QUANTITY_NOT_ESTIMABLE`

### `EMA_STANDARD`

- **input classification** - A drug that is neither highly variable nor narrow therapeutic index.
- **design required** - crossover, parallel
- **decision rule** - The 90% confidence interval for the T/R geometric mean ratio must fall entirely within 80.00-125.00%.
- **refusal behaviour** - As for the FDA standard route: not estimable yields decided=false, passes=null.
- **refusal codes** - `QUANTITY_NOT_ESTIMABLE`

### `EMA_HVD_ABEL`

- **input classification** - A drug declared highly variable. EMA's WIDENING is available for Cmax only; the route accepts every endpoint and the widening does not.
- **design required** - replicate, partial_replicate
- **decision rule** - Where CVwR for Cmax exceeds 30% strictly, the limits widen to exp(+/- 0.760.sWR) capped at 69.84-143.19%; the Method A 90% interval must fall within them AND the GMR must fall within 80.00-125.00%. Both are required. AUC stays at 80.00-125.00% regardless of variability.
- **refusal behaviour** - Widening requested for AUC is refused rather than granted. A non-replicate design is refused. CVwR at or below 30% does not widen - it is not a failure, the ordinary limits simply apply.
- **refusal codes** - `EMA_ABEL_CMAX_ONLY`, `EMA_ABEL_REPLICATE_DESIGN_REQUIRED`, `QUANTITY_NOT_ESTIMABLE`

### `EMA_NTI_AUC`

- **input classification** - A drug declared narrow therapeutic index, endpoint AUC.
- **design required** - crossover, replicate
- **decision rule** - The 90% confidence interval must fall within the NARROWED 90.00-111.11%. EMA narrows the interval where FDA adds criteria; the two NTI procedures are not variants of one rule.
- **refusal behaviour** - Not estimable yields decided=false, passes=null. The narrowed interval is never widened back to 80.00-125.00%.
- **refusal codes** - `QUANTITY_NOT_ESTIMABLE`

### `EMA_NTI_CMAX`

- **input classification** - A drug declared narrow therapeutic index, endpoint Cmax, with no product-specific guidance supplied.
- **design required** - not reached
- **decision rule** - None is selected. EMA narrows Cmax only where Cmax itself matters for safety, efficacy or therapeutic drug monitoring, and that is a per-product decision: ciclosporin narrows both AUC and Cmax, colchicine narrows AUC and leaves Cmax at 80.00-125.00%.
- **refusal behaviour** - Raises SpecificationRequired. Both available defaults are wrong for some products, so neither is chosen. Supplying the limits as a ProductOverride routes to EMA_NTI_NARROW_ABE with those limits.
- **refusal codes** - `EMA_NTI_CMAX_PRODUCT_SPECIFIC`

### `EMA_NTI_OTHER`

- **input classification** - A drug declared narrow therapeutic index, on an endpoint the general guideline does not address.
- **design required** - not reached
- **decision rule** - None is selected.
- **refusal behaviour** - Raises SpecificationRequired. The general guideline defines narrowed limits for AUC and conditionally for Cmax, and for nothing else.
- **refusal codes** - `EMA_NTI_CMAX_PRODUCT_SPECIFIC`

### `UNSUPPORTED`

- **input classification** - Any jurisdiction and drug-class combination not carried by a row above - a new regulator, or a drug class this engine does not classify.
- **design required** - not reached
- **decision rule** - None is selected and no acceptance interval is assumed.
- **refusal behaviour** - Raises NotApplicable. It does NOT fall back to 80.00-125.00%: a conventional interval applied where the regulator requires something else produces a verdict that looks identical to a correct one.
- **refusal codes** - `UNSUPPORTED_REGULATORY_ROUTE`

---

## Refusal semantics

decided says whether a regulatory criterion was evaluated. passes says which way it went, and is null whenever decided is false - never false. validation_status is orthogonal to both: it says whether the answer may be relied on for a filing, and an unvalidated method still decides.

Every refusal names what would lift it. A refusal that cannot say
that is a dead end rather than an answer.

| code | meaning | lifted by |
|---|---|---|
| `APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED` | FDA Appendix C is implemented for fully replicate designs only. For a partial replicate design (2x3x3) the model would converge and produce a plausible interval, and there is no trustworthy oracle for its Satterthwaite denominator degrees of freedom, so no verdict is issued. | An accepted licensed-SAS PROC MIXED run of the Appendix C model on a partial replicate dataset, establishing the denominator df. Tracked as blocker APPENDIX-C-PARTIAL-ORACLE. |
| `APPENDIX_C_REQUIRES_RAW_OBSERVATIONS` | Appendix C fits subject-period observations with an available-case likelihood. A dataset reduced to per-subject contrasts cannot be fitted, and substituting the Appendix G contrast would answer FDA's question with a different model. | Supply the raw log-transformed subject-period observations. |
| `FDA_HVD_DESIGN_REQUIRED` | FDA's reference-scaled procedure for a highly variable drug requires a replicated crossover, because sWR is estimated from repeated reference administrations. | Submit a partially or fully replicated crossover study. |
| `FDA_NTI_FULL_REPLICATE_REQUIRED` | FDA requires a FULLY replicate crossover for a narrow therapeutic index drug. Criterion (c) compares sigma_WT with sigma_WR, and a partial replicate design never replicates the test product. | Submit a fully replicate crossover study. |
| `EMA_ABEL_REPLICATE_DESIGN_REQUIRED` | EMA permits widened Cmax limits only where CVwR was demonstrated in a replicate design of three or four periods. | Submit a 3-period or 4-period replicate crossover study. |
| `UNSUPPORTED_REPLICATE_DESIGN` | The sequences present do not form a replicate design this engine recognises. Guessing the intended design would silently analyse a different study from the one submitted. | Submit one of the supported designs, or correct the sequence labels if they were mis-coded. |
| `EMA_ABEL_CMAX_ONLY` | EMA's widened acceptance range applies to Cmax only. 4.1.10 keeps AUC at 80.00-125.00% regardless of variability, so a widened limit is not available for this endpoint. | Nothing about the study. Analyse AUC under the ordinary 80.00-125.00% interval, which this engine does support. |
| `EMA_NTI_CMAX_PRODUCT_SPECIFIC` | EMA narrows Cmax for an NTI drug only where Cmax itself matters for safety, efficacy or therapeutic drug monitoring, and that is a per-product decision: ciclosporin narrows both AUC and Cmax, colchicine narrows AUC and leaves Cmax at 80.00-125.00%. | Supply the Cmax limits from the applicable product-specific guidance as a ProductOverride. |
| `UNSUPPORTED_REGULATORY_ROUTE` | This jurisdiction and drug-class combination is not routed by this engine. Falling back to the ordinary 80.00-125.00% interval would answer a question the regulator answers differently. | Implementation of the route, with its own validation ladder. |
| `QUANTITY_NOT_ESTIMABLE` | The quantity the criterion needs does not exist for these data - too few residual degrees of freedom, no replicated test measurement, or a ratio whose denominator is exactly zero. | More evaluable subjects, or the missing replicate measurements. The accompanying diagnostics name which subjects and why. |
| `MODEL_DID_NOT_FIT` | The mixed model did not converge, or converged to a singular covariance structure. A fit that did not happen is not a failed bioequivalence test. | Inspect the dataset for duplicated or degenerate observations; the diagnostics name the condition. |
| `VALIDATION_STATUS_BELOW_REQUIRED` | The caller required a capability at VALIDATED and this one is below that bar. The result was computed and is being withheld, which is not the same as the study failing. | Qualifying evidence promoting the capability to VALIDATED through the release gate, or a caller that accepts the stated status and its limitations. |

---

## Validation evidence manifest

What has actually been checked, against what, and where it is
re-established. A record whose environment was unavailable reads
`skipped_environment_unavailable` and never `passed`.

| evidence | tier | authority | status | capabilities |
|---|---|---|---|---|
| `FDA-HVD-SWITCH-001` | tier_1a | FDA | passed | `FDA_HVD_METHOD_SELECTION`, `FDA_HVD_RSABE` |
| `FDA-HVD-SWR-FORMULA-001` | tier_1a | FDA | passed | `FDA_HVD_REFERENCE_VARIANCE` |
| `FDA-HVD-RSABE-CRITERION-001` | tier_1a | FDA | passed | `FDA_HVD_RSABE` |
| `FDA-NTI-CRITERIA-001` | tier_1a | FDA | passed | `FDA_NTI_RSABE`, `FDA_NTI_REFERENCE_SCALED_CRITERION`, `FDA_NTI_VARIABILITY_RATIO`, `FDA_NTI_UNSCALED_ABE` |
| `FDA-HVD-TREATMENT-CONTRAST` | tier_1a | FDA | passed | `FDA_HVD_TREATMENT_CONTRAST` |
| `EMA-ABEL-PE-CONSTRAINT` | tier_1a | EMA | passed | `EMA_ABEL_PE_CONSTRAINT` |
| `EMA-HVD-ENDPOINT-DECISION` | tier_1a | EMA | passed | `EMA_HVD_ENDPOINT_DECISION` |
| `EMA-NTI-NARROWED-INTERVAL` | tier_1a | EMA | passed | `EMA_NTI_NARROW_ABE` |
| `EMA-PKWP-METHOD-A-DATASET-I` | tier_1b | EMA | passed | `EMA_REPLICATE_METHOD_A` |
| `EMA-PKWP-METHOD-A-DATASET-II` | tier_1b | EMA | passed | `EMA_REPLICATE_METHOD_A` |
| `EMA-PKWP-CVWR` | tier_1b | EMA | passed | `EMA_HVD_REFERENCE_VARIABILITY` |
| `EMA-ABEL-LIMITS-TABLE` | tier_1b | EMA | passed_with_finding | `EMA_ABEL_LIMIT_CALCULATION` |
| `APPENDIX-C-EMA-SAS-METHOD-C` | tier_1b | EMA - publishing output for a model EMA transcribes and attributes to FDA by name. NOT FDA. | passed | `FDA_REPLICATE_STANDARD_ABE_FULL`, `FDA_HVD_UNSCALED_BRANCH`, `FDA_NTI_UNSCALED_ABE` |
| `TIER-2-PUBLISHED-REFERENCE` | tier_2 | - | not_available | - |
| `POWERTOST-CROSS-CHECK` | tier_3 | PowerTOST (R) | skipped_environment_unavailable | `AVERAGE_BE_2X2`, `FDA_HVD_RSABE`, `EMA_HVD_ABEL`, `FDA_NTI_RSABE` |
| `REPLICATEBE-APPENDIX-C-CASES` | tier_3 | ReplicateBE.jl 1.0.15 on Julia 1.10.5 | skipped_environment_unavailable | `FDA_REPLICATE_STANDARD_ABE_FULL` |
| `APPENDIX-C-SYNTHETIC-STRUCTURE` | tier_4 | be-stats | passed | `FDA_REPLICATE_STANDARD_ABE_FULL` |
| `REFERENCE-VARIANCE-SIMULATION` | tier_4 | be-stats | passed | `FDA_HVD_REFERENCE_VARIANCE` |
| `SAS-APPENDIX-C-PARTIAL-REPLICATE` | tier_1b | Licensed SAS, pending | pending | `FDA_REPLICATE_STANDARD_ABE_PARTIAL` |

### `FDA-HVD-SWITCH-001`

- **scenario** - Which analysis Appendix G selects across the sWR range, including the boundary case sWR = 0.294 exactly.
- **dataset** - Six enumerated sWR values spanning the threshold.
- **environment** - None - the rule is asserted, not computed.
- **expected** - sWR < 0.294 selects the two one-sided tests procedure; sWR >= 0.294 selects reference-scaled ABE. The boundary case goes to the scaled side, which III.C and Appendix G both state.
- **observed** - The same selection for all six values, including 0.294.
- **tolerance** - Exact. A selection is a discrete choice and there is no tolerance to state; a near-miss here is a wrong analysis.
- **established by** - `tests/validation/test_algorithm_conformance.py`
- **artefact** - `validation/phase1/algorithm/FDA_HVD_SWITCH_001.json`

### `FDA-HVD-SWR-FORMULA-001`

- **scenario** - The sWR estimator Appendix G specifies.
- **dataset** - Enumerated structural cases.
- **environment** - None.
- **expected** - The estimator and its degrees of freedom as Appendix G states them.
- **observed** - Conforms.
- **tolerance** - Exact on structure; 1e-12 on the arithmetic identities.
- **established by** - `tests/validation/test_algorithm_conformance.py`
- **artefact** - `validation/phase1/algorithm/FDA_HVD_SWR_FORMULA_001.json`

### `FDA-HVD-RSABE-CRITERION-001`

- **scenario** - The scaled criterion AND the point-estimate constraint, both required by Appendix G step 3.
- **dataset** - Enumerated criterion combinations.
- **environment** - None.
- **expected** - Upper 95% bound on (muT-muR)^2 - theta.sWR^2 must be <= 0, AND the point estimate must fall within 0.8000-1.2500.
- **observed** - Both criteria enforced; neither alone decides.
- **tolerance** - Exact on the conjunction.
- **established by** - `tests/validation/test_algorithm_conformance.py`
- **artefact** - `validation/phase1/algorithm/FDA_HVD_RSABE_CRITERION_001.json`

### `FDA-NTI-CRITERIA-001`

- **scenario** - All three Appendix F criteria and every combination of their outcomes, including the ones where a single criterion decides the study.
- **dataset** - Enumerated criterion combinations over the three criteria.
- **environment** - None.
- **expected** - The endpoint passes only when all three hold. Any criterion that is not estimable makes the endpoint NOT DECIDED rather than failed.
- **observed** - Conforms across the enumerated combinations.
- **tolerance** - Exact on the conjunction and on the decided/not-decided split.
- **established by** - `tests/validation/test_nti_criterion_combinations.py`
- **artefact** - `validation/nti/cases/criterion_combinations.json`

### `FDA-HVD-TREATMENT-CONTRAST`

- **scenario** - That mu_T - mu_R is the equally weighted mean of the SEQUENCE means of Iij, with the design's own degrees of freedom - and not the simple mean over subjects, which differs whenever the sequences are unbalanced.
- **dataset** - Constructed replicate datasets, balanced and unbalanced.
- **environment** - be-stats only.
- **expected** - The Appendix G contrast, which absorbs period within a subject and estimates no period effect.
- **observed** - Conforms, and excluded subjects are reported rather than silent.
- **tolerance** - 1e-12 on the arithmetic; exact on the subject accounting.
- **established by** - `tests/unit/test_treatment_contrast.py`
- **note** - Tier 1A. No FDA-published dataset exercises this contrast, which is why the capability cannot rise above IMPLEMENTED_UNVALIDATED.

### `EMA-ABEL-PE-CONSTRAINT`

- **scenario** - That the GMR constraint is required IN ADDITION to the widened interval, and that a study inside the widened limits with a GMR outside 80.00-125.00% fails.
- **dataset** - Constructed endpoint cases either side of both criteria.
- **environment** - be-stats only.
- **expected** - 4.1.10: 'The geometric mean ratio (GMR) should lie within the conventional acceptance range 80.00-125.00%.'
- **observed** - Both criteria are required; neither alone decides.
- **tolerance** - Exact on the conjunction.
- **established by** - `tests/unit/test_ema_abel.py`
- **note** - No EMA-published example exercises the constraint on its own, which is why it stays unvalidated while the limits either side of it are validated.

### `EMA-HVD-ENDPOINT-DECISION`

- **scenario** - The whole endpoint decision: eligibility, widened limits, the Method A interval and the GMR constraint, combined into one verdict - including the paths that produce no verdict.
- **dataset** - Constructed endpoint cases across the eligibility boundary.
- **environment** - be-stats only.
- **expected** - A PASS only when both criteria hold; AUC never widened; CVwR at or below 30% analysed under the ordinary limits rather than failed.
- **observed** - Conforms.
- **tolerance** - Exact on the decision; 1e-12 on the limits.
- **established by** - `tests/integration/test_hvd_endpoint_decision.py`
- **note** - THE WIRING, and the reason this capability is deliberately NOT validated: every part below it has tier-1B evidence and no EMA publication carries one end-to-end example through to a stated verdict. Validated components assembled by unvalidated wiring is exactly what the ladder exists to make visible.

### `EMA-NTI-NARROWED-INTERVAL`

- **scenario** - That an NTI drug under EMA routes to the NARROWED interval for AUC, that Cmax refuses pending product-specific guidance, and that a product override replaces the limits rather than widening them back.
- **dataset** - The routing cases, including a ciclosporin- and a colchicine-shaped override.
- **environment** - None - the limits are stated in the guideline.
- **expected** - 90.00-111.11% for AUC. NOT 80.00-125.00%, and not FDA's additional-criteria construction, which is a different procedure.
- **observed** - The narrowed interval is selected, and Cmax raises.
- **tolerance** - Exact on both limits; the guideline states them to two decimals.
- **established by** - `tests/integration/test_spec_routing.py`
- **note** - Tier 1A and not 1B: EMA states the interval and publishes no worked example of a study decided under it.

### `EMA-PKWP-METHOD-A-DATASET-I`

- **scenario** - Method A on EMA's Data set I - a four-period fully replicate design, UNBALANCED, with eight incomplete subjects that must be retained for the published result to come out.
- **dataset** - EMA/618604/2008 Rev. 13 annex, Data set I, transcribed to validation/ema/cases/ema_pkwp_qa_datasets.json.
- **environment** - EMA published the output from SAS 9.1.
- **expected** - Point estimate 115.66%, 90% CI 107.11-124.89%.
- **observed** - Reproduced to the two decimals EMA printed, on the unbalanced set with all 77 subjects retained.
- **tolerance** - abs 0.005 on each figure - a ROUNDING bound derived from EMA printing two decimals, not a fitted one.
- **established by** - `tests/validation/test_ema_tier1b.py`
- **artefact** - `validation/ema/cases/ema_pkwp_qa_datasets.json`

### `EMA-PKWP-METHOD-A-DATASET-II`

- **scenario** - Method A on EMA's Data set II.
- **dataset** - EMA/618604/2008 Rev. 13 annex, Data set II.
- **environment** - EMA published the output from SAS 9.1.
- **expected** - Point estimate 102.26%, 90% CI 97.32-107.46%.
- **observed** - Reproduced to the two decimals printed.
- **tolerance** - abs 0.005, as above.
- **established by** - `tests/validation/test_ema_tier1b.py`
- **artefact** - `validation/ema/cases/ema_pkwp_qa_datasets.json`

### `EMA-PKWP-CVWR`

- **scenario** - The reference-only model for CVwR, on both annexed data sets.
- **dataset** - EMA/618604/2008 Rev. 13 annex, Data sets I and II.
- **environment** - EMA published the output from SAS 9.1.
- **expected** - CVwR 47.0% and 11.2% under the Model A/B column.
- **observed** - 46.96% and 11.17%.
- **tolerance** - abs 0.05 percentage points - EMA printed one decimal, so this is the rounding bound.
- **established by** - `tests/validation/test_ema_tier1b.py`
- **artefact** - `validation/ema/cases/ema_pkwp_qa_datasets.json`

### `EMA-ABEL-LIMITS-TABLE`

- **scenario** - The guideline's own table of widened limits at CVwR 30, 35, 40, 45 and >=50 percent, including the row where the cap binds.
- **dataset** - CPMP/EWP/QWP/1401/98 Rev. 1, section 4.1.10, printed table.
- **environment** - None - the table is published in the guideline.
- **expected** - Five rows, ending at the stated cap 69.84-143.19%, which is applied AS STATED rather than recomputed.
- **observed** - All five rows reproduce to the two decimals published.
- **tolerance** - abs 0.005 - the printed precision.
- **established by** - `tests/validation/test_ema_tier1b.py`
- **findings** - `VAL-EMA-ABEL-002`
- **note** - PASSED_WITH_FINDING, not PASSED: PowerTOST recomputes the cap and gets a fractionally wider pair. be-stats follows the regulator, and a reader of this row must see that difference.

### `APPENDIX-C-EMA-SAS-METHOD-C`

- **scenario** - FDA's Appendix C mixed model fitted to EMA Data set I, compared against EMA's published SAS 9.1 Method C output.
- **dataset** - EMA/618604/2008 Rev. 13 annex, Data set I, unbalanced.
- **environment** - SAS 9.1, as EMA reports it.
- **expected** - Point estimate 115.66, interval 107.10-124.89, within-subject CVs 47.3% and 35.3%.
- **observed** - All five reproduce to the decimals EMA printed.
- **tolerance** - The printed precision on each figure.
- **established by** - `tests/validation/test_appendix_c_full_replicate.py`
- **findings** - `VAL-FDA-APPENDIX-C-004`
- **note** - The strongest evidence in this package, and it does NOT promote the capability: the model is FDA's, the numbers are EMA's, and one regulator's authority is not the other's.

### `TIER-2-PUBLISHED-REFERENCE`

- **scenario** - No textbook or peer-reviewed reference dataset is currently used by this package.
- **dataset** - -
- **environment** - -
- **expected** - -
- **observed** - -
- **tolerance** - -
- **established by** - `tests/validation/test_dossier_evidence.py`
- **note** - Present so the tier is visibly empty rather than absent. An absent row and an empty one look identical in a report, and only one of them means somebody checked.

### `POWERTOST-CROSS-CHECK`

- **scenario** - Twelve Monte Carlo cases across ABE, RSABE, ABEL and NTI, simulating 20,000 studies through the be-stats pipeline against 100,000 per case on the PowerTOST side.
- **dataset** - validation/external/cases/*.json
- **environment** - A pinned Docker image; versions frozen in validation/external/environment.lock.json.
- **expected** - PowerTOST's power and type-I error estimates.
- **observed** - Agreement within the declared tolerance on every case. Two methods carry a permanent qualification.
- **tolerance** - A Monte Carlo bound evaluated at the worst case p = 0.5, with a four-standard-error gap raising a FINDING rather than tightening the tolerance after the fact.
- **established by** - `tests/validation/test_external_harness.py`
- **artefact** - `validation/external/report.json`
- **findings** - `VAL-FDA-HVD-001`, `VAL-FDA-HVD-002`, `VAL-EMA-ABEL-001`, `VAL-EMA-ABEL-002`
- **note** - Declared SKIPPED here because the manifest describes what is available in an ORDINARY environment, where R is absent. The validation-r workflow runs it in the pinned container and fails if anything is skipped there. The status a certification run reads comes from that job, not from this line.

### `REPLICATEBE-APPENDIX-C-CASES`

- **scenario** - Nine synthetic fully replicate cases compared on all five covariance parameters, the standard error and the denominator degrees of freedom.
- **dataset** - validation/appendix_c/cases/full_replicate_cases.json
- **environment** - The same pinned Docker image.
- **expected** - ReplicateBE.jl's fitted parameters and Satterthwaite df.
- **observed** - Seven of nine agree to 1e-6. The other two are negative subject-by-formulation correlation fits, which the oracle cannot represent at all, and were adjudicated by an independent algebraic identity instead.
- **tolerance** - 1e-6 on the covariance parameters and the standard error; the df tolerance is stated in df rather than percent, because the difference is a boundary effect and a relative tolerance would hide it at small df.
- **established by** - `tests/validation/test_appendix_c_case_oracle.py`
- **artefact** - `validation/appendix_c/oracle/replicatebe_cases_frozen.json`
- **findings** - `VAL-FDA-APPENDIX-C-003`, `VAL-FDA-APPENDIX-C-004`
- **note** - Gated by its own CI job, which fails if any comparison is SKIPPED. Locally Julia is absent, and the honest status is this one rather than PASSED.

### `APPENDIX-C-SYNTHETIC-STRUCTURE`

- **scenario** - For a balanced, complete, interior fit the Appendix C model reduces exactly to the classical subject-level analysis and the Satterthwaite df is exactly n - 2.
- **dataset** - Seven constructed cases meeting those conditions.
- **environment** - be-stats only.
- **expected** - The closed-form subject-level result and n - 2.
- **observed** - Agreement to 1e-8.
- **tolerance** - 1e-8, the floating-point headroom for the identity.
- **established by** - `tests/validation/test_appendix_c_synthetic_cases.py`
- **note** - An algebraic identity sharing no code with the REML implementation. Structural conformance, and explicitly NOT tier 1A - it establishes what mathematics says, not what FDA says.

### `REFERENCE-VARIANCE-SIMULATION`

- **scenario** - The sWR estimator's behaviour under simulation.
- **dataset** - Simulated replicate studies.
- **environment** - be-stats only.
- **expected** - Unbiasedness on the variance scale, and correct df.
- **observed** - Within Monte Carlo error.
- **tolerance** - A Monte Carlo bound at the simulated count.
- **established by** - `tests/validation/test_reference_variance_simulation.py`

### `SAS-APPENDIX-C-PARTIAL-REPLICATE`

- **scenario** - FDA's Appendix C statements run in a licensed SAS session on a partial replicate dataset, reporting the estimate, its standard error and the Satterthwaite denominator degrees of freedom.
- **dataset** - The generated validation package, identified by its manifest SHA-256.
- **environment** - A licensed SAS environment. Not yet run.
- **expected** - NOT STATED. Recording an expected df here would encode a candidate as the answer, which is the entire failure this blocker exists to prevent.
- **observed** - None. No SAS evidence has been accepted.
- **tolerance** - To be declared at review time, before the SAS output is read - a tolerance chosen after seeing the result is not a tolerance.
- **established by** - `tests/validation/test_dossier_evidence.py`
- **findings** - `VAL-FDA-APPENDIX-C-PARTIAL-001`, `VAL-FDA-APPENDIX-C-002`
- **note** - The one record whose arrival changes a capability's status, and it changes nothing on arrival: acceptance is a separate, human-authorised review.

### How an accepted SAS result would enter this manifest

Written down before there is anything to intake, because the day a
real result arrives is the worst day to design the route it takes.

```
When a real SAS Appendix C partial-replicate result has been uploaded,
compared and ACCEPTED through the governed human review workflow - not merely
uploaded, and not merely matching - a separate reviewed pull request does the
following, in this order:

  1. Fill in this record's `software_environment` with the SAS version and
     platform from the accepted attestation, and `dataset` with the package
     id and archive SHA-256 the operator actually ran.
  2. Fill in `expected` with the SAS output, and `observed` with what
     be-stats computes on the same dataset. Declare `tolerance` BEFORE
     comparing; a tolerance chosen after seeing the result is not one.
  3. Move `status` from PENDING to PASSED, PASSED_WITH_FINDING, or - if they
     disagree - leave it PENDING and raise a finding. A disagreement is a
     question about the comparison first, be-stats second, SAS third.
  4. Only then consider the capability. Implementing Appendix C for the
     partial replicate design is a SEPARATE change with its own tests, and
     the evidence arriving does not perform it.
  5. Only after that, and only with the transition named in
     `release_gate.REVIEWED_TRANSITIONS`, may a status move.

`blockers.PARTIAL_ORACLE_READY` and `blockers.REAL_SAS_ORACLE_STATUS` are
edited in step 5 and never earlier. Nothing in this package sets either as a
side effect of an upload, and no test fixture may set them at all.
```

---

## Source provenance

Every regulatory number, and why it is here.

- **indexed** - 29
- **verified against the primary document** - 23
- **derived by this package** - 6
- **unverified** - 0
- **normative** - 21
- **illustrative** - 2

**Normative and derived are not interchangeable.** FDA states the
highly-variable switch as `sWR = 0.294`. `sqrt(ln(1 + 0.30^2))` is
`0.29356...`, and substituting it replaces the regulator's criterion
with this package's arithmetic. Both are indexed, separately, and a
test asserts they never collapse into one entry.

| constant | value | kind | verification | document | section | version |
|---|---|---|---|---|---|---|
| `FDA_HVD_CLASSIFICATION_CV` | 0.3 | normative | verified | Statistical Approaches to Establishing Bioequivalence | III.C | final, May 2026 |
| `FDA_HVD_SWR_SWITCH` | 0.294 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix G (highly variable drugs) | final, May 2026 |
| `FDA_HVD_SIGMA_W0` | 0.25 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix G (highly variable drugs) | final, May 2026 |
| `FDA_HVD_POINT_ESTIMATE_LOWER` | 0.8 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix G (highly variable drugs) | final, May 2026 |
| `FDA_HVD_POINT_ESTIMATE_UPPER` | 1.25 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix G (highly variable drugs) | final, May 2026 |
| `EMA_ABEL_CV_THRESHOLD_PERCENT` | 30 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_K` | 0.76 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_CAP_CV_PERCENT` | 50 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_CAP_LOWER_PERCENT` | 69.84 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_CAP_UPPER_PERCENT` | 143.19 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_PE_LOWER_PERCENT` | 80 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_ABEL_PE_UPPER_PERCENT` | 125 | normative | verified | Guideline on the Investigation of Bioequivalence | 4.1.10 Highly variable drugs or drug products | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `FDA_NTI_SIGMA_W0` | 0.1 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `FDA_NTI_DELTA` | 1.11111 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `FDA_NTI_VARIANCE_RATIO_LIMIT` | 2.5 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `FDA_NTI_UNSCALED_LOWER_PERCENT` | 80 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `FDA_NTI_UNSCALED_UPPER_PERCENT` | 125 | normative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `CONVENTIONAL_LOWER_PERCENT` | 80 | normative | verified | Conventional bioequivalence acceptance interval | - | current |
| `CONVENTIONAL_UPPER_PERCENT` | 125 | normative | verified | Conventional bioequivalence acceptance interval | - | current |
| `EMA_NTI_NARROWED_LOWER_PERCENT` | 90 | normative | verified | Guideline on the Investigation of Bioequivalence | Narrow therapeutic index drugs | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `EMA_NTI_NARROWED_UPPER_PERCENT` | 111.11 | normative | verified | Guideline on the Investigation of Bioequivalence | Narrow therapeutic index drugs | CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010 |
| `DERIVED_SWR_AT_CV_30` | 0.29356 | derived | derived | derived from the 30% CV classification threshold | - | - |
| `DERIVED_FDA_HVD_THETA` | 0.796689 | derived | derived | Statistical Approaches to Establishing Bioequivalence | Appendix G (formula, not a stated number) | final, May 2026 |
| `DERIVED_FDA_NTI_THETA` | 1.11008 | derived | derived | Statistical Approaches to Establishing Bioequivalence | Appendix F (formula, not a stated number) | final, May 2026 |
| `DERIVED_FDA_NTI_THETA_SAS_EXAMPLE` | 1.11006 | derived | derived | Statistical Approaches to Establishing Bioequivalence | Appendix F, SAS example code | final, May 2026 |
| `DERIVED_EMA_ABEL_CAP_LOWER_PERCENT` | 69.8368 | derived | derived | the ABEL formula evaluated at the cap | - | - |
| `DERIVED_EMA_ABEL_CAP_UPPER_PERCENT` | 143.191 | derived | derived | the ABEL formula evaluated at the cap | - | - |
| `FDA_NTI_SAS_EXAMPLE_DELTA` | 1.11111 | illustrative | verified | Statistical Approaches to Establishing Bioequivalence | Appendix F (narrow therapeutic index drugs) | final, May 2026 |
| `FDA_IVPT_SWR_THRESHOLD` | 0.294 | illustrative | verified | Statistical Approaches to Establishing Bioequivalence | III.A (in vitro BE and population BE) | final, May 2026 |

### Derived quantities and what they are not

**`DERIVED_SWR_AT_CV_30`** = `sqrt(ln(1 + 0.30^2))`

The sWR corresponding exactly to a 30% CV. NOT FDA's switching threshold, which FDA states as 0.294. The two differ in the fourth decimal and studies fall between them.

This is the substitution PR #54 reversed. It is also EMA's threshold expressed on the sWR scale, which is why EMA's comparison is made on the CV scale instead. See validation/findings/VAL-FDA-HVD-002.md.

**`DERIVED_FDA_HVD_THETA`** = `(ln(1.25) / FDA_HVD_SIGMA_W0)^2`

FDA's scaled HVD limit. DERIVED legitimately: the guidance gives a formula rather than a number, so the formula is the thing to preserve and its inputs are normative.

**`DERIVED_FDA_NTI_THETA`** = `(ln(FDA_NTI_DELTA) / FDA_NTI_SIGMA_W0)^2`

FDA's scaled NTI limit, computed from the PROSE constant Delta = 1/0.9. The one the engine decides with.

**`DERIVED_FDA_NTI_THETA_SAS_EXAMPLE`** = `(ln(FDA_NTI_SAS_EXAMPLE_DELTA) / FDA_NTI_SIGMA_W0)^2`

Theta as Appendix F's SAS EXAMPLE would compute it, from the printed 1.11111 rather than the prose ratio. NOT the rule. Provided so the difference can be measured rather than re-derived by hand, and read by no decision path.

**`DERIVED_EMA_ABEL_CAP_LOWER_PERCENT`** = `100 * exp(-EMA_ABEL_K * sqrt(ln(1.25)))`

The lower cap as the formula gives it. EMA STATES 69.84 and be-stats applies the stated value; this exists to be compared against it, never used.

See validation/findings/VAL-EMA-ABEL-002.md.

**`DERIVED_EMA_ABEL_CAP_UPPER_PERCENT`** = `100 * exp(+EMA_ABEL_K * sqrt(ln(1.25)))`

The upper cap as the formula gives it. EMA STATES 143.19. The stated pair is not exactly reciprocal because each limit was rounded independently.

**`FDA_NTI_SAS_EXAMPLE_DELTA`** = `n/a`

The five-decimal approximation printed in Appendix F's SAS example. The normative value is the prose ratio 1/0.9.

IMPLEMENTATION REFERENCE, NOT THE REGULATORY CONSTANT. This is the five-decimal approximation written in Appendix F's SAS example; the normative value is the prose ratio Delta = 1/0.9. Verified as appearing in the document, which is a claim about the example code and not about the rule. Consumed by nothing in the decision path.

**`FDA_IVPT_SWR_THRESHOLD`** = `n/a`

The SAME NUMBER as FDA's HVD switch, in section III.A, governing in vitro permeation testing with the OPPOSITE inequality. Indexed so that finding 0.294 in the guidance is not by itself evidence about which rule applies.

IN VITRO PERMEATION TESTING ONLY, and NOT interchangeable with the highly-variable rule: here scaling applies when sWR > 0.294 (strictly), with sWR <= 0.294 unscaled. Appendix G puts the boundary case on the other side. Not consumed by any code path.

---

## Known blockers

- `partial_oracle_ready` = **false**
- `real_sas_oracle_status` = **PENDING**

### `APPENDIX-C-PARTIAL-ORACLE`

- **status** - open
- **affects** - `FDA_REPLICATE_STANDARD_ABE_PARTIAL`, `FDA_HVD_UNSCALED_BRANCH`
- **summary** - There is no trustworthy oracle for the Satterthwaite denominator degrees of freedom of FDA's Appendix C model on a PARTIAL replicate (2x3x3) design, so the capability is not implemented.
- **required evidence** - A licensed SAS PROC MIXED run of the Appendix C statements - MODEL Y = SEQ PER TRT / DDFM=SATTERTH; RANDOM TRT / TYPE=FA0(2) SUB=SUBJ G; REPEATED / GRP=TRT SUB=SUBJ - on a partial replicate dataset whose inputs are published or supplied, reporting the estimate, its standard error and the denominator degrees of freedom.
- **current behaviour** - FDA_REPLICATE_STANDARD_ABE_PARTIAL is NOT_IMPLEMENTED. A partial replicate study routed to ordinary average BE returns decided=false, passes=null, with refusal code APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED. No number is produced.
- **candidate evidence, none of it sufficient**
  - *EMA/618604/2008 Rev. 13, published Data set II output*
    - establishes: The point estimate and confidence interval a partial replicate analysis of that dataset produced under SAS.
    - insufficient because: The published output pins down the interval, not the denominator df directly. Several (SE, df) pairs reproduce the same printed interval to the decimals published.
  - *Independent observed-information calculation, sharing no code with the REML implementation*
    - establishes: A candidate denominator df of approximately 19.89, compatible with the published interval under the corroborated standard error.
    - insufficient because: It is this package's own arithmetic checking this package's own arithmetic. Tier 4. It cannot establish what SAS computes, which is what Appendix C specifies.
  - *ReplicateBE.jl 1.0.15*
    - establishes: Exact agreement with EMA's published SAS output on the FULLY replicate design, and a value of 22.540 on the partial replicate one.
    - insufficient because: 22.540 is incompatible with EMA's published interval under the corroborated standard error, so the oracle that reproduces SAS exactly on one design does not on the other. An oracle that disagrees with the published output is not an oracle for this case.
- **reference** - `validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.md`

### `FDA-TIER-1B-WORKED-EXAMPLE`

- **status** - open
- **affects** - `FDA_HVD_RSABE`, `FDA_NTI_RSABE`, `FDA_REPLICATE_STANDARD_ABE_FULL`, `FDA_HVD_REFERENCE_VARIANCE`, `FDA_HVD_TREATMENT_CONTRAST`, `FDA_NTI_REFERENCE_SCALED_CRITERION`, `FDA_NTI_VARIABILITY_RATIO`, `FDA_NTI_UNSCALED_ABE`
- **summary** - No FDA capability can reach VALIDATED, because FDA has published no worked numerical example of any of these procedures.
- **required evidence** - An FDA-published dataset with published results for the procedure being claimed, or a licensed SAS run of FDA's own example code on inputs that are published.
- **current behaviour** - Every FDA method and capability that produces a number stands at IMPLEMENTED_UNVALIDATED. Results are returned with the status and limitations attached; nothing is withheld and nothing is described as validated.
- **candidate evidence, none of it sufficient**
  - *EMA/618604/2008 Rev. 13 Data set I, SAS 9.1 Method C output*
    - establishes: That be-stats reproduces a REGULATOR-published SAS result for the model EMA transcribes and attributes to FDA by name - point estimate, interval and both within-subject CVs, to the decimals printed.
    - insufficient because: The model is FDA's and the numbers are EMA's. Promoting an FDA capability on it would inflate one regulator's authority into another's. This is why FDA_REPLICATE_STANDARD_ABE_FULL holds tier-1B evidence and remains IMPLEMENTED_UNVALIDATED.
  - *PowerTOST, pinned, run in a locked container*
    - establishes: Agreement with an independent implementation.
    - insufficient because: Tier 3. PowerTOST is an implementation oracle, not a regulatory authority, and it already diverges from FDA's stated switching threshold - see VAL-FDA-HVD-002.
- **reference** - `validation/README.md`

### `MANUAL-SAS-EXECUTION-INTEGRITY`

- **status** - open
- **affects** - `FDA_REPLICATE_STANDARD_ABE_PARTIAL`
- **summary** - In the manual upload workflow, the package hashes and the uploaded result are verifiable; that the uploaded output was produced by running THAT program in a licensed SAS session is attested by an operator, not proven by the system.
- **required evidence** - A managed or directly connected SAS execution path, where the platform submits the program and receives the output without a human-carried step in between.
- **current behaviour** - Uploads are labelled with their declared evidence origin, and only MANUAL_EXTERNAL_SAS may be accepted as oracle evidence. A TEST_FIXTURE origin can never be accepted however complete it is.
- **candidate evidence, none of it sufficient**
  - *Package manifest SHA-256 verification on upload*
    - establishes: That the dataset and program uploaded against are byte-identical to the ones generated, and that the result parses.
    - insufficient because: It establishes WHAT was supposed to run, not that it ran. A result typed by hand from a different session would pass every hash check.
  - *Operator attestation, recorded and append-only*
    - establishes: A named, authorised person's statement of the environment, the SAS version and the fact of execution.
    - insufficient because: An attestation is testimony. It is the right control for this workflow and it is not machine-verifiable evidence.
- **reference** - `docs/SAS_FIRST_LIVE_RUN.md`

---

## Findings register

Severity is about consequence for a claim, not about how surprising
the finding was.

| finding | severity | status | affects |
|---|---|---|---|
| `VAL-FDA-APPENDIX-C-PARTIAL-001` | blocking | resolved | `FDA_REPLICATE_STANDARD_ABE_PARTIAL` |
| `VAL-FDA-APPENDIX-C-002` | blocking | open | `FDA_REPLICATE_STANDARD_ABE_PARTIAL`, `FDA_REPLICATE_STANDARD_ABE_FULL` |
| `VAL-FDA-APPENDIX-C-003` | scope_limitation | resolved | `FDA_REPLICATE_STANDARD_ABE_FULL` |
| `VAL-FDA-APPENDIX-C-004` | qualifying | resolved | `FDA_REPLICATE_STANDARD_ABE_FULL` |
| `VAL-FDA-APPENDIX-C-001` | informational | resolved | `FDA_REPLICATE_STANDARD_ABE_FULL`, `FDA_REPLICATE_STANDARD_ABE_PARTIAL` |
| `VAL-FDA-HVD-002` | qualifying | resolved | `FDA_HVD_RSABE`, `FDA_HVD_METHOD_SELECTION` |
| `VAL-EMA-ABEL-002` | qualifying | resolved | `EMA_ABEL_LIMIT_CALCULATION` |
| `VAL-EMA-ABEL-001` | informational | preempted | `EMA_HVD_ENDPOINT_DECISION` |
| `VAL-FDA-HVD-001` | informational | resolved | `FDA_HVD_RSABE` |
| `DOSSIER-001` | informational | open | `FDA_REPLICATE_STANDARD_ABE_PARTIAL` |
| `DOSSIER-002` | scope_limitation | open | - |
| `DOSSIER-003` | scope_limitation | open | `FDA_HVD_RSABE`, `FDA_NTI_RSABE`, `AVERAGE_BE_2X2` |

### `VAL-FDA-APPENDIX-C-PARTIAL-001`

The correct Satterthwaite denominator degrees of freedom for FDA's Appendix C model on a partial replicate design is not determined. A candidate of about 19.89 is the best supported value; ReplicateBE.jl's 22.540 is incompatible with EMA's published interval under the corroborated standard error.

- **evidence** - An independent observed-information calculation sharing no code with the REML implementation, checked for compatibility against EMA/618604/2008 Rev. 13's published partial replicate output. Boundary handling confirmed independently.
- **resolution condition** - A licensed SAS PROC MIXED run of the Appendix C statements on a partial replicate dataset, reviewed and accepted through the governed workflow.
- **file** - `validation/findings/VAL-FDA-APPENDIX-C-PARTIAL-001.json`
- **blocker** - `APPENDIX-C-PARTIAL-ORACLE`

### `VAL-FDA-APPENDIX-C-002`

ReplicateBE.jl reproduces EMA's published SAS Method C output exactly on the fully replicate design and does not on the partial replicate one. An oracle established on one design does not transfer to the other.

- **evidence** - Pinned ReplicateBE.jl 1.0.15 on Julia 1.10.5 against both annexed EMA data sets, run in a locked container.
- **resolution condition** - The same SAS evidence that closes the partial-replicate blocker. Until then this stays OPEN, which is why the partial capability is NOT_IMPLEMENTED rather than merely unvalidated.
- **file** - `validation/findings/VAL-FDA-APPENDIX-C-002.json`
- **blocker** - `APPENDIX-C-PARTIAL-ORACLE`

### `VAL-FDA-APPENDIX-C-003`

ReplicateBE.jl cannot represent a NEGATIVE subject-by-formulation correlation, which FDA's FA0(2) structure permits through the sign of l21. Where the fit has one, the oracle is structurally incapable of fitting the same model and cannot adjudicate a disagreement.

- **evidence** - Seven of nine synthetic full-replicate cases agree to 1e-6 on all five covariance parameters, the standard error and the denominator df. The two that do not are exactly the negative-correlation fits, and they were adjudicated by an independent algebraic identity instead.
- **resolution condition** - Nothing closes it - it is a permanent property of the oracle. The tier-3 claim is stated with the domain qualifier attached, which is the correct handling rather than a workaround.
- **file** - `validation/findings/VAL-FDA-APPENDIX-C-003.json`

### `VAL-FDA-APPENDIX-C-004`

The denominator df difference against ReplicateBE.jl is a BOUNDARY effect and appears only at the boundary of the covariance parameter space. Away from it the two agree.

- **evidence** - The nine synthetic cases plus EMA Data set I, with the mechanism identified and the alternatives ruled out first.
- **resolution condition** - Nothing closes it. The tolerance is stated in df rather than in percent, so the qualification travels with the claim.
- **file** - `validation/findings/VAL-FDA-APPENDIX-C-004.json`

### `VAL-FDA-APPENDIX-C-001`

The feasibility question itself: is there a trustworthy numerical oracle for FDA's Appendix C model? Answered - one exists for the fully replicate design, within a stated covariance domain, and none exists for the partial replicate one.

- **evidence** - A survey of R mixed-model packages, none of which supports both group-specific residual variances and Satterthwaite df, followed by the ReplicateBE.jl investigation.
- **resolution condition** - Answered as a question. The obstacle it identified is tracked as the partial-replicate blocker.
- **file** - `validation/findings/VAL-FDA-APPENDIX-C-001.json`

### `VAL-FDA-HVD-002`

PowerTOST switches at sWR = 0.293560, derived from a 30% CV. FDA states 0.294. be-stats follows the regulator, so the tier-3 row is PASSED_WITH_FINDING rather than PASSED.

- **evidence** - PowerTOST source inspection plus a boundary sweep measuring how often the two thresholds select different analyses.
- **resolution condition** - Nothing closes it. Both sides behave as designed and will continue to differ. Revisit only if FDA restates the rule.
- **file** - `validation/findings/VAL-FDA-HVD-002.json`

### `VAL-EMA-ABEL-002`

EMA states the ABEL cap as the pair 69.84-143.19%; the formula at CVwR = 50% gives a fractionally wider one, which PowerTOST keeps. be-stats applies the stated pair.

- **evidence** - The guideline's own table at CVwR 30, 35, 40, 45 and >=50 percent, all five rows reproduced to the printed decimals.
- **resolution condition** - Nothing closes it. A documented divergence between an oracle and a regulator is not an open question about the rule.
- **file** - `validation/findings/VAL-EMA-ABEL-002.json`

### `VAL-EMA-ABEL-001`

PowerTOST's p(BE-ABEL) is the MIXED decision rather than the scaled criterion alone, and power.scABEL documents four purely empirical adaptations - making it a tuned approximation rather than an oracle.

- **evidence** - Source inspection before any comparison fixture was written, so the wrong comparison was never run.
- **resolution condition** - Nothing to close. Other oracles were used instead.
- **file** - `validation/findings/VAL-EMA-ABEL-001.json`

### `VAL-FDA-HVD-001`

PowerTOST's p(BE-sABEc) is the mixed decision, not the scaled criterion alone. The harness had been comparing two quantities that are not the same quantity.

- **evidence** - A harness defect with no production impact, confirmed against the real oracle and reproduced by matched synthetic datasets.
- **resolution condition** - Closed. It left behind the rule that an oracle's source is read before a comparison against it is written.
- **file** - `validation/findings/VAL-FDA-HVD-001.json`

### `DOSSIER-001`

The diagnostic emitted when a partial replicate study is refused is named APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED, while the canonical status of the capability is NOT_IMPLEMENTED. Two words for one situation, and the diagnostic's is the weaker claim.

- **evidence** - be_stats.diagnostics.DiagnosticCode versus spec.CAPABILITY_VALIDATION. The refusal vocabulary added in this release uses the accurate spelling and records the correspondence in dossier.refusals.DIAGNOSTIC_FOR.
- **resolution condition** - Renaming the diagnostic would break the rule that a diagnostic code is never repurposed, since reports and audit trails outlive releases. It is left OPEN and documented rather than renamed. Closing it means a deliberate vocabulary migration with a deprecation path, not an in-place rename.

### `DOSSIER-002`

In the manual SAS workflow the package hashes and the parsed result are verifiable, and that the output came from running that program in a licensed SAS session is ATTESTED by a named operator rather than proven by the platform.

- **evidence** - The workflow itself: package manifest SHA-256 verification establishes what was supposed to run, and an append-only operator attestation records who says it ran.
- **resolution condition** - A managed or directly connected SAS execution path, where the platform submits and receives without a human-carried step.
- **blocker** - `MANUAL-SAS-EXECUTION-INTEGRITY`

### `DOSSIER-003`

No FDA capability holds tier-1B evidence, because FDA has published no worked numerical example of any of these procedures. Every FDA method that produces a number therefore stands at IMPLEMENTED_UNVALIDATED regardless of how much tier-1A and tier-3 evidence supports it.

- **evidence** - The validation ladder in validation/README.md, and the absence of any FDA-published dataset with published results.
- **resolution condition** - An FDA-published worked example, or a licensed SAS run of FDA's own example code on published inputs.
- **blocker** - `FDA-TIER-1B-WORKED-EXAMPLE`

---

## Release gate

Whether each capability's claimed status is supportable by the
evidence recorded above. A `VALIDATED` claim needs tier-1B evidence
that passed, a pinned source, no open blocking finding, no blocker,
and an explicitly reviewed transition.

**Result: PASS**

```
release gate: PASS
  ok   AVERAGE_BE_2X2 = implemented_unvalidated
  ok   FDA_HVD_RSABE = implemented_unvalidated
  ok   FDA_NTI_RSABE = implemented_unvalidated
  ok   EMA_HVD_ABEL = implemented_unvalidated
  ok   EMA_NTI_NARROW_ABE = implemented_unvalidated
  ok   FDA_HVD_REPLICATE_DATA_VALIDATION = implemented
  ok   FDA_HVD_REFERENCE_VARIANCE = implemented_unvalidated
  ok   FDA_HVD_TREATMENT_CONTRAST = implemented_unvalidated
  ok   FDA_HVD_METHOD_SELECTION = implemented
  ok   FDA_HVD_UNSCALED_BRANCH = implemented_unvalidated
  ok   FDA_REPLICATE_STANDARD_ABE_FULL = implemented_unvalidated
  ok   FDA_REPLICATE_STANDARD_ABE_PARTIAL = not_implemented
  ok   FDA_NTI_DESIGN_VALIDATION = implemented
  ok   FDA_NTI_REFERENCE_SCALED_CRITERION = implemented_unvalidated
  ok   FDA_NTI_VARIABILITY_RATIO = implemented_unvalidated
  ok   FDA_NTI_UNSCALED_ABE = implemented_unvalidated
  ok   EMA_HVD_DESIGN_GATE = implemented
  ok   EMA_HVD_VARIABILITY_ELIGIBILITY = implemented
  ok   EMA_HVD_REFERENCE_VARIABILITY = validated
  ok   EMA_REPLICATE_METHOD_A = validated
  ok   EMA_ABEL_LIMIT_CALCULATION = validated
  ok   EMA_ABEL_PE_CONSTRAINT = implemented_unvalidated
  ok   EMA_HVD_ENDPOINT_DECISION = implemented_unvalidated
```
