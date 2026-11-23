import math

from app.services.document_processing_service import (
    EMBEDDING_DIMENSIONS,
    embed_texts,
)


def embed_question(question: str) -> list[float]:
    """Create a normalized embedding for one non-empty question."""
    if not question.strip():
        raise ValueError("Question must not be empty or whitespace-only")

    embeddings = embed_texts([question])
    if len(embeddings) != 1:
        raise ValueError(f"Expected one question embedding; got {len(embeddings)}")

    embedding = [float(value) for value in embeddings[0]]
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Question embedding must contain {EMBEDDING_DIMENSIONS} values; "
            f"got {len(embedding)}"
        )
    if not all(math.isfinite(value) for value in embedding):
        raise ValueError("Question embedding values must all be finite")

    return embedding
