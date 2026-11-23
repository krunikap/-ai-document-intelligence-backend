from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    """Validated input for creating a user account."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return value.strip().lower()


class UserResponse(BaseModel):
    """Safe user data returned by the API; password fields are excluded."""

    model_config = {"from_attributes": True}

    id: int
    name: str | None
    email: EmailStr
    created_at: datetime
    updated_at: datetime


# Keep existing auth routes compatible while using the new account input schema.
RegisterRequest = UserCreate


class UserLogin(BaseModel):
    """Credentials supplied when a user signs in."""

    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> EmailStr:
        return value.strip().lower()


LoginRequest = UserLogin


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
