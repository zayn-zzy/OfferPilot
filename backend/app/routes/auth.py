"""Registration, login, logout, and current-user endpoints."""

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)
from app.models import User
from app.schemas import UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
cookie_scheme = APIKeyCookie(name="offerpilot_session", auto_error=False)


def settings_dependency(request: Request) -> Settings:
    """Read app settings from the application container."""

    return request.app.state.settings


def session_dependency(request: Request) -> Generator[Session, None, None]:
    """Open one SQLAlchemy session for the current request."""

    with request.app.state.session_factory() as session:
        yield session


def enforce_same_origin(request: Request, settings: Settings) -> None:
    """Reject browser mutations from origins outside the configured frontend."""

    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in {item.rstrip("/") for item in settings.allowed_origins}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")


def set_session_cookie(response: Response, user_id: UUID, settings: Settings) -> None:
    """Issue an HttpOnly cookie after successful registration or login."""

    secret = settings.secret_key.get_secret_value()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user_id, secret, settings.session_ttl_minutes),
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


def current_user_dependency(
    token: Annotated[str | None, Depends(cookie_scheme)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> User:
    """Resolve the cookie to an active user, returning 401 for invalid sessions."""

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = read_session_token(token, settings.secret_key.get_secret_value())
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from None

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> User:
    """Create an account and sign in the new user."""

    enforce_same_origin(request, settings)
    user = User(email=str(payload.email), password_hash=hash_password(payload.password.get_secret_value()))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already exists for this email") from None
    session.refresh(user)
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/login", response_model=UserRead)
def login(
    payload: UserLogin,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> User:
    """Verify credentials and issue a short-lived session cookie."""

    enforce_same_origin(request, settings)
    user = session.scalar(select(User).where(User.email == str(payload.email)))
    if user is None or not verify_password(payload.password.get_secret_value(), user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> Response:
    """Clear the session cookie."""

    enforce_same_origin(request, settings)
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def read_current_user(
    user: Annotated[User, Depends(current_user_dependency)],
) -> User:
    """Return the currently authenticated account."""

    return user
