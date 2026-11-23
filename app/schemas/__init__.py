from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatQuestionRequest,
    ChatSessionCreate,
    ChatSessionRequest,
    ChatSessionResponse,
    ChatSourceReference,
    ChatTurnResponse,
)
from app.schemas.common import ApiResponse
from app.schemas.document import DocumentCreate, DocumentResponse, DocumentUpdate
from app.schemas.user import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

__all__ = [
    "ApiResponse",
    "UserCreate",
    "UserResponse",
    "UserLogin",
    "DocumentCreate",
    "DocumentUpdate",
    "DocumentResponse",
    "ChatSessionCreate",
    "ChatSessionRequest",
    "ChatSessionResponse",
    "ChatMessageCreate",
    "ChatMessageResponse",
    "ChatQuestionRequest",
    "ChatSourceReference",
    "ChatTurnResponse",
    # Backward-compatible exports for the existing authentication code.
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
]
