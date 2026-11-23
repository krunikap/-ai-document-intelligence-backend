import logging
from google import genai
from collections.abc import AsyncIterator

from app.core.config import settings


logger = logging.getLogger(__name__)
client = genai.Client(api_key=settings.GEMINI_API_KEY)


def generate_answer(prompt: str) -> str:
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )

    answer = response.text
    logger.info("Gemini response text: %r", answer)

    if not answer:
        raise RuntimeError("Gemini returned an empty response")

    return answer


async def generate_answer_stream(prompt: str) -> AsyncIterator[str]:
    """Yield text from the configured Gemini model's supported async stream."""
    stream = await client.aio.models.generate_content_stream(
        model=settings.GEMINI_MODEL,
        contents=prompt,
    )
    response_parts: list[str] = []
    try:
        async for response in stream:
            text = response.text
            if text:
                response_parts.append(text)
                yield text
    finally:
        logger.info("Gemini streamed response text: %r", "".join(response_parts))
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
