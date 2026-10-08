from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myproject.models.document import Document
from myproject.schemas.document import DocumentCreate


def create_document(
    db: Session,
    document_data: DocumentCreate,
    *,
    file_path: str,
) -> Document:
    """Create a document record from validated metadata and a stored file path.

    File upload and path generation happen outside this function. The caller
    supplies the resulting path because the database model requires it, while
    ``DocumentCreate`` intentionally does not expose this internal field.
    """
    if not file_path.strip():
        raise ValueError("file_path cannot be blank")

    now = datetime.now(timezone.utc)
    document = Document(
        user_id=document_data.user_id,
        name=document_data.name,
        file_name=document_data.file_name,
        file_path=file_path,
        file_size=document_data.file_size,
        mime_type=document_data.mime_type,
        status="QUEUED",
        progress=0,
        stage="QUEUED",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(document)
    return document


def get_document_by_id(db: Session, document_id: int) -> Document | None:
    """Return a document by primary key, or None if it does not exist."""
    return db.get(Document, document_id)


def get_documents_by_user(
    db: Session,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[Document]:
    """Return only documents owned by ``user_id``, in a stable page."""
    if user_id <= 0:
        raise ValueError("user_id must be greater than zero")
    if skip < 0:
        raise ValueError("skip must be zero or greater")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    statement = (
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.id)
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def update_document(
    db: Session,
    document_id: int,
    updates: dict[str, Any],
) -> Document | None:
    """Update editable document metadata or processing state.

    Values should already be validated by a request schema or processing
    component. Ownership, file storage, and file contents are not changed here.
    """
    document = db.get(Document, document_id)
    if document is None:
        return None

    allowed_fields = {
        "name",
        "file_name",
        "file_size",
        "mime_type",
        "status",
        "error_message",
    }
    unknown_fields = updates.keys() - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unsupported document update field(s): {names}")
    if not updates:
        raise ValueError("At least one field must be provided for update")

    for field, value in updates.items():
        if field in {"name", "file_name", "mime_type", "status"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
            value = value.strip()
        elif field == "file_size" and (not isinstance(value, int) or value < 0):
            raise ValueError("file_size must be a non-negative integer")
        elif field == "error_message" and value is not None and not isinstance(value, str):
            raise ValueError("error_message must be a string or None")
        setattr(document, field, value)

    document.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(document)
    return document


def delete_document(db: Session, document_id: int) -> bool:
    """Delete a document record; return False if it was not found."""
    document = db.get(Document, document_id)
    if document is None:
        return False

    db.delete(document)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
