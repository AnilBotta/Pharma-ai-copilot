"""Three different integrity questions, kept apart because they have three
different answers.

WHAT WENT WRONG, AND WHY IT MATTERED

The first version of the workflow called `compare()` with a hard-coded
`program_hash_matched=True`, and the report duly said the program hash had been
verified. It had not. Nothing in the manual workflow establishes which
`validate.sas` a customer executed.

What we could actually show was collapsed into one claim:

    we know the archive we generated and its hash
    the result reports a dataset hash that matches ours
    the result reports the case id we expect
    -> "hash verification passed"

Each of those is worth having. None of them is evidence about the program that
ran, and presenting them as one verified fact overstates what a reviewer is
being handed - on a record whose whole purpose is to be trustworthy.

THE THREE QUESTIONS

    PACKAGE INTEGRITY
        Do we still have the exact bytes we generated and shipped?
        We hash the archive ourselves and store it. VERIFIED, server-side, and
        it depends on nothing the customer does.

    DATASET PROVENANCE
        Does the result say it was computed from the dataset we shipped?
        The generated program stamps the dataset hash and case id into its own
        output, and we compare those with the package we own. MATCH, MISMATCH
        or MISSING.

        This is SELF-REPORTED EXECUTION PROVENANCE checked against a
        server-owned package. It catches the realistic failure - a result
        uploaded against the wrong package - and it is NOT cryptographic
        attestation: a modified program could emit the same string. Useful
        evidence, and not proof.

    PROGRAM EXECUTION INTEGRITY
        Did the customer run the exact unmodified `validate.sas` we shipped?
        In manual mode: UNVERIFIED, and unverifiable. Execution happened in an
        environment we do not control, and no artefact returned from it can
        settle the question.

UNVERIFIED IS NOT FAILURE

`UNVERIFIED_MANUAL_EXECUTION` is a property of the manual workflow, not a
defect in a particular upload. Every honest manual run has it. Turning it into
a mismatch would fail every valid upload and teach reviewers to ignore the
field, which is the opposite of the point.

So the numerical comparison still happens, the run still reaches
`COMPARISON_AVAILABLE` or `REVIEW_REQUIRED`, and the qualification travels with
the record for a reviewer to weigh.

WHERE VERIFIED WOULD BECOME POSSIBLE

A future MANAGED provider would control the program bytes, the submission, the
execution environment and the result retrieval - the whole chain. There,
`PROGRAM_EXECUTION_INTEGRITY = VERIFIED` would be a claim that could be
supported. That provider is not implemented and this module does not assume it;
the enum simply leaves room for the distinction rather than pretending the
distinction does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.sas_validation.modes import SASIntegrationMode


class PackageIntegrity(StrEnum):
    """Are the shipped bytes the bytes we generated?"""

    VERIFIED = "verified"
    #: The stored archive is missing or its hash does not match the record.
    CORRUPT = "corrupt"
    #: No archive was stored - an incompletely generated package.
    ABSENT = "absent"


class DatasetProvenance(StrEnum):
    """Does the result say it came from the dataset we shipped?"""

    MATCH = "match"
    MISMATCH = "mismatch"
    #: The result carries no stamp. Either it predates stamping, or it was not
    #: produced by our program at all.
    MISSING = "missing"


class ProgramExecutionIntegrity(StrEnum):
    """Did the exact unmodified program run?"""

    #: Only reachable where we control the whole chain. Nothing implemented
    #: today can set this, and a test asserts the manual path never does.
    VERIFIED = "verified"

    #: Positive evidence that a different program ran.
    MISMATCH = "mismatch"

    #: The honest answer for manual execution. NOT a failure - see the module
    #: docstring. It is a property of the workflow, present on every valid
    #: manual run.
    UNVERIFIED_MANUAL_EXECUTION = "unverified_manual_execution"

    @property
    def is_failure(self) -> bool:
        """Only an actual mismatch is a failure.

        Asked as a method so no caller has to remember that `not VERIFIED`
        would wrongly condemn every manual upload.
        """
        return self is ProgramExecutionIntegrity.MISMATCH


#: Said the same way everywhere it is said - the report, the API and the audit
#: trail should not each paraphrase it differently.
UNVERIFIED_EXPLANATION = (
    "The application can verify the package it generated and can compare "
    "provenance values emitted by the SAS result. Because SAS execution "
    "occurred in a customer-controlled environment, the application cannot "
    "cryptographically prove that the exact unmodified validate.sas file was "
    "executed."
)

DATASET_STAMP_EXPLANATION = (
    "Self-reported execution provenance, checked against the server-owned "
    "package. It identifies which validation dataset the result claims to come "
    "from and catches a result uploaded against the wrong package. It is not "
    "cryptographic attestation: a modified program could emit the same value."
)


@dataclass(frozen=True, slots=True)
class EvidenceIntegrity:
    """The three answers, carried together and never collapsed."""

    package: PackageIntegrity
    dataset_provenance: DatasetProvenance
    case_stamp: DatasetProvenance
    program_execution: ProgramExecutionIntegrity
    mode: SASIntegrationMode

    @property
    def provenance_is_sound(self) -> bool:
        """Does the result belong to this package?

        Deliberately does NOT consider `program_execution`: in manual mode that
        is permanently unverified, so folding it in here would make every
        honest upload look unsound.
        """
        return (
            self.dataset_provenance is DatasetProvenance.MATCH
            and self.case_stamp is DatasetProvenance.MATCH
            and self.package is PackageIntegrity.VERIFIED
        )

    @property
    def qualification(self) -> str | None:
        """The sentence a reviewer must see, or None when there is nothing to say."""
        if self.program_execution is ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION:
            return UNVERIFIED_EXPLANATION
        if self.program_execution is ProgramExecutionIntegrity.MISMATCH:
            return (
                "The evidence indicates a different program was executed. The "
                "numbers below are not results for the model this package "
                "specifies."
            )
        return None

    def as_dict(self) -> dict[str, object]:
        return {
            "package_integrity": self.package.value,
            "dataset_provenance": self.dataset_provenance.value,
            "validation_case_stamp": self.case_stamp.value,
            "program_execution_integrity": self.program_execution.value,
            "program_execution_is_failure": self.program_execution.is_failure,
            "mode": self.mode.value,
            "qualification": self.qualification,
            "dataset_stamp_meaning": DATASET_STAMP_EXPLANATION,
        }


def manual_execution_integrity(
    *,
    package: PackageIntegrity,
    dataset_provenance: DatasetProvenance,
    case_stamp: DatasetProvenance,
) -> EvidenceIntegrity:
    """Integrity for a customer-run upload.

    `program_execution` is fixed at UNVERIFIED_MANUAL_EXECUTION and is not a
    parameter, so no caller can pass VERIFIED for a manual run - which is
    exactly the mistake this module exists to make impossible.
    """
    return EvidenceIntegrity(
        package=package,
        dataset_provenance=dataset_provenance,
        case_stamp=case_stamp,
        program_execution=ProgramExecutionIntegrity.UNVERIFIED_MANUAL_EXECUTION,
        mode=SASIntegrationMode.MANUAL_UPLOAD,
    )


__all__ = [
    "DATASET_STAMP_EXPLANATION",
    "UNVERIFIED_EXPLANATION",
    "DatasetProvenance",
    "EvidenceIntegrity",
    "PackageIntegrity",
    "ProgramExecutionIntegrity",
    "manual_execution_integrity",
]
