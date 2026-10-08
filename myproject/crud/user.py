from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myproject.models.user import User
from myproject.schemas.user import UserCreate


def create_user(
    db: Session,
    user_data: UserCreate,
    *,
    password_hash: str,
) -> User:
    """Persist a user using an already-hashed password value.

    Password hashing is intentionally not implemented in this CRUD module.
    The caller must provide a hash; never pass ``user_data.password`` here.
    A future service layer should hash the password before calling this function.
    """
    if not password_hash or password_hash == user_data.password:
        raise ValueError("password_hash must be provided and must not be the plain password")

    now = datetime.now(timezone.utc)
    user = User(
        name=user_data.name,
        email=str(user_data.email).lower(),
        password_hash=password_hash,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Return one user by primary key, or None when it does not exist."""
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    """Return one user by email, or None when it does not exist."""
    statement = select(User).where(User.email == email.strip().lower())
    return db.scalar(statement)


def get_users(db: Session, *, skip: int = 0, limit: int = 100) -> list[User]:
    """Return a page of users, ordered by id for stable pagination."""
    if skip < 0:
        raise ValueError("skip must be zero or greater")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    statement = select(User).order_by(User.id).offset(skip).limit(limit)
    return list(db.scalars(statement).all())


def update_user(
    db: Session,
    user_id: int,
    updates: dict[str, Any],
) -> User | None:
    """Update a user's name and/or email; return None if the user is absent.

    ``updates`` should contain validated values. Password updates are deliberately
    excluded until a password-hashing service exists.
    """
    user = db.get(User, user_id)
    if user is None:
        return None

    allowed_fields = {"name", "email"}
    unknown_fields = updates.keys() - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unsupported user update field(s): {names}")
    if not updates:
        raise ValueError("At least one field must be provided for update")

    for field, value in updates.items():
        if field == "email":
            value = value.strip().lower()
        elif field == "name" and value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Name cannot be blank")
        setattr(user, field, value)

    user.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    """Delete a user and return whether a matching user was found."""
    user = db.get(User, user_id)
    if user is None:
        return False

    db.delete(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
