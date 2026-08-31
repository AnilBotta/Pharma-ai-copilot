"""The adapter each SAS mode plugs into, and the one implementation that works.

WHY THE STUBS RAISE INSTEAD OF PRETENDING

`ManagedSASValidationProvider` and `CustomerViyaSASProvider` exist as
interfaces and refuse to do anything. That is deliberate and it is the harder
option: it would be easy to write a plausible `httpx` call against SAS Viya's
documented REST API and have this module look finished.

It would also be code that has never once run against a real environment,
cannot be tested, and would fail in front of the first customer who enabled it.
A stub that raises `SASProviderUnavailable` with a reason is honest about the
same state of affairs and cannot be mistaken for working software.

The stubs are still worth having now, because they force the manual path to be
written against an ABSTRACTION rather than against itself - so adding a real
provider later is an implementation, not a refactor of everything above it.

NOTHING HERE EXECUTES A SAS PROGRAM

Not now and not by design later. There is no host, no port, no command string
and no shell. The manual provider hands a customer a package and receives a
file back. Whatever a future connected provider does, it will submit a
prepared, generated program to a vendor API - it will not accept a command from
a user and run it, because a SaaS that executes customer-supplied code against
a customer's infrastructure is a different and much more dangerous product than
this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.sas_validation.modes import (
    UNAVAILABLE_REASON,
    SASCapability,
    SASIntegrationMode,
    SASValidationRunStatus,
    is_enabled,
)
from app.sas_validation.package import ValidationPackage


class SASProviderUnavailable(RuntimeError):
    """This provider cannot act, and says why rather than failing obscurely."""


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    ok: bool
    detail: str
    environment_name: str | None = None
    sas_version: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    """What came back from asking for a validation to be run."""

    accepted: bool
    status: SASValidationRunStatus
    detail: str
    #: Set only by providers that run something. Manual mode has no handle
    #: because there is no remote job - the customer has the package.
    external_job_id: str | None = None


@runtime_checkable
class SASValidationProvider(Protocol):
    """The four things any mode must be able to answer."""

    mode: SASIntegrationMode

    def test_connection(self) -> ConnectionTestResult: ...

    def submit_validation(self, package: ValidationPackage) -> SubmissionReceipt: ...

    def get_validation_status(self, external_job_id: str) -> SASValidationRunStatus: ...

    def fetch_validation_result(self, external_job_id: str) -> str: ...


class ManualSASValidationProvider:
    """The mode that works end to end, precisely because it connects to nothing.

    A customer generates a package, runs it in their own SAS, and uploads the
    result. This application stores no credential, opens no connection and
    executes nothing - which is why it can ship before any commercial or
    licensing question is settled, and why it is the right first mode rather
    than a fallback.
    """

    mode = SASIntegrationMode.MANUAL_UPLOAD

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=True,
            detail=(
                "Manual validation needs no connection. Your SAS environment "
                "remains under your organisation's control and this "
                "application never reaches it."
            ),
        )

    def submit_validation(self, package: ValidationPackage) -> SubmissionReceipt:
        """Nothing is submitted anywhere. The package is handed over."""
        return SubmissionReceipt(
            accepted=True,
            status=SASValidationRunStatus.COMPARISON_PENDING,
            detail=(
                f"Package {package.package_id[:16]} is ready to download. Run "
                f"{package.manifest['program_filename']} in your SAS "
                f"environment and upload {package.manifest['result_filename']} "
                "with the SAS log."
            ),
            external_job_id=None,
        )

    def get_validation_status(self, external_job_id: str) -> SASValidationRunStatus:
        raise SASProviderUnavailable(
            "Manual validation has no remote job to poll. Its status is "
            "whatever the uploaded evidence has established."
        )

    def fetch_validation_result(self, external_job_id: str) -> str:
        raise SASProviderUnavailable(
            "Manual validation results arrive by upload, not by fetch."
        )


class _DisabledProvider:
    """Shared refusal, so a disabled mode cannot half-work."""

    mode: SASIntegrationMode

    def _refuse(self) -> SASProviderUnavailable:
        return SASProviderUnavailable(
            UNAVAILABLE_REASON.get(
                self.mode, f"{self.mode.value} is not available."
            )
        )

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=False, detail=str(self._refuse()))

    def submit_validation(self, package: ValidationPackage) -> SubmissionReceipt:
        raise self._refuse()

    def get_validation_status(self, external_job_id: str) -> SASValidationRunStatus:
        raise self._refuse()

    def fetch_validation_result(self, external_job_id: str) -> str:
        raise self._refuse()


class ManagedSASValidationProvider(_DisabledProvider):
    """Placeholder for a SAS environment this organisation would operate.

    NO VENDOR IS BOUND. A managed service could eventually be a commercial SAS
    Viya environment, a service-provider deployment, or an approved cloud
    marketplace offering, and choosing between those is a commercial decision
    that has not been made. Writing a client for any one of them now would bind
    the architecture to the first guess.

    Disabled until this organisation holds the appropriate SAS commercial and
    service-provider rights.
    """

    mode = SASIntegrationMode.MANAGED


class CustomerViyaSASProvider(_DisabledProvider):
    """Placeholder for a customer-owned SAS Viya environment.

    The configuration model exists (see `config.py`); the API calls do not.
    They stay unwritten until there is a real Viya environment to develop
    against, because a speculative OAuth flow and job-submission sequence is
    exactly the kind of code that passes review and fails in production.
    """

    mode = SASIntegrationMode.CUSTOMER_VIYA


class CustomerRemoteSASProvider(_DisabledProvider):
    """Placeholder for a customer-managed enterprise or remote SAS.

    Kept separate from Viya on purpose: the authentication story and the
    deployment shape differ, and one adapter serving both would force one of
    them into the wrong model.

    Whatever this becomes, it will not execute user-supplied commands. See the
    module docstring.
    """

    mode = SASIntegrationMode.CUSTOMER_REMOTE


_PROVIDERS: dict[SASIntegrationMode, type] = {
    SASIntegrationMode.MANUAL_UPLOAD: ManualSASValidationProvider,
    SASIntegrationMode.MANAGED: ManagedSASValidationProvider,
    SASIntegrationMode.CUSTOMER_VIYA: CustomerViyaSASProvider,
    SASIntegrationMode.CUSTOMER_REMOTE: CustomerRemoteSASProvider,
}


def provider_for(mode: SASIntegrationMode) -> SASValidationProvider:
    """Resolve a provider, refusing modes whose feature flag is off.

    The flag is checked HERE rather than at the UI, so a client that guesses
    the API shape cannot reach a disabled provider by asking for it directly.
    """
    if mode is SASIntegrationMode.NOT_CONFIGURED:
        raise SASProviderUnavailable(
            "No SAS validation mode has been configured for this organisation."
        )

    if mode is SASIntegrationMode.MANUAL_UPLOAD:
        if not is_enabled(SASCapability.MANUAL_PACKAGE_GENERATION):
            raise SASProviderUnavailable("Manual SAS validation is disabled.")
    elif mode is SASIntegrationMode.MANAGED:
        if not is_enabled(SASCapability.MANAGED_VALIDATION):
            raise SASProviderUnavailable(UNAVAILABLE_REASON[mode])
    elif not is_enabled(SASCapability.CUSTOMER_CONNECTION):
        raise SASProviderUnavailable(UNAVAILABLE_REASON[mode])

    return _PROVIDERS[mode]()  # type: ignore[return-value]


__all__ = [
    "ConnectionTestResult",
    "CustomerRemoteSASProvider",
    "CustomerViyaSASProvider",
    "ManagedSASValidationProvider",
    "ManualSASValidationProvider",
    "SASProviderUnavailable",
    "SASValidationProvider",
    "SubmissionReceipt",
    "provider_for",
]
