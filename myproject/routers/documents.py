import json
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from myproject.crud.document import (
    create_document,
    delete_document,
    get_document_by_id,
    get_documents_by_user,
    update_document,
)
from myproject.celery_app import celery_app
from myproject.dependencies import get_current_user, get_db
from myproject.database import SessionLocal
from myproject.models.document import Document
from myproject.models.user import User
from myproject.schemas.document import DocumentCreate, DocumentResponse, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    name: str = Form(..., min_length=1, max_length=255),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Save an uploaded file locally and queue its background processing."""
    original_name = Path(file.filename or "").name
    if not original_name:
        raise HTTPException(status_code=400, detail="A filename is required")

    user_dir = UPLOAD_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    stored_path = user_dir / f"{uuid4().hex}{Path(original_name).suffix}"

    size = 0
    try:
        with stored_path.open("wb") as destination:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="File exceeds the 100 MB limit")
                destination.write(chunk)

        payload = DocumentCreate(
            user_id=user.id,
            name=name.strip(),
            file_name=original_name,
            file_size=size,
            mime_type=file.content_type or "application/octet-stream",
        )
        document = create_document(db, payload, file_path=str(stored_path))
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

    try:
        celery_app.send_task("documents.process_document", args=[document.id])
    except Exception as exc:
        document.status = "FAILED"
        document.stage = "FAILED"
        document.error_message = f"Could not queue processing: {str(exc)[:1900]}"
        db.commit()
        db.refresh(document)
    return DocumentResponse.model_validate(document)


@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentResponse]:
    documents = get_documents_by_user(db, user.id, skip=skip, limit=limit)
    return [DocumentResponse.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentResponse)
def read_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/events")
def document_progress_events(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    owner_id = user.id

    def events() -> Iterator[str]:
        previous_data = None
        idle_ticks = 0
        while True:
            event_db = SessionLocal()
            try:
                current = event_db.get(Document, document_id)
                if current is None or current.user_id != owner_id:
                    return
                data = {
                    "document_id": current.id,
                    "status": current.status,
                    "stage": current.stage,
                    "progress": current.progress,
                    "error_message": current.error_message,
                }
                terminal = current.status in {"COMPLETED", "FAILED"}
            finally:
                event_db.close()

            if data != previous_data:
                yield f"data: {json.dumps(data)}\n\n"
                previous_data = data
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 15:
                    yield ": keep-alive\n\n"
                    idle_ticks = 0
            if terminal:
                return
            time.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
def rename_document(
    document_id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    updated = update_document(db, document_id, payload.model_dump(exclude_unset=True))
    return DocumentResponse.model_validate(updated)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status in {"QUEUED", "PROCESSING"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document cannot be deleted while processing",
        )

    stored_path = Path(document.file_path)
    deleted = delete_document(db, document_id)
    if deleted:
        stored_path.unlink(missing_ok=True)
