from dataclasses import dataclass
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.services.document_processing_service import EMBEDDING_DIMENSIONS


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    content: str
    page_number: int | None
    chunk_index: int
    distance: float
    similarity: float


def retrieve_relevant_chunks(
    db: Session,
    document_id: int,
    question_embedding: list[float],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Return the nearest embedded chunks belonging to one document."""
    if len(question_embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Question embedding must contain {EMBEDDING_DIMENSIONS} values; "
            f"got {len(question_embedding)}"
        )
    try:
        embedding = [float(value) for value in question_embedding]
    except (TypeError, ValueError) as exc:
        raise ValueError("Question embedding values must be finite numbers") from exc
    if not all(math.isfinite(value) for value in embedding):
        raise ValueError("Question embedding values must all be finite")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
    statement = (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.content,
            DocumentChunk.page_number,
            DocumentChunk.chunk_index,
            distance,
        )
        .where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(distance.asc())
        .limit(top_k)
    )

    rows = db.execute(statement).all()
    return [
        RetrievedChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            content=row.content,
            page_number=row.page_number,
            chunk_index=row.chunk_index,
            distance=float(row.distance),
            similarity=1.0 - float(row.distance),
        )
        for row in rows
    ]
