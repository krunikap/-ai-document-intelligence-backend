from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import ConflictException, UnauthorizedException
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.repositories import create_user, get_user_by_email, revoke_token
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse


def register(db: Session, payload: RegisterRequest) -> User:
    if get_user_by_email(db, payload.email) is not None:
        raise ConflictException("Email is already registered")
    try:
        return create_user(db, payload, password_hash=hash_password(payload.password))
    except IntegrityError:
        raise ConflictException("Email is already registered") from None


def login(db: Session, payload: LoginRequest) -> TokenResponse:
    user = get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedException("Incorrect email or password")
    access_token, _, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


def logout(db: Session, token: str) -> None:
    claims = decode_access_token(token)
    revoke_token(
        db,
        claims["jti"],
        datetime.fromtimestamp(claims["exp"], timezone.utc).isoformat(),
    )
