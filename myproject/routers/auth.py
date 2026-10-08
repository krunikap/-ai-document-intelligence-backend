from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from myproject.dependencies import get_current_user, get_db
from myproject.models.user import RevokedToken, User
from myproject.schemas.user import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from myproject.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from fastapi.security import HTTPAuthorizationCredentials
from myproject.dependencies import bearer_scheme

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    now = datetime.now(timezone.utc).isoformat()
    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token, _, expires_in = create_access_token(user.id)
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Response:
    claims = decode_access_token(credentials.credentials)
    db.add(
        RevokedToken(
            jti=claims["jti"],
            expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc).isoformat(),
        )
    )
    db.commit()
    return response
