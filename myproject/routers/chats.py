from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from myproject.crud.chat import (
    create_chat_message,
    create_chat_session,
    delete_chat_session,
    get_chat_session_by_id,
    get_chat_sessions_by_user,
    get_messages_by_session,
)
from myproject.crud.document import get_document_by_id
from myproject.dependencies import get_current_user, get_db
from myproject.models.user import User
from myproject.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def start_chat_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSessionResponse:
    document = get_document_by_id(db, payload.document_id)
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    owned_payload = payload.model_copy(update={"user_id": user.id})
    session = create_chat_session(db, owned_payload)
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatSessionResponse]:
    sessions = get_chat_sessions_by_user(db, user.id, skip=skip, limit=limit)
    return [ChatSessionResponse.model_validate(session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def read_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSessionResponse:
    session = get_chat_session_by_id(db, session_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return ChatSessionResponse.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if not delete_chat_session(db, session_id, user.id):
        raise HTTPException(status_code=404, detail="Chat session not found")


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_chat_message(
    session_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatMessageResponse:
    if payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="Session ID in URL and body must match")
    message = create_chat_message(db, payload, user.id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return ChatMessageResponse.model_validate(message)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
)
def list_chat_messages(
    session_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatMessageResponse]:
    messages = get_messages_by_session(
        db, session_id, user.id, skip=skip, limit=limit
    )
    if messages is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return [ChatMessageResponse.model_validate(message) for message in messages]
