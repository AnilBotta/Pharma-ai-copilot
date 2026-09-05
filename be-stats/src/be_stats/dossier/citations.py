"""What counts as a pinned regulatory citation. Defined once.

WHY THIS MODULE EXISTS AT ALL

Because the definition was written twice and the two copies disagreed.

`ConstantRecord.has_pinned_citation` required authority, document, section and
version. The release gate, three modules away, tested pinning as:

    if not record.regulatory_source.document_version:
        violation

So `document_version = "current"` passed the gate - the string is non-empty -
while the same citation was correctly excluded from the provenance layer's
pinned count. Two definitions of one concept, and the weaker one sat on the
control that decides whether something may be called VALIDATED.

That is exactly the class of failure this whole dossier exists to prevent, and
it was inside the dossier.

A POSITIVE DEFINITION, NOT A BLACKLIST

The tempting fix is to reject "current", "latest", "TBD". That is a promise to
have thought of every future vague word, and nobody can keep it: "in force",
"as published", "n/a", an empty-looking non-breaking space.

So the rule is positive. A pinned version must IDENTIFY WHICH ISSUE of the
document is meant, and a document is identified by a year or by a revision
marker. Every real citation in this package satisfies it:

    "final, May 2026"                                          -> 2026
    "CPMP/EWP/QWP/1401/98 Rev. 1, effective 1 August 2010"      -> Rev. 1, 2010
    "EMA/618604/2008 Rev. 13"                                   -> Rev. 13
    "EMA/531548/2024, adopted by CHMP 17 February 2025"         -> 2025
    "draft, reissued 2003"                                      -> 2003

and the vague ones do not:

    "current"                    identifies nothing
    "FDA guidance for industry"  names a category, not an issue

ONE AUTHORITY, BECAUSE A CITATION IS A PLACE TO LOOK

"ICH / FDA / EMA" is not a citation, it is a claim that three bodies agree. A
reader cannot open it. A citation naming more than one authority is therefore
not pinned, whatever else it carries.

EXCEPTIONS ARE DECLARED, NOT INFERRED

A citation that is not pinned and is KNOWN not to be pinned carries a
`CitationException` in the registry below: what is missing, what would close
it, and the finding tracking it. The registry is keyed by the `Citation`
object itself, so every record sharing that citation inherits the exception -
which is how a capability and the two constants beneath it stay consistent
without any of them naming a finding id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from be_stats.provenance import Citation

#: A version string identifies an issue if it carries a year or a revision.
#:
#: Deliberately permissive about FORM and strict about CONTENT: "May 2026",
#: "2010", "Rev. 13" and "v2" all pass, and no amount of confident-sounding
#: prose does.
_IDENTIFIES_AN_ISSUE = re.compile(
    r"(?:\b(?:19|20)\d{2}\b)"  # a four-digit year
    r"|(?:\brev\.?\s*\d)"  # Rev. 1, rev 13
    r"|(?:\brevision\s*\d)"
    r"|(?:\bv\d)",  # v2
    re.IGNORECASE,
)


def version_is_pinned(document_version: str) -> bool:
    """Does this version string say WHICH issue of the document is meant?

    The single rule. `release_gate`, `constants` and any future reader all
    call this rather than testing the string themselves.
    """
    return bool(document_version and _IDENTIFIES_AN_ISSUE.search(document_version))


def names_one_authority(authority: str) -> bool:
    """A citation must name one body, because it is a place to look.

    `/` and `,` are the two ways this package has actually spelled a list of
    authorities. A single authority never contains either - "FDA", "EMA",
    "ICH" - so the check is on the shape a list takes rather than on a
    vocabulary of known bodies, which would need maintaining.
    """
    return bool(authority) and not re.search(r"[/,]| and ", authority)


def is_pinned(citation: Citation) -> bool:
    """The canonical definition. Four conditions, all required.

    A citation is pinned when a reader can be handed it and find the same
    words: one authority, a named document, the section within it, and which
    issue of that document is meant.
    """
    return (
        names_one_authority(citation.authority)
        and bool(citation.document)
        and bool(citation.section)
        and version_is_pinned(citation.document_version)
    )


def why_not_pinned(citation: Citation) -> tuple[str, ...]:
    """Which conditions a citation fails, for a message worth reading.

    A bare "not pinned" sends somebody to compare four fields by eye.
    """
    reasons = []
    if not citation.authority:
        reasons.append("no authority")
    elif not names_one_authority(citation.authority):
        reasons.append(
            f"names more than one authority ({citation.authority!r}); a "
            "citation is a place to look, not a claim that bodies agree"
        )
    if not citation.document:
        reasons.append("no document")
    if not citation.section:
        reasons.append(
            "no section; a guidance runs to dozens of pages and a rule can "
            "sit beside its near-twin in another section of the same document"
        )
    if not citation.document_version:
        reasons.append("no document version")
    elif not version_is_pinned(citation.document_version):
        reasons.append(
            f"version {citation.document_version!r} identifies no issue of "
            "the document - a pinned version carries a year or a revision"
        )
    return tuple(reasons)


@dataclass(frozen=True, slots=True)
class CitationException:
    """A known-unpinned citation, declared rather than discovered.

    Carries the finding tracking it so that consumers - the release gate
    especially - can report WHICH open question blocks them without any of
    them hard-coding a finding id.
    """

    #: What is missing and why it has not been fixed by editing this file.
    reason: str
    #: The finding in `dossier.findings` that tracks it.
    tracked_as: str
    #: What would close it.
    resolution: str

    def explain(self) -> str:
        return f"{self.reason} Tracked as {self.tracked_as}. {self.resolution}"


#: Citations this package knows are not pinned, keyed by the citation itself.
#:
#: Keyed by the `Citation` OBJECT rather than by constant id or capability id,
#: which is what keeps the provenance layer and the release gate consistent
#: for free: `AVERAGE_BE_2X2` and the two conventional-interval constants all
#: reference the same object, so all three would inherit one exception and
#: none of them would name a finding.
#:
#: CURRENTLY EMPTY, AND THE MACHINERY IS STILL LOAD-BEARING
#:
#: The single entry was the conventional 80.00-125.00% interval, tracked as
#: DOSSIER-004. It was closed by reading ICH M13A 2.2.4 and the FDA and EMA
#: adoptions of it, so the exception went with it - a stale exception excludes
#: a good citation from the pinned count, which is the failure mode in the
#: opposite direction.
#:
#: The registry is NOT deleted along with its last entry. An empty dict makes
#: the invariant tests vacuous, so `test_the_exception_machinery_still_holds_
#: with_an_empty_registry` drives a fabricated exception through the same
#: paths. Deleting the mechanism would mean the next unpinned citation has
#: nowhere to be declared, and undeclared is how one gets absorbed.
CITATION_EXCEPTIONS: dict[Citation, CitationException] = {}


def exception_for(citation: Citation) -> CitationException | None:
    """The declared exception for this citation, if there is one."""
    return CITATION_EXCEPTIONS.get(citation)


def is_pinned_or_declared(citation: Citation) -> bool:
    """Pinned, OR unpinned with the gap declared.

    Used where the question is "has anybody looked at this", not "may this
    support a regulatory claim". The release gate asks the second question and
    calls `is_pinned` instead - a declared gap is still a gap.
    """
    return is_pinned(citation) or exception_for(citation) is not None
