"""Request and response shapes for the Manager Agent API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    role: str
    content: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None
    #: Deliberately not returned. The full result is kept in the database for
    #: the record, but replaying it to the browser would send tens of thousands
    #: of tokens of gate data the UI already has better ways to show.
    truncated: bool = False
    truncated_reason: str | None = None
    created_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[MessageOut] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
