"""SAS validation - an optional independent validation service.

be-stats is the calculator of record. Nothing in this package may be required
to produce a regulatory result, and `tests/sas_validation/test_sas_is_never_
required.py` enforces that by asserting no supported calculation path imports
any of it.

What ships working in this release is MANUAL validation: generate an immutable
package, the customer runs it in their own SAS, they upload what SAS wrote, and
a reviewer reads a comparison. No credential is stored and nothing connects
outward.

What is designed but disabled: managed SAS (pending commercial and
service-provider rights) and direct customer connections (pending a real
environment to integrate against). Both are interfaces that refuse, not clients
that pretend.
"""

from app.sas_validation.compare import (
    ComparisonReport,
    QuantityAgreement,
    compare,
    render_report,
)
from app.sas_validation.config import (
    AuthorisationAcknowledgement,
    ManagedConfig,
    RemoteConfig,
    SASIntegration,
    SecretReference,
    ViyaConfig,
)
from app.sas_validation.ingest import ParsedSASResult, ingest_upload, parse_result_csv
from app.sas_validation.modes import (
    ACKNOWLEDGEMENT_TEXT,
    CUSTOMER_CONTROL_NOTICE,
    MANAGED_AVAILABILITY_NOTICE,
    ManagedBillingMode,
    OracleClosureDecision,
    SASCapability,
    SASIntegrationMode,
    SASValidationRunStatus,
    is_enabled,
    mode_is_available,
)
from app.sas_validation.package import ValidationPackage, build_package
from app.sas_validation.program import generate_program
from app.sas_validation.providers import (
    ManualSASValidationProvider,
    SASProviderUnavailable,
    SASValidationProvider,
    provider_for,
)
from app.sas_validation.targets import TARGETS, ValidationTarget, get_target

__all__ = [
    "ACKNOWLEDGEMENT_TEXT",
    "CUSTOMER_CONTROL_NOTICE",
    "MANAGED_AVAILABILITY_NOTICE",
    "TARGETS",
    "AuthorisationAcknowledgement",
    "ComparisonReport",
    "ManagedBillingMode",
    "ManagedConfig",
    "ManualSASValidationProvider",
    "OracleClosureDecision",
    "ParsedSASResult",
    "QuantityAgreement",
    "RemoteConfig",
    "SASCapability",
    "SASIntegration",
    "SASIntegrationMode",
    "SASProviderUnavailable",
    "SASValidationProvider",
    "SASValidationRunStatus",
    "SecretReference",
    "ValidationPackage",
    "ValidationTarget",
    "ViyaConfig",
    "build_package",
    "compare",
    "generate_program",
    "get_target",
    "ingest_upload",
    "is_enabled",
    "mode_is_available",
    "parse_result_csv",
    "provider_for",
    "render_report",
]
