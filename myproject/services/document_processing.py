from functools import lru_cache
import logging
from pathlib import Path
from time import perf_counter

from sentence_transformers import SentenceTransformer

from myproject.config import EMBEDDING_MODEL

EMBEDDING_DIMENSIONS = 384
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
EMBEDDING_BATCH_SIZE = 256
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _embedding_model() -> SentenceTransformer:
    started_at = perf_counter()
    model = SentenceTransformer(EMBEDDING_MODEL)
    dimensions = model.get_sentence_embedding_dimension()
    if dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding model must return {EMBEDDING_DIMENSIONS} values; got {dimensions}"
        )
    logger.info(
        "Embedding model loaded: model=%s device=%s dimensions=%s load_seconds=%.3f",
        EMBEDDING_MODEL,
        model.device,
        dimensions,
        perf_counter() - started_at,
    )
    return model


def embedding_runtime_info() -> tuple[str, str, bool]:
    """Return model/device/cache state, loading the cached model if needed."""
    was_loaded = _embedding_model.cache_info().currsize > 0
    model = _embedding_model()
    return EMBEDDING_MODEL, str(model.device), was_loaded


def extract_pages(file_path: str) -> list[tuple[int | None, str]]:
    """Extract text from supported local document formats."""
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [
            (page_number, page.extract_text() or "")
            for page_number, page in enumerate(reader.pages, start=1)
        ]

    if extension == ".docx":
        from docx import Document as WordDocument

        document = WordDocument(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return [(None, text)]

    if extension in {".txt", ".md", ".csv"}:
        return [(None, path.read_text(encoding="utf-8-sig"))]

    raise ValueError(f"Unsupported file type: {extension or 'no extension'}")


def make_chunks(pages: list[tuple[int | None, str]]) -> list[tuple[int, int | None, str]]:
    """Split extracted text into overlapping, page-aware chunks."""
    chunks: list[tuple[int, int | None, str]] = []
    for page_number, text in pages:
        normalized = " ".join(text.split())
        if not normalized:
            continue

        start = 0
        while start < len(normalized):
            end = min(start + CHUNK_SIZE, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind(" ", start + CHUNK_SIZE // 2, end)
                if boundary > start:
                    end = boundary
            content = normalized[start:end].strip()
            if content:
                chunks.append((len(chunks), page_number, content))
            if end >= len(normalized):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = _embedding_model().encode(
        texts,
        batch_size=EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vectors.tolist()
