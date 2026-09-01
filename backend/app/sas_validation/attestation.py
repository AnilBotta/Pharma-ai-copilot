"""What a SAS operator declares, and exactly how much it is worth.

THIS IS A HUMAN STATEMENT, NOT A CRYPTOGRAPHIC PROOF.

The application generates a package, a person runs it inside an environment we
have no access to, and a file comes back. Nothing in that path lets us verify
which bytes SAS actually executed. An attestation does not change that. It adds
an ACCOUNTABLE HUMAN CLAIM alongside the evidence - who ran it, where, on which
SAS version, against which package - so that a reviewer weighing the evidence
knows whom to ask, and so that a later dispute has a named starting point.

    ProgramExecutionIntegrity stays UNVERIFIED_MANUAL_EXECUTION.

That is not a formality. `attestation_does_not_upgrade_integrity` in the test
suite asserts it, because "the operator signed something" is exactly the kind
of fact that gets rounded up to "verified" by the third person to read it.

WHAT AN ATTESTATION IS GOOD FOR

    It cannot show      that the executed program matched the package
    It can show         who says it did, on what date, in which organisation,
                        under which SAS product version

The second is worth recording. It is not the first.

THE OPERATOR IS NOT NECESSARILY THE REVIEWER

The person with a licensed SAS environment and the person authorised to accept
oracle evidence are usually different people, and often in different
organisations. So operator identity is DECLARED metadata, captured as text,
while reviewer identity is an authenticated `ReviewerIdentity` resolved from
the session. Modelling the operator as a platform user would either force the
client to hold an account they do not need, or - worse - invite someone to
record a decision under whichever identity happened to be signed in.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvidenceOrigin(StrEnum):
    """Where a run's evidence came from. Declared, never inferred.

    A fixture CSV and a real SAS CSV are the same shape - that is the point of
    a fixture - so nothing about the file can distinguish them. The origin is
    therefore recorded at upload by the caller and never guessed from content.

    `test_dry_run_is_never_real_evidence.py` asserts no code path derives this
    from a file, because "it parsed, so it must be real" is precisely how a
    dry-run artefact ends up in a regulatory record.
    """

    #: An operational exercise. Never regulatory evidence, whatever it contains.
    TEST_FIXTURE = "test_fixture"

    #: The real path in this release: a licensed SAS environment we do not
    #: operate, run by someone else, returning files.
    MANUAL_EXTERNAL_SAS = "manual_external_sas"

    #: Reserved, and deliberately not implemented. Recorded here so the
    #: vocabulary does not have to change when a managed service exists.
    MANAGED_SAS = "managed_sas"

    @property
    def is_regulatory_evidence(self) -> bool:
        """Only real SAS output can be evidence about a regulatory question."""
        return self is not EvidenceOrigin.TEST_FIXTURE


#: Bumped whenever the wording changes, and stored with every attestation, so
#: "what exactly did this operator claim" survives a later edit.
ATTESTATION_VERSION = "sas-operator-attestation/1"

#: `{package_id}` is filled in per attestation, so the stored text names the
#: package rather than gesturing at one.
ATTESTATION_TEMPLATE = (
    "I confirm that I executed the validation package identified by package ID "
    "{package_id} in my organization's authorized SAS environment. Other than "
    "the documented environment/path configuration required to run the "
    "package, I did not intentionally alter the supplied validation dataset or "
    "statistical model."
)

#: What this attestation is NOT, kept beside the text so the two are read
#: together wherever either is displayed.
ATTESTATION_LIMITATION = (
    "This is a human declaration, not cryptographic verification. The "
    "application cannot verify the exact SAS program bytes executed in an "
    "environment it does not control, and this attestation does not change "
    "that: program execution integrity remains UNVERIFIED_MANUAL_EXECUTION."
)


def attestation_text(package_id: str) -> str:
    return ATTESTATION_TEMPLATE.format(package_id=package_id)


def attestation_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AttestationRejected(ValueError):
    """The attestation was refused before it was stored."""


@dataclass(frozen=True, slots=True)
class OperatorAttestation:
    """A named person's claim about one execution of one package.

    Every field is DECLARED. None of it is verified, and the type name says so
    rather than leaving a reader to notice.
    """

    package_id: str
    archive_sha256: str

    #: Free text. The operator may be an employee of a client organisation with
    #: no account here, and inventing a user id for them would be a fiction the
    #: audit trail then carries forever.
    operator_name: str
    operator_organization: str

    #: Optional because an operator may legitimately not know, and a required
    #: field that people fill with "unknown" is worse than an absent one.
    operator_email: str | None
    sas_version: str | None
    operating_environment: str | None

    executed_at: datetime | None

    attestation_version: str
    attestation_text: str
    attestation_hash: str

    #: When the declaration was made here, which is not when SAS ran.
    attested_at: datetime | None = None

    #: Who was signed in when this was submitted. Recorded as the SUBMITTER,
    #: never as the operator: an account manager pasting a client's details is
    #: the ordinary case.
    submitted_by: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "archive_sha256": self.archive_sha256,
            "operator_name": self.operator_name,
            "operator_organization": self.operator_organization,
            "operator_email": self.operator_email,
            "sas_version": self.sas_version,
            "operating_environment": self.operating_environment,
            "executed_at": self.executed_at,
            "attestation_version": self.attestation_version,
            "attestation_text": self.attestation_text,
            "attestation_hash": self.attestation_hash,
            "attested_at": self.attested_at,
            "submitted_by": self.submitted_by,
            # Stated in the record itself, not only in the code that wrote it.
            "limitation": ATTESTATION_LIMITATION,
            "program_execution_integrity": "unverified_manual_execution",
        }


def build_attestation(
    *,
    package_id: str,
    archive_sha256: str,
    operator_name: str,
    operator_organization: str,
    confirmed: bool,
    operator_email: str | None = None,
    sas_version: str | None = None,
    operating_environment: str | None = None,
    executed_at: datetime | None = None,
    submitted_by: str | None = None,
) -> OperatorAttestation:
    """Assemble an attestation, refusing the shapes that would be worthless.

    `confirmed` must be an explicit true. An attestation nobody affirmed is a
    form someone skipped, and storing it would put an unmade claim into the
    evidence record.
    """
    if not confirmed:
        raise AttestationRejected(
            "The operator must affirm the attestation. An unaffirmed "
            "attestation is a skipped form, not a weaker claim."
        )
    if not operator_name or not operator_name.strip():
        raise AttestationRejected(
            "An attestation needs a named operator. Its whole value is that "
            "there is somebody to ask."
        )
    if not operator_organization or not operator_organization.strip():
        raise AttestationRejected(
            "An attestation needs the operating organisation - the SAS licence "
            "belongs to an organisation, not to a person."
        )
    if not archive_sha256 or len(archive_sha256) != 64:
        raise AttestationRejected(
            "An attestation must name the archive hash it is about. Without it "
            "the claim does not identify which bytes were run."
        )

    text = attestation_text(package_id)
    return OperatorAttestation(
        package_id=package_id,
        archive_sha256=archive_sha256,
        operator_name=operator_name.strip(),
        operator_organization=operator_organization.strip(),
        operator_email=(operator_email or "").strip() or None,
        sas_version=(sas_version or "").strip() or None,
        operating_environment=(operating_environment or "").strip() or None,
        executed_at=executed_at,
        attestation_version=ATTESTATION_VERSION,
        attestation_text=text,
        attestation_hash=attestation_hash(text),
        submitted_by=submitted_by,
    )


__all__ = [
    "ATTESTATION_LIMITATION",
    "ATTESTATION_TEMPLATE",
    "ATTESTATION_VERSION",
    "AttestationRejected",
    "EvidenceOrigin",
    "OperatorAttestation",
    "attestation_hash",
    "attestation_text",
    "build_attestation",
]
