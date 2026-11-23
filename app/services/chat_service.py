import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import status
from sqlalchemy.orm import Session

from app.core import (
    AppException,
    BadRequestException,
    ConflictException,
    NotFoundException,
    ServiceUnavailableException,
    UnprocessableException,
)
from app.models import ChatMessage, ChatSession, Document, User
from app.repositories import (
    create_chat_message,
    create_chat_session,
    delete_chat_session,
    get_chat_session_by_id,
    get_chat_sessions_by_document,
    get_chat_sessions_by_user,
    get_document_by_id,
    get_latest_unanswered_user_message,
    get_messages_by_session,
)
from app.schemas import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSourceReference,
    ChatTurnResponse,
)
from app.services.ai_service import (
    _remove_unverified_references,
    generate_document_answer,
    stream_document_answer,
)
from app.services.embedding_service import embed_question
from app.services.retrieval_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

_CHAT_FAILURES = {
    "embedding": (
        "QUESTION_EMBEDDING_FAILED",
        "We couldn't prepare your question for document search. Your question was saved; please retry.",
    ),
    "retrieval": (
        "DOCUMENT_SEARCH_FAILED",
        "We couldn't search this document right now. Your question was saved; please retry.",
    ),
    "generation": (
        "ANSWER_GENERATION_FAILED",
        "The AI service couldn't generate an answer right now. Your question was saved; please retry in a moment.",
    ),
    "persistence": (
        "ANSWER_SAVE_FAILED",
        "An answer was generated but couldn't be saved to chat history. Please retry.",
    ),
    "timeout": (
        "ANSWER_GENERATION_TIMEOUT",
        "Answer generation took too long. Your question was saved; please retry.",
    ),
    "empty": (
        "EMPTY_ANSWER",
        "The AI service returned an empty answer. Your question was saved; please retry.",
    ),
    "unexpected": (
        "CHAT_REQUEST_FAILED",
        "We couldn't complete your request because of a server error. Your question was saved; please retry.",
    ),
}


def _chat_failure(stage: str) -> tuple[str, str]:
    return _CHAT_FAILURES.get(stage, _CHAT_FAILURES["unexpected"])


def _log_chat_failure(stage: str, session_id: int, exc: Exception) -> None:
    logger.error(
        "Chat request failed stage=%s session_id=%s error_type=%s",
        stage,
        session_id,
        type(exc).__name__,
    )


def _save_chat_error(
    db: Session,
    session_id: int,
    user_id: int,
    stage: str,
) -> dict | None:
    """Persist a safe error as a history message, without exception details."""
    code, message = _chat_failure(stage)
    try:
        saved = create_chat_message(
            db,
            ChatMessageCreate(session_id=session_id, role="error", content=message),
            user_id,
        )
        if saved is None:
            return None
        return ChatMessageResponse.model_validate(saved).model_dump(mode="json")
    except Exception as exc:
        _log_chat_failure("error_message_persistence", session_id, exc)
        return None


def _sse_chat_error(db: Session, session_id: int, user_id: int, stage: str) -> str:
    code, message = _chat_failure(stage)
    error_message = _save_chat_error(db, session_id, user_id, stage)
    return _sse(
        "error",
        {"code": code, "message": message, "chat_message": error_message},
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_references(chunks) -> list[ChatSourceReference]:
    return [
        ChatSourceReference(
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            excerpt=chunk.content[:300],
        )
        for chunk in chunks
    ]


def get_owned_document(
    db: Session,
    document_id: int,
    user_id: int,
    *,
    require_completed: bool = False,
) -> Document:
    document = get_document_by_id(db, document_id)
    if document is None or document.user_id != user_id:
        raise NotFoundException("Document not found")
    if require_completed and document.status == "FAILED":
        raise ConflictException(
            "Document processing failed; chat is unavailable for this document."
        )
    if require_completed and document.status != "COMPLETED":
        raise ConflictException(
            "Document processing is still in progress; try again when it completes."
        )
    return document


def get_owned_session(db: Session, session_id: int, user_id: int) -> ChatSession:
    chat_session = get_chat_session_by_id(db, session_id, user_id)
    if chat_session is None:
        raise NotFoundException("Chat session not found")
    return chat_session


def _generate_chat_turn(
    db: Session,
    chat_session: ChatSession,
    question: str,
    user: User,
) -> ChatTurnResponse:
    unanswered_message = get_latest_unanswered_user_message(db, chat_session.id)
    if (
        unanswered_message is not None
        and unanswered_message.content == question
    ):
        user_message = unanswered_message
    else:
        user_payload = ChatMessageCreate(
            session_id=chat_session.id,
            role="user",
            content=question,
        )
        user_message = create_chat_message(db, user_payload, user.id)
        if user_message is None:
            raise NotFoundException("Chat session not found")

    try:
        question_embedding = embed_question(question)
    except Exception as exc:
        _log_chat_failure("embedding", chat_session.id, exc)
        _save_chat_error(db, chat_session.id, user.id, "embedding")
        raise ServiceUnavailableException(_chat_failure("embedding")[1]) from None
    try:
        chunks = retrieve_relevant_chunks(
            db, chat_session.document_id, question_embedding
        )
    except Exception as exc:
        _log_chat_failure("retrieval", chat_session.id, exc)
        _save_chat_error(db, chat_session.id, user.id, "retrieval")
        raise ServiceUnavailableException(_chat_failure("retrieval")[1]) from None
    try:
        answer = generate_document_answer(question, chunks)
    except Exception as exc:
        _log_chat_failure("generation", chat_session.id, exc)
        _save_chat_error(db, chat_session.id, user.id, "generation")
        raise ServiceUnavailableException(_chat_failure("generation")[1]) from None

    try:
        assistant_payload = ChatMessageCreate(
            session_id=chat_session.id,
            role="assistant",
            content=answer,
        )
        assistant_message = create_chat_message(db, assistant_payload, user.id)
        if assistant_message is None:
            raise RuntimeError("Owned chat session disappeared before saving answer")
    except Exception as exc:
        _log_chat_failure("persistence", chat_session.id, exc)
        _save_chat_error(db, chat_session.id, user.id, "persistence")
        raise AppException(
            _chat_failure("persistence")[1],
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from None

    return ChatTurnResponse(
        user_message=ChatMessageResponse.model_validate(user_message),
        assistant_message=ChatMessageResponse.model_validate(assistant_message),
        answer=answer,
        sources=_source_references(chunks),
    )


# Document-scoped chat


def create_document_session(
    db: Session, document_id: int, title: str | None, user: User
) -> ChatSession:
    get_owned_document(db, document_id, user.id, require_completed=True)
    session_data = ChatSessionCreate(
        user_id=user.id,
        document_id=document_id,
        title=title,
    )
    return create_chat_session(db, session_data)


def list_document_sessions(
    db: Session, document_id: int, user: User, skip: int, limit: int
) -> list[ChatSession]:
    get_owned_document(db, document_id, user.id)
    return get_chat_sessions_by_document(
        db, document_id, user.id, skip=skip, limit=limit
    )


def get_history(
    db: Session, session_id: int, user: User, skip: int, limit: int
) -> list[ChatMessage]:
    chat_session = get_owned_session(db, session_id, user.id)
    get_owned_document(db, chat_session.document_id, user.id)
    messages = get_messages_by_session(
        db, session_id, user.id, skip=skip, limit=limit
    )
    if messages is None:
        raise NotFoundException("Chat session not found")
    return messages


def ask_question(
    db: Session, session_id: int, content: str, user: User
) -> ChatTurnResponse:
    if not content.strip():
        raise UnprocessableException("Question must not be empty")
    chat_session = get_owned_session(db, session_id, user.id)
    get_owned_document(db, chat_session.document_id, user.id, require_completed=True)
    return _generate_chat_turn(db, chat_session, content, user)


def stream_answer(
    db: Session,
    session_id: int,
    content: str,
    user: User,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Validate and save the question, then return the SSE answer stream.

    `done` is emitted only after the answer is saved. If the client disconnects
    before persistence, cancellation closes the async Gemini iterator where
    supported and leaves only the user message. A disconnect during the
    synchronous database commit cannot be rolled back safely; history may then
    contain a complete assistant message even if the client saw no `done`.
    A client must treat EOF without `done` as incomplete and reload history
    before retrying. Sequential retries reuse the latest identical unanswered
    user turn.
    """
    request_started = time.perf_counter()
    question = content.strip()
    if not question:
        raise UnprocessableException("Question must not be empty")
    chat_session = get_owned_session(db, session_id, user.id)
    get_owned_document(db, chat_session.document_id, user.id, require_completed=True)

    # Sequential retries of the same last question reuse the persisted user turn.
    unanswered_message = get_latest_unanswered_user_message(db, session_id)
    if unanswered_message is not None and unanswered_message.content == question:
        user_message = unanswered_message
    else:
        try:
            user_message = create_chat_message(
                db,
                ChatMessageCreate(session_id=session_id, role="user", content=question),
                user.id,
            )
        except Exception as exc:
            logger.error("Streaming chat user-message save failed (error_type=%s)", type(exc).__name__)
            raise AppException(
                "Could not save your question. Please retry.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from None
        if user_message is None:
            raise NotFoundException("Chat session not found")

    async def stream_events() -> AsyncIterator[str]:
        answer_parts: list[str] = []
        embedding_seconds = 0.0
        retrieval_seconds = 0.0
        gemini_started = None
        gemini_total_seconds = None
        first_token_seconds = None
        stage = "embedding"
        try:
            embedding_started = time.perf_counter()
            try:
                question_embedding = await asyncio.to_thread(embed_question, question)
            finally:
                embedding_seconds = time.perf_counter() - embedding_started

            stage = "retrieval"
            retrieval_started = time.perf_counter()
            chunks = retrieve_relevant_chunks(db, chat_session.document_id, question_embedding)
            retrieval_seconds = time.perf_counter() - retrieval_started

            stage = "generation"
            gemini_started = time.perf_counter()
            async with asyncio.timeout(180):
                async for fragment in stream_document_answer(question, chunks):
                    if not fragment:
                        continue
                    if first_token_seconds is None:
                        first_token_seconds = time.perf_counter() - gemini_started
                    answer_parts.append(fragment)
                    yield _sse("chunk", {"text": fragment})
            gemini_total_seconds = time.perf_counter() - gemini_started

            answer = "".join(answer_parts).strip()
            if not answer:
                logger.warning("Chat answer was empty session_id=%s", session_id)
                yield _sse_chat_error(db, session_id, user.id, "empty")
                return
            answer = _remove_unverified_references(answer, chunks)

            # Avoid committing an answer if disconnection is already observable.
            if await is_disconnected():
                return
            stage = "persistence"
            try:
                assistant_message = create_chat_message(
                    db,
                    ChatMessageCreate(session_id=session_id, role="assistant", content=answer),
                    user.id,
                )
                if assistant_message is None:
                    raise RuntimeError("Owned chat session disappeared")
            except Exception as exc:
                _log_chat_failure("persistence", session_id, exc)
                yield _sse_chat_error(db, session_id, user.id, "persistence")
                return

            yield _sse("done", {
                "user_message": ChatMessageResponse.model_validate(user_message).model_dump(mode="json"),
                "assistant_message": ChatMessageResponse.model_validate(assistant_message).model_dump(mode="json"),
                "answer": answer,
                "sources": [source.model_dump() for source in _source_references(chunks)],
            })
        except asyncio.CancelledError:
            logger.info("Streaming chat cancelled (session_id=%s)", session_id)
            raise
        except TimeoutError as exc:
            _log_chat_failure("generation_timeout", session_id, exc)
            yield _sse_chat_error(db, session_id, user.id, "timeout")
        except Exception as exc:
            _log_chat_failure(stage, session_id, exc)
            yield _sse_chat_error(db, session_id, user.id, stage)
        finally:
            total_seconds = time.perf_counter() - request_started
            generation_seconds = gemini_total_seconds
            if generation_seconds is None:
                generation_seconds = time.perf_counter() - gemini_started if gemini_started is not None else 0.0
            logger.info(
                "Streaming chat timings session_id=%s embedding_seconds=%.3f retrieval_seconds=%.3f "
                "gemini_time_to_first_token_seconds=%s gemini_total_seconds=%.3f total_request_seconds=%.3f",
                session_id,
                embedding_seconds,
                retrieval_seconds,
                f"{first_token_seconds:.3f}" if first_token_seconds is not None else "unavailable",
                generation_seconds,
                total_seconds,
            )

    return stream_events()


# Generic chat sessions


def start_session(db: Session, payload: ChatSessionCreate, user: User) -> ChatSession:
    document = get_document_by_id(db, payload.document_id)
    if document is None or document.user_id != user.id:
        raise NotFoundException("Document not found")

    owned_payload = payload.model_copy(update={"user_id": user.id})
    return create_chat_session(db, owned_payload)


def list_sessions(db: Session, user: User, skip: int, limit: int) -> list[ChatSession]:
    return get_chat_sessions_by_user(db, user.id, skip=skip, limit=limit)


def remove_session(db: Session, session_id: int, user: User) -> None:
    if not delete_chat_session(db, session_id, user.id):
        raise NotFoundException("Chat session not found")


def add_message(
    db: Session, session_id: int, payload: ChatMessageCreate, user: User
) -> ChatTurnResponse:
    if payload.session_id != session_id:
        raise BadRequestException("Session ID in URL and body must match")
    if payload.role != "user":
        raise UnprocessableException("Message role must be 'user'")
    if not payload.content.strip():
        raise UnprocessableException("Question must not be empty")

    chat_session = get_owned_session(db, session_id, user.id)
    get_owned_document(db, chat_session.document_id, user.id, require_completed=True)
    return _generate_chat_turn(db, chat_session, payload.content, user)


def list_messages(
    db: Session, session_id: int, user: User, skip: int = 0, limit: int = 100
) -> list[ChatMessage]:
    messages = get_messages_by_session(
        db, session_id, user.id, skip=skip, limit=limit
    )
    if messages is None:
        raise NotFoundException("Chat session not found")
    return messages
