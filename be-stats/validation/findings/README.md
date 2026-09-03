# Validation findings

A **finding** is a numerical disagreement between `be-stats` and an external
oracle that the declared tolerance did not fail, and that chance does not
explain. The harness raises one when two Monte Carlo estimates sit more than
four of their own standard errors apart while still inside a tolerance
evaluated at the worst case `p = 0.5`.

That gap is deliberate. Tightening the tolerance to the observed `p` after
seeing the result is how a tolerance stops meaning anything, so the harness
does not fail the case — it names the difference and refuses to let it read as
noise.

## Why they live in files

A finding raised in a CI log is gone at the next run. A finding in a file
survives, carries its own reproduction, and can be pointed at from a case file
via `open_findings`, which downgrades a method's tier-3 row from `PASSED` to
`PASSED_WITH_FINDING`. That downgrade is the point: a reviewer scanning the
tier-3 block should not be able to read `PASSED` without also reading what it
does not cover.

## Status and classification are separate fields

They answer different questions, and collapsing them loses one of the answers.

**`status`** — does anyone still need to work on this?

| status | meaning |
|---|---|
| `OPEN` | Not yet explained. |
| `PREEMPTED` | Found by inspecting the oracle's source *before* a comparison was written, so the wrong comparison was never run. Nothing broke, so nothing needed resolving. |
| `RESOLVED` | Understood and decided. **Not** the same as "the numbers now agree." |

**`classification`** — what turned out to be true. Present when `status` is
`RESOLVED`.

| classification | meaning |
|---|---|
| `RESOLVED_MONTE_CARLO_VARIATION` | Chance after all, shown by re-running at higher counts and other seeds. |
| `RESOLVED_SIMULATION_MODEL_DIFFERENCE` | The two sides simulated different studies. |
| `RESOLVED_POWERTOST_LEGACY_METHOD_DIFFERENCE` | The oracle implements an older or different published method. |
| `RESOLVED_BE_STATS_DEFECT` | `be-stats` was wrong. Fix the package, not the case. |
| `RESOLVED_POWERTOST_CONFIGURATION_ERROR` | The harness drove the oracle wrongly, or compared quantities that are not the same quantity. |
| `ACCEPTED_ORACLE_DIVERGENCE` | Correct on both sides, and **permanent**: the oracle encodes something the regulator states differently. `be-stats` follows the regulator. |

### A resolved finding can still qualify a tier-3 row

`ACCEPTED_ORACLE_DIVERGENCE` is the case in point. `VAL-FDA-HVD-002` and
`VAL-EMA-ABEL-002` are both `RESOLVED` — nobody needs to investigate them
again — and both describe a numerical difference that appears in **every run**
and always will.

So the method's tier-3 row stays `PASSED_WITH_FINDING`. Marking it `PASSED`
would hide a real difference behind a green tick; leaving the finding `OPEN`
would keep a closed question permanently open. The two fields let the report
say both things at once, which is what a reviewer actually needs.

## The hierarchy, which a finding never inverts

    FDA source  ->  be-stats implementation  ->  PowerTOST reproduction

PowerTOST is an implementation oracle, not a regulatory authority. A
disagreement is a question about the comparison first, about `be-stats` second,
and about the oracle third — but never a reason to change what `be-stats` does
so a number matches. `VAL-FDA-HVD-002` is the case in point: PowerTOST switches
at a threshold that differs from FDA's stated one, and `be-stats` follows FDA.

## The records

This table used to be maintained by hand. It listed five of the nine findings
that existed, and ended with "No finding is currently `OPEN`" while
`VAL-FDA-APPENDIX-C-002` was open. Nobody was careless; nothing could fail.

It is now generated from `be_stats.dossier.findings`, and
`tests/validation/test_dossier_evidence.py` regenerates it and compares. The
register also carries findings with no numerical comparison behind them - the
`DOSSIER-*` records - which is why some rows have no linked file.

<!-- BEGIN GENERATED findings table -->

*Generated from `be_stats.dossier.findings`. Do not edit by hand;
regenerate with `python -m be_stats.dossier.render <this file>`.*

| id | subject | severity | status |
|---|---|---|---|
| [`VAL-FDA-APPENDIX-C-PARTIAL-001`](VAL-FDA-APPENDIX-C-PARTIAL-001.md) | The correct Satterthwaite denominator degrees of freedom for FDA's Appendix C model on a partial replicate design is not determined. A candidate of about 19.89 is the best supported value; ReplicateBE.jl's 22.540 is incompatible with EMA's published interval under the corroborated standard error. | blocking | resolved |
| [`VAL-FDA-APPENDIX-C-002`](VAL-FDA-APPENDIX-C-002.md) | ReplicateBE.jl reproduces EMA's published SAS Method C output exactly on the fully replicate design and does not on the partial replicate one. An oracle established on one design does not transfer to the other. | blocking | open |
| [`VAL-FDA-APPENDIX-C-003`](VAL-FDA-APPENDIX-C-003.md) | ReplicateBE.jl cannot represent a NEGATIVE subject-by-formulation correlation, which FDA's FA0(2) structure permits through the sign of l21. Where the fit has one, the oracle is structurally incapable of fitting the same model and cannot adjudicate a disagreement. | scope_limitation | resolved |
| [`VAL-FDA-APPENDIX-C-004`](VAL-FDA-APPENDIX-C-004.md) | The denominator df difference against ReplicateBE.jl is a BOUNDARY effect and appears only at the boundary of the covariance parameter space. Away from it the two agree. | qualifying | resolved |
| [`VAL-FDA-APPENDIX-C-001`](VAL-FDA-APPENDIX-C-001.md) | The feasibility question itself: is there a trustworthy numerical oracle for FDA's Appendix C model? Answered - one exists for the fully replicate design, within a stated covariance domain, and none exists for the partial replicate one. | informational | resolved |
| [`VAL-FDA-HVD-002`](VAL-FDA-HVD-002.md) | PowerTOST switches at sWR = 0.293560, derived from a 30% CV. FDA states 0.294. be-stats follows the regulator, so the tier-3 row is PASSED_WITH_FINDING rather than PASSED. | qualifying | resolved |
| [`VAL-EMA-ABEL-002`](VAL-EMA-ABEL-002.md) | EMA states the ABEL cap as the pair 69.84-143.19%; the formula at CVwR = 50% gives a fractionally wider one, which PowerTOST keeps. be-stats applies the stated pair. | qualifying | resolved |
| [`VAL-EMA-ABEL-001`](VAL-EMA-ABEL-001.md) | PowerTOST's p(BE-ABEL) is the MIXED decision rather than the scaled criterion alone, and power.scABEL documents four purely empirical adaptations - making it a tuned approximation rather than an oracle. | informational | preempted |
| [`VAL-FDA-HVD-001`](VAL-FDA-HVD-001.md) | PowerTOST's p(BE-sABEc) is the mixed decision, not the scaled criterion alone. The harness had been comparing two quantities that are not the same quantity. | informational | resolved |
| `DOSSIER-001` | The diagnostic emitted when a partial replicate study is refused is named APPENDIX_C_PARTIAL_REPLICATE_NOT_VALIDATED, while the canonical status of the capability is NOT_IMPLEMENTED. Two words for one situation, and the diagnostic's is the weaker claim. | informational | open |
| `DOSSIER-002` | In the manual SAS workflow the package hashes and the parsed result are verifiable, and that the output came from running that program in a licensed SAS session is ATTESTED by a named operator rather than proven by the platform. | scope_limitation | open |
| `DOSSIER-003` | No FDA capability holds tier-1B evidence, because FDA has published no worked numerical example of any of these procedures. Every FDA method that produces a number therefore stands at IMPLEMENTED_UNVALIDATED regardless of how much tier-1A and tier-3 evidence supports it. | scope_limitation | open |

Open: `VAL-FDA-APPENDIX-C-002`, `DOSSIER-001`, `DOSSIER-002`, `DOSSIER-003`.

<!-- END GENERATED findings table -->

## Two families of finding

The classifications split by the activity that produces them.

**Comparison findings** come from running a case against an oracle and asking
why two numbers differ. `RESOLVED_MONTE_CARLO_VARIATION`,
`RESOLVED_POWERTOST_CONFIGURATION_ERROR`, `ACCEPTED_ORACLE_DIVERGENCE` and the
rest belong here.

**Oracle-feasibility findings** come from asking, before any comparison exists,
whether there is anything trustworthy to compare against at all.
`DF_METHOD_DIFFERENCE`, `MODEL_STRUCTURE_DIFFERENCE`,
`COVARIANCE_PARAMETERIZATION_DIFFERENCE`, `MISSING_DATA_DIFFERENCE`,
`NUMERICAL_OPTIMIZER_DIFFERENCE`, `SOURCE_DATA_AMBIGUITY` and
`OPEN_UNEXPLAINED` belong here.

`VAL-FDA-APPENDIX-C-001` is the first of the second kind, and it carries a
field the first kind does not need:

```
oracle_ready         false
implementation_status NOT_IMPLEMENTED
```

Those are different concepts and a feasibility record has to keep them apart.
An oracle can be ready while the implementation is absent; the reverse — an
implementation with no oracle — is the situation this package exists to avoid.

## The rule VAL-FDA-HVD-001 left behind

**Before writing a comparison against any oracle, read the oracle's source and
establish what the quantity you are about to name actually counts.** Record the
function, the version, the internal counter, the routing rule, the reported
output name, and the actual mathematical meaning.

`VAL-EMA-ABEL-001` is the first finding raised by following that rule, and it
found two problems in the EMA family before a single fixture existed: the same
`p(BE-…)` naming trap as the FDA case, and — worse, with no FDA analogue —
that `power.scABEL` documents four "purely empirical" adaptations and is
therefore a tuned approximation rather than an oracle at all.

That is what the rule is for. The cost of following it is an hour of reading;
the cost of not following it was PR #59.

`VAL-FDA-HVD-001-evidence.json` is the frozen output of
`validation/external/investigate_val_fda_hvd_001.py`, which re-runs on demand.
