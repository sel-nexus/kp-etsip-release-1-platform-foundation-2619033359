"""Implement local sign-in and profile operations."""
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from app.auth.repository import IdentityRepository, timestamp
from app.core.security import create_access_token, hash_password, verify_password


async def login(repo: IdentityRepository, email: str, password: str) -> dict:
    """Authenticate an active account and audit every attempt."""
    email = email.strip().lower()
    user = await repo.by_email(email)
    valid = bool(user and await run_in_threadpool(verify_password, password, user["passwordHash"]))
    if not valid or user["status"] != "Active":
        await repo.audit(user, email[:254], "Failed login")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = await repo.update(user, {"lastLogin": timestamp()})
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await repo.audit(user, email, "Successful login")
    return {"token": create_access_token(user), "user": user}


async def change_password(repo: IdentityRepository, user: dict, current: str, new: str) -> dict:
    """Replace the password, clear the initial-password flag and revoke older tokens."""
    if not await run_in_threadpool(verify_password, current, user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if current == new:
        raise HTTPException(status_code=400, detail="Choose a different password")
    hashed = await run_in_threadpool(hash_password, new)
    updated = await repo.update(user, {"passwordHash": hashed, "mustChangePassword": False}, increment_version=True)
    if updated is None:
        raise HTTPException(status_code=409, detail="Account changed; sign in again")
    await repo.profile_audit(updated, "Password changed")
    return {"token": create_access_token(updated), "user": updated}


async def change_preferences(repo: IdentityRepository, user: dict, landing: str) -> dict:
    """Persist the selected default destination."""
    updated = await repo.update(user, {"defaultLandingPage": landing})
    if updated is None:
        raise HTTPException(status_code=409, detail="Account changed; sign in again")
    await repo.profile_audit(updated, "Landing preference changed")
    return updated
