import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from redis import Redis
from redis.exceptions import RedisError
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
from myproject.config import REDIS_URL
from myproject.database import SessionLocal
from myproject.dependencies import get_current_user, get_db
from myproject.models.document import Document
from myproject.models.user import User
from myproject.schemas.document import DocumentCreate, DocumentResponse, DocumentUpdate

router = APIRouter(prefix="/documents", tags=["documents"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
logger = logging.getLogger(__name__)


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
    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        redis_client.ping()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(f"document:{document_id}:progress")
        logger.info("SSE subscribed: document_id=%s", document_id)
    except RedisError as exc:
        redis_client.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Progress events are temporarily unavailable",
        ) from exc

    def events() -> Iterator[str]:
        try:
            def read_current_progress() -> dict | None:
                snapshot_db = SessionLocal()
                try:
                    current = snapshot_db.get(Document, document_id)
                    if current is None or current.user_id != owner_id:
                        return None
                    return {
                        "document_id": current.id,
                        "status": current.status,
                        "stage": current.stage,
                        "progress": current.progress,
                        "error_message": current.error_message,
                        "updated_at": current.updated_at.isoformat(),
                    }
                finally:
                    snapshot_db.close()

            data = read_current_progress()
            if data is None:
                return

            last_updated = data["updated_at"]
            logger.info(
                "SSE initial state: document_id=%s status=%s progress=%s",
                document_id,
                data["status"],
                data["progress"],
            )
            yield f"event: progress\ndata: {json.dumps(data)}\n\n"
            if data["status"] in {"COMPLETED", "FAILED"}:
                return

            last_heartbeat = time.monotonic()
            while True:
                message = pubsub.get_message(timeout=1)
                update = None
                if message is not None:
                    try:
                        update = json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        pass

                # Redis Pub/Sub is immediate but not persistent. Check the DB
                # after idle polls so a missed terminal event cannot leave the
                # browser stuck on an old percentage.
                if update is None or update.get("updated_at", "") <= last_updated:
                    update = read_current_progress()

                if update is not None and update.get("updated_at", "") > last_updated:
                    last_updated = update["updated_at"]
                    logger.info(
                        "SSE progress sent: document_id=%s status=%s progress=%s",
                        document_id,
                        update["status"],
                        update["progress"],
                    )
                    yield f"event: progress\ndata: {json.dumps(update)}\n\n"
                    if update.get("status") in {"COMPLETED", "FAILED"}:
                        return
                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
        finally:
            pubsub.close()
            redis_client.close()

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
