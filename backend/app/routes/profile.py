"""Current user's education and job-search preference endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CandidateProfile, User
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import CandidateProfileRead, CandidateProfileWrite

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=CandidateProfileRead)
def read_profile(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> CandidateProfileRead:
    """Return the user's profile, or an empty form when it has not been saved."""

    profile = session.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if profile is not None:
        return CandidateProfileRead.model_validate(profile)
    return CandidateProfileRead(
        graduation_year=None,
        education=None,
        major=None,
        target_roles=[],
        target_cities=[],
        industries=[],
        skills=[],
    )


@router.put("", response_model=CandidateProfileRead)
def save_profile(
    payload: CandidateProfileWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> CandidateProfile:
    """Create or replace the current user's profile."""

    enforce_same_origin(request, settings)
    profile = session.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    fields = payload.model_dump()
    if profile is None:
        profile = CandidateProfile(user_id=user.id, **fields)
        session.add(profile)
    else:
        for field, value in fields.items():
            setattr(profile, field, value)
    session.commit()
    session.refresh(profile)
    return profile
