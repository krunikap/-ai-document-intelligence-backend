from myproject.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)
from myproject.schemas.document import DocumentCreate, DocumentResponse
from myproject.schemas.user import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

__all__ = [
    "UserCreate",
    "UserResponse",
    "UserLogin",
    "DocumentCreate",
    "DocumentResponse",
    "ChatSessionCreate",
    "ChatSessionResponse",
    "ChatMessageCreate",
    "ChatMessageResponse",
    # Backward-compatible exports for the existing authentication code.
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
]
