from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import UnauthorizedException
from app.core.security import decode_access_token
from app.db import get_db
from app.models import User
from app.repositories import get_user_by_id, is_token_revoked

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    unauthorized = UnauthorizedException("Invalid or expired access token")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
    except (ValueError, KeyError, TypeError):
        raise unauthorized

    if is_token_revoked(db, claims["jti"]):
        raise unauthorized
    user = get_user_by_id(db, int(claims["sub"]))
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
