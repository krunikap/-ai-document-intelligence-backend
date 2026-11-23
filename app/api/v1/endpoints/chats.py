from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.schemas import (
    ApiResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatQuestionRequest,
    ChatSessionCreate,
    ChatSessionRequest,
    ChatSessionResponse,
    ChatTurnResponse,
)
from app.services import chat_service

router = APIRouter(prefix="/chats", tags=["Chats"])
document_chat_router = APIRouter(tags=["Document Chat"])

Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=1000)]


@document_chat_router.post(
    "/documents/{document_id}/chat/sessions",
    status_code=status.HTTP_201_CREATED,
)
def create_document_chat_session(
    document_id: int,
    payload: ChatSessionRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[ChatSessionResponse]:
    session = chat_service.create_document_session(db, document_id, payload.title, user)
    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Chat session created",
        data=ChatSessionResponse.model_validate(session),
    )


@document_chat_router.get("/documents/{document_id}/chat/sessions")
def list_document_chat_sessions(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
    skip: Skip = 0,
    limit: Limit = 100,
) -> ApiResponse[list[ChatSessionResponse]]:
    sessions = chat_service.list_document_sessions(db, document_id, user, skip, limit)
    return ApiResponse(
        message="Chat sessions fetched",
        data=[ChatSessionResponse.model_validate(session) for session in sessions],
    )


@document_chat_router.get("/chat/sessions/{session_id}/messages")
def get_chat_history(
    session_id: int,
    db: DbSession,
    user: CurrentUser,
    skip: Skip = 0,
    limit: Limit = 100,
) -> ApiResponse[list[ChatMessageResponse]]:
    messages = chat_service.get_history(db, session_id, user, skip, limit)
    return ApiResponse(
        message="Chat history fetched",
        data=[ChatMessageResponse.model_validate(message) for message in messages],
    )


@document_chat_router.post(
    "/chat/sessions/{session_id}/messages",
    status_code=status.HTTP_201_CREATED,
)
def ask_chat_question(
    session_id: int,
    payload: ChatQuestionRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[ChatTurnResponse]:
    turn = chat_service.ask_question(db, session_id, payload.content, user)
    return ApiResponse(status=status.HTTP_201_CREATED, message="Answer generated", data=turn)


@document_chat_router.post("/chat/sessions/{session_id}/messages/stream")
async def ask_chat_question_stream(
    session_id: int,
    payload: ChatQuestionRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> StreamingResponse:
    """Stream an answer as SSE events: `chunk`, then `done` or `error`."""
    events = chat_service.stream_answer(
        db, session_id, payload.content, user, request.is_disconnected
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def start_chat_session(
    payload: ChatSessionCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[ChatSessionResponse]:
    session = chat_service.start_session(db, payload, user)
    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Chat session created",
        data=ChatSessionResponse.model_validate(session),
    )


@router.get("/sessions")
def list_chat_sessions(
    db: DbSession,
    user: CurrentUser,
    skip: Skip = 0,
    limit: Limit = 100,
) -> ApiResponse[list[ChatSessionResponse]]:
    sessions = chat_service.list_sessions(db, user, skip, limit)
    return ApiResponse(
        message="Chat sessions fetched",
        data=[ChatSessionResponse.model_validate(session) for session in sessions],
    )


@router.get("/sessions/{session_id}")
def read_chat_session(
    session_id: int,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[ChatSessionResponse]:
    session = chat_service.get_owned_session(db, session_id, user.id)
    return ApiResponse(message="Chat session fetched", data=ChatSessionResponse.model_validate(session))


@router.delete("/sessions/{session_id}")
def remove_chat_session(
    session_id: int,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[None]:
    chat_service.remove_session(db, session_id, user)
    return ApiResponse(message="Chat session deleted", data=None)


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def add_chat_message(
    session_id: int,
    payload: ChatMessageCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse[ChatTurnResponse]:
    turn = chat_service.add_message(db, session_id, payload, user)
    return ApiResponse(status=status.HTTP_201_CREATED, message="Answer generated", data=turn)


@router.get("/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: int,
    db: DbSession,
    user: CurrentUser,
    skip: Skip = 0,
    limit: Limit = 100,
) -> ApiResponse[list[ChatMessageResponse]]:
    messages = chat_service.list_messages(db, session_id, user, skip, limit)
    return ApiResponse(
        message="Chat messages fetched",
        data=[ChatMessageResponse.model_validate(message) for message in messages],
    )
