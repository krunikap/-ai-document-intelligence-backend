from datetime import datetime, timezone
from pathlib import Path

from myproject.celery_app import celery_app
from myproject.database import SessionLocal
from myproject.models.document import Document
from myproject.models.document_chunk import DocumentChunk
from myproject.services.document_processing import (
    EMBEDDING_BATCH_SIZE,
    embed_texts,
    extract_pages,
    make_chunks,
)


def _set_progress(
    db,
    document: Document,
    *,
    status: str,
    progress: int,
    stage: str,
    error_message: str | None = None,
) -> None:
    document.status = status
    document.progress = progress
    document.stage = stage
    document.error_message = error_message
    document.updated_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="documents.process_document", ignore_result=True)
def process_document(document_id: int) -> None:
    """Extract, chunk, and embed one uploaded document."""
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return

        path = Path(document.file_path)
        if not path.is_file():
            raise FileNotFoundError("Uploaded file is missing from local storage")

        _set_progress(
            db, document, status="PROCESSING", progress=5, stage="EXTRACTING"
        )
        pages = extract_pages(str(path))
        _set_progress(
            db, document, status="PROCESSING", progress=10, stage="CHUNKING"
        )
        chunks = make_chunks(pages)
        if not chunks:
            raise ValueError("No readable text was found in this document")

        _set_progress(
            db, document, status="PROCESSING", progress=15, stage="EMBEDDING"
        )
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document.id
        ).delete(synchronize_session=False)
        db.commit()

        total = len(chunks)
        for batch_start in range(0, total, EMBEDDING_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + EMBEDDING_BATCH_SIZE]
            vectors = embed_texts([content for _, _, content in batch])
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
            progress = 15 + int(80 * min(batch_start + len(batch), total) / total)
            _set_progress(
                db,
                document,
                status="PROCESSING",
                progress=progress,
                stage="EMBEDDING",
            )

        _set_progress(
            db, document, status="COMPLETED", progress=100, stage="COMPLETED"
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
            )
        raise
    finally:
        db.close()
