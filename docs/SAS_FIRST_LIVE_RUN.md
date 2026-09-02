# The first live SAS run

This describes how one real SAS execution reaches this system, what the system
does with it, and — just as importantly — what accepting it will and will not
mean.

It is an **operations** document. No statistical method is implemented or
validated here.

```
FDA_REPLICATE_STANDARD_ABE_FULL     IMPLEMENTED_UNVALIDATED
FDA_REPLICATE_STANDARD_ABE_PARTIAL  NOT_IMPLEMENTED
FDA_NTI_RSABE                       IMPLEMENTED_UNVALIDATED
partial_oracle_ready                false
```

Those four lines are unchanged by anything in this milestone, and remain
unchanged if the first live run succeeds perfectly.

---

## 1. The question the first run is meant to answer

`FDA_APPENDIX_C_PARTIAL_EMA_DATASET_II`.

The FDA's Appendix C `PROC MIXED` model is defined for replicate designs. On a
**partial**-replicate design — one T observation per subject — σ²_BT and σ²_WT
are exactly non-identifiable, and the denominator degrees of freedom that
Satterthwaite produces depend on how the software handles that. Different
implementations give different answers, and no regulator has published the
number for this dataset.

So the oracle question is: **what does SAS itself report?**

### The system must stay neutral about the answer

Three numbers exist in this area, and the system labels every one of them:

| Value | What it is | Label |
|---|---|---|
| estimate ≈ 102.26 %, 90 % CI 97.05–107.76 | EMA published this | **REGULATOR PUBLISHED** |
| denominator df ≈ 19.8906 | our own observed-information computation | **INDEPENDENT CANDIDATE — not regulator-confirmed** |
| denominator df ≈ 22.5403 | ReplicateBE.jl | **EXTERNAL IMPLEMENTATION — not regulator-confirmed** |

**None of these is the expected SAS answer.** 19.8906 and 22.5403 are plausible
outputs of two different methods, and a report that printed either as
"expected" would turn the open question into an answer key. The comparison
carries each value's `evidence_status` inline, next to the number, precisely so
they cannot read as equally authoritative on a screen.

If SAS returns something that matches neither, that is a *result*, not a fault.

---

## 2. Readiness matrix

| # | Step | Implemented | Tested | Needs real SAS | Needs a human | Remaining limitation |
|---|---|---|---|---|---|---|
| A | Package generation | yes | yes | no | no | — |
| B | Immutable archive storage | yes | yes | no | no | Storage bucket must exist in the deployment (see §7) |
| C | Package download (signed URL) | yes | yes | no | no | Link is short-lived by design; re-issue as needed |
| D | Result upload | yes | yes | **yes** | no | Nothing to upload until SAS has run |
| E | Log upload | yes | yes | **yes** | no | Log is archived, never parsed for regulatory numbers |
| F | Result provenance checking | yes | yes | no | no | Verifies dataset + case stamps, **not** the executed program |
| G | Parsing | yes | yes | no | no | Only the structured file `validate.sas` writes |
| H | Comparison | yes | yes | no | no | Engine value is absent: partial Appendix C is `NOT_IMPLEMENTED`, so the engine refuses rather than producing an unvalidated number |
| I | Deterministic evidence display | yes | yes | no | no | — |
| J | AI advisory analysis | yes | yes | no | no | Advisory only; blocked until H exists; absent if no provider configured |
| K | Reviewer authorization | yes | yes | no | **yes** | Requires `system_administrator` or `executive` |
| L | Human acceptance / rejection | yes | yes | no | **yes** | Acceptance additionally requires the acknowledgement |
| M | Immutable review evidence snapshot | yes | yes | no | no | Hashed at decision time; append-only |
| N | Audit trail | yes | yes | no | no | — |
| — | **Operator attestation** | yes | yes | no | **yes** | Human declaration; does **not** upgrade execution integrity |
| — | **Evidence origin flag** | yes | yes | no | no | Declared at upload; never inferred from file content |

Every "no" in *Needs real SAS* was demonstrated by
`backend/scripts/sas_operational_dry_run.py`, which walks the whole path with a
controlled fixture.

---

## 3. Operator runbook

For the person who will run the package in a licensed SAS environment.

> You do **not** need to give this application your SAS username, password or
> licence key. Nothing connects to your environment.

1. **Download the validation package** from Pharma AI (Settings → SAS
   Validation → *Download package*). It is a ZIP.

2. **Record these two values** before you do anything else:
   - `package_id`
   - `archive_sha256`

   Both are shown next to the download button.

3. **Verify the archive you received is the archive we supplied.** On the
   machine that will run it:

   ```
   certutil -hashfile <file>.zip SHA256      (Windows)
   shasum -a 256 <file>.zip                  (macOS / Linux)
   ```

   Compare with `archive_sha256`. **If it differs, stop and tell us.** A
   mismatch means the bytes changed in transit, and anything produced from them
   would be evidence about a different package.

4. **Extract it.** You will find `dataset.csv`, `validate.sas`,
   `model_specification.txt` and `manifest.json`.

5. **Do not edit any of the following:**
   - the statistical model
   - the dataset
   - the `PROC MIXED` statements
   - any transformation

   The package contains the approved generated validation program. Regulatory
   source/model provenance is preserved, and the executable SAS contains only
   documented, allow-listed adaptations required for execution.

   **These adaptations are already applied in `validate.sas`. Do not make them
   yourself.** Each is recorded in the file beside the statement it replaced:

   | Regulatory source | Executable in `validate.sas` |
   |---|---|
   | `PROC MIXED;` | `PROC MIXED DATA=be_input METHOD=REML;` |
   | `CLASSES SEQ SUBJ PER TRT;` | `CLASS SEQ SUBJ PER TRT;` |

   `CLASS` is **not** an alias for `CLASSES`. `CLASS` is the statement
   `PROC MIXED` documents; the FDA guidance prints `CLASSES` in its Appendix C
   listing. Substituting the keyword changes SAS syntax only — the same four
   variables are declared classification variables, so the fixed-effects
   design, the covariance structure and every estimate are unchanged.

   `MODEL`, `RANDOM`, `REPEATED` and `ESTIMATE` carry no adaptation at all.

   Editing any statement silently is the one thing that makes the result
   uninterpretable.

6. **The only permitted change** is the documented path configuration at the top
   of `validate.sas` — the `packagedir` macro variable that tells SAS where you
   extracted the package.

7. **Run `validate.sas`.**

8. **Save both outputs:**
   - `be_result.csv` — the structured result the program writes
   - the **complete** SAS log (not an excerpt)

9. **Record:**
   - SAS product and version (the log's first lines, or `%put &sysvlong;`)
   - operating environment, if you can share it
   - execution date and time

10. **Upload both files** back into Pharma AI, and complete the operator
    attestation (§4).

11. **If the program will not run without a code change, tell us what change is
    needed — do not make it silently.** A result from an altered program is not
    weaker evidence about our package; it is evidence about a different program,
    and only you would know that.

---

## 4. Operator attestation — and exactly what it is worth

Manual execution happens in an environment this application has no access to.
We cannot verify which SAS program bytes actually ran. That is permanent for
this path.

The attestation records an **accountable human claim** beside the evidence:

> I confirm that I executed the validation package identified by package ID
> \[X\] in my organization's authorized SAS environment. Other than the
> documented environment/path configuration required to run the package, I did
> not intentionally alter the supplied validation dataset or statistical model.

Stored with it: operator name, organization, optional email, `package_id`,
`archive_sha256`, SAS version, operating environment, execution timestamp,
attestation version, attestation hash, and `attested_at`.

**This is not cryptographic verification.**

```
program_execution_integrity = UNVERIFIED_MANUAL_EXECUTION
```

— before the attestation, and after it. `test_first_live_run_readiness.py`
asserts this, and the stored row carries the limitation in its own body, because
"the operator signed something" is exactly the fact that gets rounded up to
"verified" by the third person to read it.

### The operator is not the reviewer

The person with the SAS licence and the person authorised to accept oracle
evidence are usually different people, often in different organisations. So:

| | Operator | Reviewer |
|---|---|---|
| Identity | **declared** text (name, organisation) | **authenticated** `ReviewerIdentity` |
| Needs an account here | no | yes |
| Recorded in | `sas_operator_attestations` | `sas_human_reviews` |
| Audit action | `..._OPERATOR_ATTESTATION_RECORDED` | `..._REVIEW_ACCEPTED` / `..._REJECTED` |

Minting a platform user id for an external operator would put a fiction in the
audit trail that every later reader would have to un-learn.

---

## 5. What would count as strong first oracle evidence

**Documented, not automatically executed.** A reviewer weighs these; nothing
below is computed into a verdict.

- the approved package was used, unmodified apart from the path configuration
- package archive integrity is known
- dataset provenance = **MATCH**
- validation case provenance = **MATCH**
- the structured SAS output is complete
- denominator df is present
- the 90 % CI is present
- the SAS version is known
- the fit converged
- the complete log was retained
- no unexplained `ERROR` condition in the log
- an authorized human reviewed the evidence
- the manual-execution limitation was explicitly acknowledged

### And one that no amount of good evidence can satisfy

```
evidence_origin = manual_external_sas
```

Every other item above asks *"is this evidence sound?"*. This one asks *"is it
evidence at all?"* — and a dry-run fixture with matching hashes, complete
fields and a converged fit answers no. It is checked first, and the refusal
says what the run **is** rather than what it lacks, because a reviewer looking
at a flawless fixture would otherwise go hunting for a missing field.

`test_fixture` can never be accepted. `managed_sas` cannot either, because no
managed service exists and an accepted run claiming that origin would describe
something that did not happen. An absent or unrecognised origin resolves to
`test_fixture` — both are guesses, and that is the direction where being wrong
is recoverable.

**Rejection has none of these preconditions**, including this one. A reviewer
must always be able to record why a run is unsuitable, whatever it is.

### Not required

```
program_execution_integrity = VERIFIED
```

It cannot be achieved on this path, so requiring it would make acceptance
impossible for every honest run. It must be **visible**, not satisfied — which
is what the acknowledgement is for.

```
operator_attestation = PRESENT
```

Also not required. An operator's declaration is provenance, not verification;
gating acceptance on it would let a form stand in for evidence quality. The
report states `present` or `absent` explicitly so the reviewer can weigh it,
and nothing manufactures one.

---

## 6. One good run is important; it is not magic

A properly documented SAS run on EMA Data Set II **may** be sufficient to
resolve the specific denominator-df oracle question currently open.

It does **not** mean the partial-replicate implementation is
regulator-validated.

```
one accepted SAS run   ≠   method VALIDATED
```

Nothing in the code encodes that equivalence, and
`test_no_automatic_promotion.py` prevents it from being added. When the
statistical implementation PR eventually happens, it should carry additional
independent and/or synthetic validation cases where appropriate — one dataset
from one SAS version is one data point.

### What `ORACLE_CLOSURE_ACCEPTED` means

> This evidence is accepted as suitable **oracle evidence** for the subsequent
> statistical implementation/validation task.

### What it does not mean

- the statistical method is implemented
- the statistical method is validated
- FDA has confirmed the denominator df
- `partial_oracle_ready` may be set true

These four lines travel with the evidence report itself
(`evidence_report.DECISION_SEMANTICS`), so any copy of the report carries them.

---

## 7. Deployment state

Run the read-only audit:

```
cd backend; .venv\Scripts\python.exe scripts\sas_readiness_audit.py
```

It reports migrations, the private bucket, the audit function, reviewer roles
and configuration — and applies nothing. Where something is missing it prints
the exact command that would fix it, and stops.

Migrations, in order:

```
0032_sas_validation.sql            packages, runs, artifacts, audit
0033_sas_validation_storage.sql    private bucket + archive columns
0034_sas_validation_review.sql     AI reviews, human reviews, role lookup
0035_sas_operator_attestation.sql  attestation + evidence origin
```

Apply with `python scripts/apply_sql.py ../supabase/migrations/<file>`.

A **partial** application is the dangerous state: 0032 without 0034 gives a
system that accepts uploads and cannot record a review of them.

### Reviewer roles

Reported by the audit, never granted by it. To grant one:

```
python -m app.pdp_admin grant-role \
  --email reviewer@example.com \
  --role system_administrator
```

Verify with `python -m app.pdp_admin who --email reviewer@example.com`.

---

## 8. Dry runs are never evidence

Every run carries a declared `evidence_origin`:

| Value | Meaning | Regulatory evidence? |
|---|---|---|
| `test_fixture` | an operational exercise | **no**, whatever the numbers say |
| `manual_external_sas` | a licensed SAS environment we do not operate | yes |
| `managed_sas` | reserved; no implementation exists | — (uploads refused) |

It is **declared at upload, never inferred from the file**. A fixture CSV and a
real SAS CSV are the same shape — that is what makes a fixture useful — so
"it parsed, therefore it is real" is exactly how a rehearsal artefact ends up
in a regulatory record. The upload endpoint defaults to `test_fixture`, because
of the two possible mistakes only one is recoverable.

A report built from a fixture opens with:

> **OPERATIONAL DRY RUN — NOT SAS VALIDATION EVIDENCE.**

And a fixture **cannot be accepted as oracle evidence** — not by any reviewer
role, not with a matching hash, not with the assistant recommending it. The
rule lives in `AcceptancePreconditions`, so the POST endpoint enforces it; the
UI hiding the Accept button is a convenience on top.

The assistant *may* analyse a rehearsal — exercising deterministic checks →
advisory → review UI is exactly what a dry run is for. Its facts carry
`evidence_origin`, `is_regulatory_evidence` and a `dry_run_qualification`, so
it never has to infer what it is looking at. What it cannot do is make a
rehearsal acceptable.

To rehearse the path:

```
cd backend; .venv\Scripts\python.exe scripts\sas_operational_dry_run.py
```

Its fixture reports `denominator_df = 1.0000` and `sas_version =
DRY-RUN-NOT-SAS`, so no line copied out of its output could be mistaken for a
measurement.

---

## 9. No SAS result without SAS

There is no substitute for the pending licensed SAS result. Not PowerTOST, not
ReplicateBE.jl, not the Python engine, not a language model. Each of those is a
different implementation's answer to the question SAS is being asked, which is
the whole reason the question is open.

**The exact remaining action:** send the generated package to an authorized SAS
operator, have them follow §3, and upload `be_result.csv` and the complete log
with `evidence_origin = manual_external_sas`.

Until then, `partial_oracle_ready` stays `false`.
