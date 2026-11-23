from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import CurrentUser, DbSession, bearer_scheme
from app.schemas import ApiResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> ApiResponse[UserResponse]:
    user = auth_service.register(db, payload)
    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="User registered",
        data=UserResponse.model_validate(user),
    )


@router.post("/login")
def login(payload: LoginRequest, db: DbSession) -> ApiResponse[TokenResponse]:
    token = auth_service.login(db, payload)
    return ApiResponse(message="Login successful", data=token)


@router.post("/logout")
def logout(
    user: CurrentUser,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> ApiResponse[None]:
    auth_service.logout(db, credentials.credentials)
    return ApiResponse(message="Logout successful", data=None)
