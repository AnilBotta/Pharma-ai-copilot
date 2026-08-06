"""Normalised records returned by external providers.

Every provider adapter converts its own response format into these models. The
rest of the system - deduplication, ranking, evidence creation, the graph - only
ever sees these types, so adding a provider never changes anything downstream.

Fields are deliberately conservative. Where a provider does not supply a value
the field is ``None``, never a guess and never a placeholder. ``access_level``
in particular records what was actually retrieved so no downstream text can
claim full text was reviewed when only an abstract was available.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccessLevel(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"


class EvidenceCategory(StrEnum):
    REVIEW = "review"
    IN_VITRO = "in_vitro"
    IN_VIVO = "in_vivo"
    CLINICAL = "clinical"
    FORMULATION = "formulation"
    TOXICOLOGY = "toxicology"
    MANUFACTURING = "manufacturing"
    ANALYTICAL = "analytical"
    OTHER = "other"


class PatentRecordType(StrEnum):
    """Distinctions the product must preserve and display."""

    PUBLISHED_APPLICATION = "published_application"
    GRANTED_PATENT = "granted_patent"
    FAMILY_RECORD = "family_record"


# --------------------------------------------------------------------------- #
# Search inputs
# --------------------------------------------------------------------------- #


class SearchFilters(BaseModel):
    """Provider-agnostic filters. Adapters translate what they support and
    ignore what they do not, reporting the difference in `SearchResult.notes`."""

    model_config = ConfigDict(frozen=True)

    date_from: int | None = Field(default=None, ge=1800, le=2200)
    date_to: int | None = Field(default=None, ge=1800, le=2200)
    max_results: int = Field(default=25, ge=1, le=200)
    jurisdictions: tuple[str, ...] = ()
    open_access_only: bool = False

    @model_validator(mode="after")
    def _dates_ordered(self) -> SearchFilters:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


# --------------------------------------------------------------------------- #
# Literature
# --------------------------------------------------------------------------- #

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


class LiteratureRecord(BaseModel):
    """A publication retrieved from a literature provider."""

    provider: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: date | None = None
    publication_year: int | None = None

    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    url: str | None = None

    publication_types: list[str] = Field(default_factory=list)
    is_preprint: bool = False
    is_open_access: bool = False
    full_text: str | None = None

    raw: dict | None = None

    @field_validator("doi")
    @classmethod
    def _normalise_doi(cls, v: str | None) -> str | None:
        """Strip common prefixes and lowercase. DOIs are case-insensitive, and
        normalising here is what makes cross-provider deduplication work."""
        if not v:
            return None
        cleaned = v.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :]
        cleaned = cleaned.strip().lower()
        return cleaned if _DOI_RE.match(cleaned) else None

    @field_validator("pmid")
    @classmethod
    def _clean_pmid(cls, v: str | None) -> str | None:
        """A PMID is a bare integer. Anything else is rejected rather than
        coerced -- a mangled identifier resolves to the wrong paper, or to
        nothing, and either way misattributes the evidence."""
        if not v:
            return None
        cleaned = v.strip()
        return cleaned if cleaned.isdigit() else None

    @field_validator("pmcid")
    @classmethod
    def _clean_pmcid(cls, v: str | None) -> str | None:
        """A PMCID is 'PMC' followed by digits. The prefix is normalised on,
        but only when what remains is actually numeric."""
        if not v:
            return None
        cleaned = v.strip().upper()
        digits = cleaned.removeprefix("PMC")
        return f"PMC{digits}" if digits.isdigit() else None

    @property
    def has_full_text(self) -> bool:
        return bool(self.full_text and self.full_text.strip())

    @property
    def access_level(self) -> AccessLevel:
        """What we actually hold. Never upgraded optimistically."""
        if self.has_full_text:
            return AccessLevel.FULL_TEXT
        if self.abstract and self.abstract.strip():
            return AccessLevel.ABSTRACT_ONLY
        return AccessLevel.METADATA_ONLY

    @property
    def best_url(self) -> str | None:
        """A link built from a verified identifier, never invented."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        if self.pmcid:
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{self.pmcid}/"
        return self.url

    @property
    def has_identifier(self) -> bool:
        """Mirrors the database's literature_has_identifier constraint."""
        return bool(self.doi or self.pmid or self.pmcid or self.url)

    def normalised_title(self) -> str:
        """Lowercased, punctuation-stripped title used as a last-resort
        deduplication key when no shared identifier exists."""
        return re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()


# --------------------------------------------------------------------------- #
# Patents
# --------------------------------------------------------------------------- #


class PatentRecord(BaseModel):
    """A patent document retrieved from a patent provider."""

    provider: str
    publication_number: str
    title: str | None = None
    abstract: str | None = None

    application_number: str | None = None
    family_id: str | None = None
    kind_code: str | None = None
    jurisdiction: str | None = None
    record_type: PatentRecordType = PatentRecordType.PUBLISHED_APPLICATION

    priority_date: date | None = None
    filing_date: date | None = None
    publication_date: date | None = None

    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)

    cpc_classifications: list[str] = Field(default_factory=list)
    ipc_classifications: list[str] = Field(default_factory=list)

    legal_status: str | None = None
    legal_status_date: date | None = None

    raw: dict | None = None

    @field_validator("publication_number")
    @classmethod
    def _normalise_publication_number(cls, v: str) -> str:
        """Uppercase and strip separators so EP 1234567 A1, EP1234567A1 and
        ep-1234567-a1 collapse to one key."""
        return re.sub(r"[\s\-/]", "", v).upper()

    @property
    def access_level(self) -> AccessLevel:
        return AccessLevel.ABSTRACT_ONLY if self.abstract else AccessLevel.METADATA_ONLY

    @property
    def best_url(self) -> str | None:
        """Espacenet link derived from the publication number."""
        if not self.publication_number:
            return None
        return (
            "https://worldwide.espacenet.com/patent/search?q="
            f"pn%3D{self.publication_number}"
        )

    @property
    def family_key(self) -> str:
        """Deduplication key. Family members collapse to one entry; without a
        family id the document stands alone."""
        return self.family_id or self.publication_number


# --------------------------------------------------------------------------- #
# Search output
# --------------------------------------------------------------------------- #


class SearchResult[T: (LiteratureRecord, PatentRecord)](BaseModel):
    """Outcome of one provider search.

    A failed search returns ``ok=False`` with an empty ``records`` list and a
    populated ``error``. It never returns substitute or synthesised results -
    an empty list is an honest answer, invented data is not.
    """

    provider: str
    query: str
    records: list[T] = Field(default_factory=list)
    total_available: int | None = None
    from_cache: bool = False
    duration_ms: int = 0
    ok: bool = True
    error: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)
