# Validation

**Status: not validated. This engine must not be used to support a regulatory
submission.**

That sentence is the point of this directory. Everything in `tests/` shows the
code computes what the module documentation says it computes. Nothing in
`tests/` shows that what the documentation says is what a regulator expects.
Only an external reference answer can do that.

---

## The distinction this package is built around

| | `tests/` | `validation/` |
|---|---|---|
| Question | Does the code do what we said? | Is what we said correct? |
| Truth comes from | Algebra, invariance, internal consistency | An independent, citable source |
| Who signs it off | Engineering | A qualified statistician |
| Runs | Every commit | Per qualified release |

The 31 tests currently in `tests/` are deliberately of the first kind: a period
effect must not move the treatment estimate, TOST and the confidence interval
must never disagree, swapping T and R must invert the ratio, zero variance must
be refused. Each is checkable without knowing a single published number.

**No expected value in this package was taken from memory.** That rule exists
because a remembered constant that is subtly wrong is indistinguishable from a
correct one until a submission fails.

---

## An observation that is *not* validation

Running the engine for a 2×2 crossover, ratio 0.95, 80% power, 80.00–125.00%,
gives:

| CV | n |
|---|---|
| 10% | 8 |
| 15% | 12 |
| 20% | 20 |
| 25% | 28 |
| 30% | 40 |
| 40% | 66 |

These appear to agree with the classical published sample-size tables at every
point. That is reassuring and it is a reason to expect the formal cross-check to
go well — **but it is not evidence**, because the comparison was made against
recollection rather than against a fetched, citable table. It is recorded here
so that whoever does the real check knows what to expect, and notices if they
get something different.

---

## What has to happen before "validated" is true

**1. Reference datasets, agreed before use.**
Datasets with independently published answers, nominated or accepted by the
reviewing statistician. Candidates worth evaluating:

- worked examples in the FDA guidance;
- the reference fixtures shipped in `PowerTOST`'s own `/tests` directory, which
  exist for exactly this purpose;
- a published dataset from the standard textbooks, with its printed results.

Each dataset lands here as data + expected values + **the citation**, and the
expected values are transcribed from the source, never produced by this engine.

**2. Independent cross-implementation.**
The same inputs through R (`PowerTOST` for power and sample size, and a
`PROC GLM`-equivalent for the crossover analysis), asserted to agree within a
stated tolerance, in CI. Two independent implementations agreeing is the
cheapest real evidence either is right. The tolerance must be stated and
justified, not discovered.

**3. Method equivalence for power.**
`power.py` implements the non-central t approximation and says so. Where it
disagrees with an exact Owen's Q result by a subject, that must be documented
as a known, understood difference rather than found later by a client.

**4. The lifecycle documents.**
Validation Plan, User Requirements Specification, Functional Specification,
IQ/OQ/PQ protocols and reports, and a traceability matrix from each requirement
to the test that demonstrates it. Change control, with impact assessment on any
change that can move a number — which is what `__version__` in
`src/be_stats/__init__.py` exists to make visible.

**5. Supplier qualification.**
Documented justification for scipy and for any R used in cross-checking,
including pinned versions.

---

## Open items inherited from the research

Recorded in `docs/BIOEQUIVALENCE_TOOL_PLAN.md` §11 and repeated here because
they bear directly on what this engine may claim:

- The FDA final guidance body (28 May 2026) was not read directly — only the
  Federal Register notice and a secondary summary. The conclusion that
  individual BE has been dropped rests on those.
- The EMA narrowed interval for NTI drugs is implemented as **90.00–111.11%**.
  This must be confirmed against the current EMA guideline before it is relied
  on. It is presently the single most consequential unverified constant in the
  package, and at CV 15% it changes the required sample size from 12 to 96.

---

## Scope of this version

Implemented: average bioequivalence for 2×2 crossover and parallel designs;
power and sample size; FDA and EMA profiles for the standard interval and the
EMA NTI interval.

Explicitly refused rather than approximated — each raises `NotApplicable`
instead of quietly returning the standard interval:

- FDA narrow therapeutic index (needs reference-scaled ABE plus a variance
  comparison — Phase 2);
- highly variable drugs under either regulator (needs a replicate design —
  Phase 2);
- population bioequivalence and the in vitro battery (Phase 3).
