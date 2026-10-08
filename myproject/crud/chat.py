from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from myproject.models.chat_message import ChatMessage
from myproject.models.chat_session import ChatSession
from myproject.schemas.chat import ChatMessageCreate, ChatSessionCreate


def create_chat_session(
    db: Session,
    session_data: ChatSessionCreate,
) -> ChatSession:
    """Create and return a chat session from validated request data."""
    now = datetime.now(timezone.utc)
    chat_session = ChatSession(
        user_id=session_data.user_id,
        document_id=session_data.document_id,
        title=session_data.title,
        created_at=now,
        updated_at=now,
    )
    db.add(chat_session)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(chat_session)
    return chat_session


def get_chat_session_by_id(
    db: Session,
    session_id: int,
    user_id: int,
) -> ChatSession | None:
    """Return a session only when it belongs to ``user_id``."""
    statement = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    return db.scalar(statement)


def get_chat_sessions_by_user(
    db: Session,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[ChatSession]:
    """Return a stable page of chat sessions owned by ``user_id``."""
    if user_id <= 0:
        raise ValueError("user_id must be greater than zero")
    if skip < 0:
        raise ValueError("skip must be zero or greater")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    statement = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def delete_chat_session(db: Session, session_id: int, user_id: int) -> bool:
    """Delete an owned chat session; return False if absent or not owned."""
    chat_session = get_chat_session_by_id(db, session_id, user_id)
    if chat_session is None:
        return False

    db.delete(chat_session)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def create_chat_message(
    db: Session,
    message_data: ChatMessageCreate,
    user_id: int,
) -> ChatMessage | None:
    """Create a message only if its session belongs to ``user_id``.

    Returns None if the session does not exist or is not owned by that user.
    Adding a message also updates the session's activity timestamp.
    """
    chat_session = get_chat_session_by_id(db, message_data.session_id, user_id)
    if chat_session is None:
        return None

    message = ChatMessage(
        session_id=chat_session.id,
        role=message_data.role,
        content=message_data.content,
        created_at=datetime.now(timezone.utc),
    )
    chat_session.updated_at = message.created_at
    db.add(message)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(message)
    return message


def get_messages_by_session(
    db: Session,
    session_id: int,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[ChatMessage] | None:
    """Return a page of messages in an owned session, oldest first.

    Returns None when the session does not exist or belongs to another user;
    an empty list means the owned session has no messages in this page.
    """
    if skip < 0:
        raise ValueError("skip must be zero or greater")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if get_chat_session_by_id(db, session_id, user_id) is None:
        return None

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(statement).all())
