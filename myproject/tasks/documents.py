from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
from time import perf_counter

from celery.signals import worker_ready
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update

from myproject.celery_app import celery_app
from myproject.config import REDIS_URL
from myproject.database import SessionLocal
from myproject.models.document import Document
from myproject.models.document_chunk import DocumentChunk
from myproject.services.document_processing import (
    EMBEDDING_BATCH_SIZE,
    embedding_runtime_info,
    embed_texts,
    extract_pages,
    make_chunks,
)

logger = logging.getLogger(__name__)


def _profiled_commit(db, profile: dict, label: str) -> None:
    started_at = perf_counter()
    try:
        db.commit()
    finally:
        elapsed = perf_counter() - started_at
        profile["db_commit_seconds"] += elapsed
        profile["db_commit_count"] += 1
        logger.info(
            "DB commit %s: %.3fs (count=%s cumulative=%.3fs)",
            label,
            elapsed,
            profile["db_commit_count"],
            profile["db_commit_seconds"],
        )


def _set_progress(
    db,
    document: Document,
    *,
    status: str,
    progress: int,
    stage: str,
    error_message: str | None = None,
    profile: dict | None = None,
) -> None:
    document.status = status
    document.progress = progress
    document.stage = stage
    document.error_message = error_message
    document.updated_at = datetime.now(timezone.utc)
    event = {
        "document_id": document.id,
        "status": document.status,
        "stage": document.stage,
        "progress": document.progress,
        "error_message": document.error_message,
        "updated_at": document.updated_at.isoformat(),
    }
    if profile is None:
        db.commit()
    else:
        _profiled_commit(db, profile, f"progress:{stage}:{progress}")
    try:
        subscribers = _redis_client().publish(
            f"document:{document.id}:progress", json.dumps(event)
        )
        logger.info(
            "Redis progress published: document_id=%s status=%s progress=%s subscribers=%s",
            document.id,
            document.status,
            document.progress,
            subscribers,
        )
    except RedisError:
        logger.exception(
            "Could not publish document progress event for document %s",
            document.id,
        )


_redis = None


def _redis_client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


@worker_ready.connect
def recover_queued_documents(sender=None, **kwargs) -> None:
    """Requeue DB jobs that were left queued after a worker stopped/crashed."""
    pool_class = getattr(sender, "pool_cls", None)
    pool_name = getattr(pool_class, "__name__", str(pool_class or "unknown"))
    logger.info(
        "Celery worker ready: hostname=%s pool=%s concurrency=%s cpu_count=%s",
        getattr(sender, "hostname", "unknown"),
        pool_name,
        getattr(sender, "concurrency", "unknown"),
        os.cpu_count(),
    )
    db = SessionLocal()
    try:
        queued_ids = db.scalars(
            select(Document.id).where(Document.status == "QUEUED")
        ).all()
    finally:
        db.close()

    for document_id in queued_ids:
        celery_app.send_task("documents.process_document", args=[document_id])
        logger.info("Recovered queued document job: document_id=%s", document_id)


@celery_app.task(name="documents.process_document", ignore_result=True)
def process_document(document_id: int) -> None:
    """Extract, chunk, and embed one uploaded document."""
    processing_started = perf_counter()
    profile = {
        "extraction_seconds": 0.0,
        "chunking_seconds": 0.0,
        "model_setup_seconds": 0.0,
        "embedding_seconds": 0.0,
        "db_insert_seconds": 0.0,
        "db_commit_seconds": 0.0,
        "db_commit_count": 0,
        "total_chunks": 0,
        "processing_batch_size": 0,
        "embedding_batch_count": 0,
        "model_name": "unknown",
        "device": "unknown",
        "model_reused": False,
    }
    db = SessionLocal()
    try:
        # Claim atomically so a recovered job and an already queued message
        # cannot process the same document twice.
        claimed = db.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == "QUEUED")
            .values(
                status="PROCESSING",
                stage="STARTING",
                progress=0,
                error_message=None,
                updated_at=datetime.now(timezone.utc),
            )
        ).rowcount
        _profiled_commit(db, profile, "claim-document")
        if not claimed:
            return

        document = db.get(Document, document_id)
        if document is None:
            return

        path = Path(document.file_path)
        if not path.is_file():
            raise FileNotFoundError("Uploaded file is missing from local storage")

        _set_progress(
            db,
            document,
            status="PROCESSING",
            progress=5,
            stage="EXTRACTING",
            profile=profile,
        )
        stage_started = perf_counter()
        pages = extract_pages(str(path))
        profile["extraction_seconds"] = perf_counter() - stage_started
        logger.info(
            "Document extraction: document_id=%s seconds=%.3f pages=%s",
            document_id,
            profile["extraction_seconds"],
            len(pages),
        )
        _set_progress(
            db,
            document,
            status="PROCESSING",
            progress=10,
            stage="CHUNKING",
            profile=profile,
        )
        stage_started = perf_counter()
        chunks = make_chunks(pages)
        profile["chunking_seconds"] = perf_counter() - stage_started
        profile["total_chunks"] = len(chunks)
        logger.info(
            "Document chunking: document_id=%s seconds=%.3f total_chunks=%s",
            document_id,
            profile["chunking_seconds"],
            profile["total_chunks"],
        )
        if not chunks:
            raise ValueError("No readable text was found in this document")

        _set_progress(
            db,
            document,
            status="PROCESSING",
            progress=15,
            stage="EMBEDDING",
            profile=profile,
        )
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document.id
        ).delete(synchronize_session=False)
        _profiled_commit(db, profile, "delete-existing-chunks")

        model_started = perf_counter()
        model_name, device, model_reused = embedding_runtime_info()
        profile["model_setup_seconds"] = perf_counter() - model_started
        profile["model_name"] = model_name
        profile["device"] = device
        profile["model_reused"] = model_reused
        logger.info(
            "Embedding runtime: document_id=%s model=%s device=%s reused_from_cache=%s setup_seconds=%.3f internal_batch_size=%s",
            document_id,
            model_name,
            device,
            model_reused,
            profile["model_setup_seconds"],
            EMBEDDING_BATCH_SIZE,
        )

        total = len(chunks)
        # Keep embedding work small enough that progress can be reported at
        # roughly the same 2% intervals as the Node worker. Cap each model
        # call at the embedding service's normal batch size.
        progress_batch_size = min(
            EMBEDDING_BATCH_SIZE, max(1, math.ceil(total / 42))
        )
        profile["processing_batch_size"] = progress_batch_size
        logger.info(
            "Embedding batches: document_id=%s total_chunks=%s outer_batch_size=%s internal_batch_size=%s",
            document_id,
            total,
            progress_batch_size,
            EMBEDDING_BATCH_SIZE,
        )
        next_progress = 17
        for batch_start in range(0, total, progress_batch_size):
            batch = chunks[batch_start : batch_start + progress_batch_size]
            batch_number = profile["embedding_batch_count"] + 1
            batch_started = perf_counter()
            vectors = embed_texts([content for _, _, content in batch])
            batch_elapsed = perf_counter() - batch_started
            profile["embedding_batch_count"] = batch_number
            profile["embedding_seconds"] += batch_elapsed
            logger.info(
                "Embedding batch %s: document_id=%s chunks=%s seconds=%.3f",
                batch_number,
                document_id,
                len(batch),
                batch_elapsed,
            )
            db.add_all(
                [
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=chunk_index,
                        page_number=page_number,
                        content=content,
                        embedding=vector,
                        created_at=datetime.now(timezone.utc),
                    )
                    for (chunk_index, page_number, content), vector in zip(
                        batch, vectors, strict=True
                    )
                ]
            )
            insert_started = perf_counter()
            try:
                db.flush()
            finally:
                insert_elapsed = perf_counter() - insert_started
                profile["db_insert_seconds"] += insert_elapsed
                logger.info(
                    "DB insert batch %s: document_id=%s rows=%s seconds=%.3f cumulative=%.3f",
                    batch_number,
                    document_id,
                    len(batch),
                    insert_elapsed,
                    profile["db_insert_seconds"],
                )
            _profiled_commit(db, profile, f"embedding-batch-{batch_number}")

            completed_chunks = min(batch_start + len(batch), total)
            target_progress = 15 + (83 * completed_chunks // total)
            while next_progress <= min(target_progress, 97):
                _set_progress(
                    db,
                    document,
                    status="PROCESSING",
                    progress=next_progress,
                    stage="EMBEDDING",
                    profile=profile,
                )
                next_progress += 2

        # Embedding occupies 15–98%; completion is reported separately as 100%.
        if document.progress < 98:
            _set_progress(
                db,
                document,
                status="PROCESSING",
                progress=98,
                stage="EMBEDDING",
                profile=profile,
            )

        _set_progress(
            db,
            document,
            status="COMPLETED",
            progress=100,
            stage="COMPLETED",
            profile=profile,
        )
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        if document is not None:
            _set_progress(
                db,
                document,
                status="FAILED",
                progress=document.progress,
                stage="FAILED",
                error_message=str(exc)[:2000],
                profile=profile,
            )
        raise
    finally:
        db.close()
        logger.info(
            "Document processing profile: document_id=%s total_seconds=%.3f extraction_seconds=%.3f chunking_seconds=%.3f total_chunks=%s model=%s device=%s model_reused=%s model_setup_seconds=%.3f outer_batch_size=%s internal_batch_size=%s embedding_batches=%s embedding_seconds=%.3f db_insert_seconds=%.3f db_commit_count=%s db_commit_seconds=%.3f",
            document_id,
            perf_counter() - processing_started,
            profile["extraction_seconds"],
            profile["chunking_seconds"],
            profile["total_chunks"],
            profile["model_name"],
            profile["device"],
            profile["model_reused"],
            profile["model_setup_seconds"],
            profile["processing_batch_size"],
            EMBEDDING_BATCH_SIZE,
            profile["embedding_batch_count"],
            profile["embedding_seconds"],
            profile["db_insert_seconds"],
            profile["db_commit_count"],
            profile["db_commit_seconds"],
        )
