"""SAS validation: the vocabulary, before any of the machinery.

WHAT SAS IS AND IS NOT, IN THIS PRODUCT

be-stats is the calculator of record. Every regulatory result this application
produces comes from the Python engine, and a customer with no SAS at all must
be able to use every supported calculation. SAS is an OPTIONAL INDEPENDENT
VALIDATION SERVICE layered beside that engine, never in front of it.

    be-stats Python calculation
              |
              +---- normal regulatory result
              |
              +---- optional external SAS verification
                             |
           ---------------------------------------
           |                 |                   |
     Managed SAS       Bring Your SAS      Manual SAS
     (future service)   (customer env)     (customer runs it)

`test_sas_is_never_required.py` enforces the first branch: no supported
calculation path may read any of this.

WHY THE MODES ARE NAMED AFTER OWNERSHIP, NOT AFTER CREDENTIALS

An earlier sketch of this called every mode "API key". That is wrong three
times over. A customer's own SAS Viya deployment authenticates by OAuth against
their tenant; an enterprise SAS installation may authenticate by Kerberos or by
a service account; and the manual route has no credential at all because
nothing ever connects. Naming the modes after WHO OWNS AND OPERATES the
environment keeps those differences visible instead of flattening them into a
text field labelled "key".
"""

from __future__ import annotations

from enum import StrEnum


class SASIntegrationMode(StrEnum):
    """How - or whether - a tenant reaches a SAS environment."""

    #: The default and the only honest state until someone chooses.
    NOT_CONFIGURED = "not_configured"

    #: We eventually supply the SAS environment as a paid service. Placeholder
    #: only: feature-flagged off until this organisation holds the appropriate
    #: SAS commercial and service-provider rights. No vendor is bound yet.
    MANAGED = "managed"

    #: Customer-owned SAS Viya, reached over REST with OAuth against their own
    #: tenant. Configuration abstraction only in this release.
    CUSTOMER_VIYA = "customer_viya"

    #: Customer-owned enterprise or remote SAS. Deliberately SEPARATE from
    #: Viya: the authentication story and the deployment shape are different,
    #: and collapsing them would force one of the two into the wrong model.
    CUSTOMER_REMOTE = "customer_remote"

    #: No connection of any kind. We generate a package, the customer runs it
    #: inside their own controlled environment, and uploads what SAS produced.
    #: The only mode that works end to end in this release.
    MANUAL_UPLOAD = "manual_upload"

    @property
    def stores_secrets(self) -> bool:
        return self in (self.CUSTOMER_VIYA, self.CUSTOMER_REMOTE)

    @property
    def connects_outbound(self) -> bool:
        """Does this mode ever open a connection to a SAS environment?

        MANUAL_UPLOAD is the point of the whole first release: it answers no,
        which is why it can ship without a single stored credential.
        """
        return self in (self.MANAGED, self.CUSTOMER_VIYA, self.CUSTOMER_REMOTE)

    @property
    def requires_authorisation_acknowledgement(self) -> bool:
        """Customer-connected environments need the operator to confirm they may
        connect it. See `ACKNOWLEDGEMENT_TEXT`."""
        return self in (self.CUSTOMER_VIYA, self.CUSTOMER_REMOTE)


class SASValidationRunStatus(StrEnum):
    """Where an external validation run has got to.

    THE ORDER MATTERS LESS THAN THE FACT THAT NONE OF THEM MEANS 'VALIDATED'.

    Every state below describes what has happened to a FILE and to a
    COMPARISON. None of them describes a regulatory conclusion, and nothing in
    this module may change a method's validation status - see
    `test_no_automatic_promotion.py`.
    """

    UPLOADED = "uploaded"
    PARSED = "parsed"

    #: The uploaded output does not correspond to the package we generated.
    #: Evidence for a different program or a different dataset is not evidence.
    HASH_MISMATCH = "hash_mismatch"

    #: Parsed, but SAS did not report everything the comparison needs.
    INCOMPLETE = "incomplete"

    COMPARISON_PENDING = "comparison_pending"

    #: The numbers agree within the tolerance recorded on the target. Still not
    #: a validation - a human decides what agreement means.
    MATCH = "match"
    MISMATCH = "mismatch"

    REVIEW_REQUIRED = "review_required"
    REVIEWED_ACCEPTED = "reviewed_accepted"
    REVIEWED_REJECTED = "reviewed_rejected"

    @property
    def is_terminal(self) -> bool:
        return self in (self.REVIEWED_ACCEPTED, self.REVIEWED_REJECTED)

    @property
    def is_reviewed(self) -> bool:
        return self.is_terminal


class OracleClosureDecision(StrEnum):
    """A reviewer's explicit verdict on whether an oracle question is closed.

    Recorded separately from the run status because they answer different
    questions. A run can be MATCH - the numbers agree - while the reviewer
    still declines to close the oracle, because agreement on one dataset from
    one SAS version is not the same as a resolved regulatory question.

    Only a later statistical implementation PR may act on this. Nothing here
    changes `FDA_REPLICATE_STANDARD_ABE_PARTIAL`.
    """

    NOT_ASSESSED = "not_assessed"
    ORACLE_CLOSURE_ACCEPTED = "oracle_closure_accepted"
    ORACLE_CLOSURE_REJECTED = "oracle_closure_rejected"


class ManagedBillingMode(StrEnum):
    """How a managed validation run would eventually be paid for.

    Designed, not implemented, and carrying NO PRICES. Whatever managed SAS
    costs depends on commercial terms this organisation has not agreed, and a
    number written here now would be quoted back later as if it were one.
    """

    NOT_APPLICABLE = "not_applicable"
    INCLUDED_IN_PLAN = "included_in_plan"
    PAY_PER_VALIDATION = "pay_per_validation"
    VALIDATION_CREDIT = "validation_credit"
    ENTERPRISE_INCLUDED = "enterprise_included"


class SASCapability(StrEnum):
    """Capability flags, so plans are described by what they can do.

    Deliberately NOT plan names. The billing model in this repository does not
    yet have tiers, and inventing STARTER/PROFESSIONAL/ENTERPRISE here would
    hard-code a commercial structure into the schema. A plan, when there is
    one, is a set of these.
    """

    MANUAL_PACKAGE_GENERATION = "sas.manual_package_generation"
    MANUAL_RESULT_UPLOAD = "sas.manual_result_upload"
    MANAGED_VALIDATION = "sas.managed_validation"
    CUSTOMER_CONNECTION = "sas.customer_connection"
    VALIDATION_ARCHIVE = "sas.validation_archive"


#: FEATURE FLAGS - default OFF for everything that does not work yet.
#:
#: The UI may show an unavailable option, because hiding a service a customer
#: might want to ask about is its own kind of dishonesty. It may not show one
#: as though it worked. `available_modes()` is what the API reports and the UI
#: renders from.
FEATURE_FLAGS: dict[SASCapability, bool] = {
    # Works end to end in this release.
    SASCapability.MANUAL_PACKAGE_GENERATION: True,
    SASCapability.MANUAL_RESULT_UPLOAD: True,
    SASCapability.VALIDATION_ARCHIVE: True,
    # OFF until this organisation holds SAS commercial/service-provider rights.
    SASCapability.MANAGED_VALIDATION: False,
    # OFF until there is a real customer environment to integrate against.
    # Building speculative API calls with nothing to test them on produces code
    # that looks finished and has never once run.
    SASCapability.CUSTOMER_CONNECTION: False,
}


def is_enabled(capability: SASCapability) -> bool:
    return FEATURE_FLAGS.get(capability, False)


def mode_is_available(mode: SASIntegrationMode) -> bool:
    if mode is SASIntegrationMode.NOT_CONFIGURED:
        return True
    if mode is SASIntegrationMode.MANUAL_UPLOAD:
        return is_enabled(SASCapability.MANUAL_PACKAGE_GENERATION)
    if mode is SASIntegrationMode.MANAGED:
        return is_enabled(SASCapability.MANAGED_VALIDATION)
    return is_enabled(SASCapability.CUSTOMER_CONNECTION)


#: What the UI says about a mode it cannot currently offer. Written here rather
#: than in the frontend so the API and the interface cannot drift into
#: promising different things.
UNAVAILABLE_REASON: dict[SASIntegrationMode, str] = {
    SASIntegrationMode.MANAGED: (
        "Managed SAS validation is not yet available. Availability depends on "
        "your subscription and on our licensed service availability."
    ),
    SASIntegrationMode.CUSTOMER_VIYA: (
        "Direct connection to a customer SAS Viya environment is not yet "
        "available. Manual validation is available now and keeps your SAS "
        "environment entirely under your organisation's control."
    ),
    SASIntegrationMode.CUSTOMER_REMOTE: (
        "Direct connection to a customer-managed remote SAS environment is not "
        "yet available. Manual validation is available now."
    ),
}

#: Shown before a customer connects an environment they operate. An
#: ACKNOWLEDGEMENT, not a licence check: this application cannot verify anyone's
#: SAS entitlement and does not claim to.
ACKNOWLEDGEMENT_TEXT = (
    "I confirm that my organization is authorized to use this SAS environment "
    "and to connect it to this application for validation."
)

#: Reassurance that is also a true statement about the architecture: in both
#: customer modes and in manual mode, no SAS program is ever executed by us.
CUSTOMER_CONTROL_NOTICE = (
    "Your SAS environment remains under your organisation's control."
)

MANAGED_AVAILABILITY_NOTICE = (
    "Managed SAS availability depends on your subscription and our licensed "
    "service availability."
)


__all__ = [
    "ACKNOWLEDGEMENT_TEXT",
    "CUSTOMER_CONTROL_NOTICE",
    "FEATURE_FLAGS",
    "MANAGED_AVAILABILITY_NOTICE",
    "UNAVAILABLE_REASON",
    "ManagedBillingMode",
    "OracleClosureDecision",
    "SASCapability",
    "SASIntegrationMode",
    "SASValidationRunStatus",
    "is_enabled",
    "mode_is_available",
]
