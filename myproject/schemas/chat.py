from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    """Input for starting a chat session for a user and document."""

    user_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    title: Annotated[str | None, Field(max_length=255)] = None


class ChatSessionResponse(BaseModel):
    """Chat session details returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    user_id: int
    document_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(BaseModel):
    """Input for adding a message to an existing chat session."""

    session_id: int = Field(gt=0)
    role: Annotated[str, Field(min_length=1, max_length=20)]
    content: Annotated[str, Field(min_length=1)]


class ChatMessageResponse(BaseModel):
    """Chat message details returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime
