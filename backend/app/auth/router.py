"""Expose local authentication and self-service profile routes."""
from typing import Annotated
from fastapi import APIRouter, Depends
from pymongo.asynchronous.database import AsyncDatabase
from app.auth import service
from app.auth.repository import IdentityRepository
from app.auth.schemas import LoginRequest, LoginResponse, PasswordRequest, PreferencesRequest, PublicUser
from app.core.database import get_database
from app.core.security import get_current_user, require_ready_user

router = APIRouter(tags=["Identity"])
DB = Annotated[AsyncDatabase, Depends(get_database)]
Current = Annotated[dict, Depends(get_current_user)]
Ready = Annotated[dict, Depends(require_ready_user)]


@router.post("/auth/login", response_model=LoginResponse, summary="Sign in with local credentials")
async def login(body: LoginRequest, db: DB) -> dict:
    """Authenticate and return a public profile and token."""
    return await service.login(IdentityRepository(db), body.email, body.password)


@router.post("/auth/logout", summary="End the client session")
async def logout(user: Current) -> dict[str, str]:
    """Acknowledge logout; the client must discard its token."""
    return {"message": "Signed out"}


@router.get("/auth/me", response_model=PublicUser, summary="Get the current account")
async def me(user: Current) -> dict:
    """Return the current public profile."""
    return user


@router.put("/profile/password", response_model=LoginResponse, summary="Change your password")
async def password(body: PasswordRequest, user: Current, db: DB) -> dict:
    """Change credentials and return a replacement token."""
    return await service.change_password(IdentityRepository(db), user, body.currentPassword, body.newPassword)


@router.put("/profile/preferences", response_model=PublicUser, summary="Save landing preference")
async def preferences(body: PreferencesRequest, user: Ready, db: DB) -> dict:
    """Persist the signed-in user's landing preference."""
    return await service.change_preferences(IdentityRepository(db), user, body.defaultLandingPage)
