"""Request and response models for the notification settings API."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.settings_module.repository import KNOWN_CONDITIONS


def _check_conditions(v: list[str]) -> list[str]:
    """Refuse an unknown condition rather than subscribing somebody to nothing.

    A typo would otherwise produce a recipient who is configured, looks
    configured on the page, and never receives anything - which is the failure
    this whole area keeps producing and the one hardest to notice.
    """
    unknown = [c for c in v if c not in KNOWN_CONDITIONS]
    if unknown:
        raise ValueError(
            f"Unknown alert type(s): {', '.join(unknown)}. "
            f"Valid values: {', '.join(KNOWN_CONDITIONS)}."
        )
    # Order and duplicates carry no meaning; storing them tidily keeps the audit
    # payloads comparable.
    return sorted(set(v))


class CreateRecipientRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    #: Empty means every alert type.
    conditions: list[str] = Field(default_factory=list, max_length=20)
    wants_immediate: bool = True
    wants_digest: bool = True

    @field_validator("email")
    @classmethod
    def _clean_email(cls, v: str) -> str:
        cleaned = v.strip()
        if "@" not in cleaned or " " in cleaned:
            raise ValueError("That does not look like an email address.")
        return cleaned

    @field_validator("conditions")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return _check_conditions(v)


class UpdateRecipientRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    conditions: list[str] | None = Field(default=None, max_length=20)
    wants_immediate: bool | None = None
    wants_digest: bool | None = None
    is_active: bool | None = None

    @field_validator("conditions")
    @classmethod
    def _known(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_conditions(v)


class RecipientResponse(BaseModel):
    id: str
    email: str
    name: str | None
    is_active: bool
    conditions: list[str]
    wants_immediate: bool
    wants_digest: bool

    #: So the page can show that an address is really receiving mail, rather
    #: than only that somebody once typed it in.
    sent_count: int
    last_sent_at: str | None

    created_at: str
    updated_at: str


class AlertType(BaseModel):
    """One subscribable condition, with the name a person would recognise."""

    condition: str
    name: str
    description: str | None
    severity: str
    is_active: bool


__all__ = [
    "AlertType",
    "CreateRecipientRequest",
    "RecipientResponse",
    "UpdateRecipientRequest",
]
