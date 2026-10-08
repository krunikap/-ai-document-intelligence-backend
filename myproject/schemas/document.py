from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    """Client-visible document metadata used when creating a document record."""

    user_id: int = Field(gt=0)
    name: Annotated[str, Field(min_length=1, max_length=255)]
    file_name: Annotated[str, Field(min_length=1, max_length=255)]
    file_size: int = Field(ge=0)
    mime_type: Annotated[str, Field(min_length=1, max_length=100)]


class DocumentUpdate(BaseModel):
    """Fields a user may edit on their document."""

    name: Annotated[str, Field(min_length=1, max_length=255)]


class DocumentResponse(BaseModel):
    """Public document details. Storage path is kept internal."""

    model_config = {"from_attributes": True}

    id: int
    user_id: int
    name: str
    file_name: str
    file_size: int
    mime_type: str
    status: str
    progress: int
    stage: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
