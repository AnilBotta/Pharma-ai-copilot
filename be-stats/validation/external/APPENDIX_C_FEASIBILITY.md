# Appendix C oracle: feasibility, and why it is still blocked

**Conclusion: BLOCKED.** No R package examined can reproduce FDA's Appendix C
model faithfully enough to serve as an oracle, and no oracle has been run —
because no R environment was available where this was written.

**Nothing may be implemented in Python on the strength of this document.** It
records what was checked and what was found, so the next attempt starts from
evidence rather than from the appendix again.

---

## What has to be reproduced

```
PROC MIXED;
CLASSES SEQ SUBJ PER TRT;
MODEL Y = SEQ PER TRT / DDFM=SATTERTH;
RANDOM TRT / TYPE=FA0(2) SUB=SUBJ G;
REPEATED / GRP=TRT SUB=SUBJ;
ESTIMATE 'T vs. R' TRT 1 -1 / CL ALPHA=0.1;
```

Four requirements, and an oracle must meet all four:

1. fixed effects for sequence, **period** and treatment;
2. an **unstructured 2×2 subject-by-formulation** random covariance
   (`TYPE=FA0(2)`, three parameters);
3. **treatment-specific residual variances** (`GRP=TRT`, two parameters);
4. **Satterthwaite** denominator degrees of freedom for the T−R contrast,
   derived from all five covariance parameters.

The output an oracle must produce, for a fixed synthetic dataset: the T−R
estimate, its SE, the denominator df, the 90% CI and the GMR.

## What was checked

Desk research against the packages' own CRAN manuals, read directly. **No R was
run**, so every row below is a documentation finding, not an observed one.

| Package | (1) fixed effects | (2) unstructured subject-by-formulation | (3) residual variance by treatment | (4) Satterthwaite df | Verdict |
|---|---|---|---|---|---|
| `nlme` 3.1-170 | yes | yes — `random = list(subj = pdSymm(~ trt - 1))` | yes — `weights = varIdent(form = ~ 1 \| trt)` | **no** | **fails (4)** |
| `lme4` + `lmerTest` | yes | yes | **no** — one residual variance | yes | **fails (3)** |
| `glmmTMB` | yes | yes | yes — `dispformula` | **not Satterthwaite** | **fails (4)** |

### The nlme finding, which is the decisive one

`nlme` is the closest: it expresses the covariance structure exactly, with
`pdSymm` for the unstructured random term and `varIdent` for treatment-specific
residuals. Both are documented in its manual (version 3.1-170, dated
2026-07-15).

But **the word "Satterthwaite" does not appear anywhere in the nlme manual.**
Its fixed-effect tests use containment degrees of freedom based on the
innermost level of nesting. That is a different quantity from `DDFM=SATTERTH`,
not an approximation of it, and the difference lands directly on the width of
the 90% CI — which is the thing criterion (b) tests.

So `nlme` could serve as a **partial** oracle: the T−R estimate and its SE,
but not the df and therefore not the CI. A partial oracle is worth having, and
it is not enough to unblock the criterion.

### `lme4` + `lmerTest`

`lmerTest` supplies Satterthwaite df, which is requirement (4). But `lme4`
fits a single residual variance and has no `GRP=`-equivalent, so it cannot
express requirement (3) — and for a narrow-therapeutic-index drug, whether
σWT differs from σWR is not incidental to the model, it is the subject of
criterion (c).

### `glmmTMB`

Can express both variance structures. Its inference is Wald/profile-based
rather than Satterthwaite, so requirement (4) is again unmet by a different
route.

## What would unblock this

In order, and none of it should be skipped:

1. **Build the validation image.** Everything here is desk research; the first
   step is an environment in which any of it can be checked.
2. **Try `nlme` on fixed synthetic datasets** and record the estimate, SE and
   containment df. This establishes how far a partial oracle gets.
3. **Find out what SAS actually returns** for the same datasets, or find a
   published worked example that does. Without one side of the comparison being
   authoritative, agreement between two approximations proves nothing.
4. **Only then** decide whether a Python implementation is justified, and
   against what it will be checked.

An alternative worth investigating before writing any REML code: whether FDA,
ICH or EMA publish a worked replicate dataset with the expected average-BE
output. That would close tier 1B *and* give the oracle, and it is a search
rather than a build.

## What must not happen

Implementing the model in Python because `nlme` "gets close". Two
implementations that disagree with SAS in different ways are not a check on
each other. The refusal in `replicate_abe.py` stands until there is something
to check against — and that refusal is the reason the unscaled branch of both
the highly-variable and NTI procedures reports NOT DECIDED rather than a
plausible number.

---

*Sources read directly: the CRAN reference manuals for `PowerTOST` 1.5-7 and
`nlme` 3.1-170. The `lme4`/`lmerTest` and `glmmTMB` rows are from their
documented feature sets and are the least firm entries in the table — they
should be confirmed in the image before anyone relies on them.*
