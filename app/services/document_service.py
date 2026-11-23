import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core import BadRequestException, ConflictException, NotFoundException, ServiceUnavailableException
from app.core.celery_app import celery_app
from app.core.config import settings
from app.db import SessionLocal
from app.models import Document, User
from app.repositories import (
    create_document,
    delete_document,
    get_document_by_id,
    get_documents_by_user,
    update_document,
)
from app.schemas import DocumentCreate, DocumentUpdate

logger = logging.getLogger(__name__)


def get_owned_document(db: Session, document_id: int, user_id: int) -> Document:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user_id:
        raise NotFoundException("Document not found")
    return document


def upload_document(db: Session, user: User, name: str, file: UploadFile) -> Document:
    """Save an uploaded file locally and queue its background processing."""
    original_name = Path(file.filename or "").name
    if not original_name:
        raise BadRequestException("A filename is required")

    user_dir = Path(settings.UPLOAD_DIR) / str(user.id)
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
    return document


def list_documents(db: Session, user: User, skip: int, limit: int) -> list[Document]:
    return get_documents_by_user(db, user.id, skip=skip, limit=limit)


def rename_document(db: Session, document_id: int, user: User, payload: DocumentUpdate) -> Document:
    get_owned_document(db, document_id, user.id)
    return update_document(db, document_id, payload.model_dump(exclude_unset=True))


def remove_document(db: Session, document_id: int, user: User) -> None:
    document = get_owned_document(db, document_id, user.id)
    if document.status in {"QUEUED", "PROCESSING"}:
        raise ConflictException("Document cannot be deleted while processing")

    stored_path = Path(document.file_path)
    if delete_document(db, document_id):
        stored_path.unlink(missing_ok=True)


def progress_events(db: Session, document_id: int, user: User) -> Iterator[str]:
    """Subscribe to progress updates and return an SSE event iterator."""
    get_owned_document(db, document_id, user.id)
    owner_id = user.id
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        redis_client.ping()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(f"document:{document_id}:progress")
        logger.info("SSE subscribed: document_id=%s", document_id)
    except RedisError as exc:
        redis_client.close()
        raise ServiceUnavailableException("Progress events are temporarily unavailable") from exc

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

    def events() -> Iterator[str]:
        try:
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

    return events()
