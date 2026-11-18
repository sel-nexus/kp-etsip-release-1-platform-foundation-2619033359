"""Implement password hashing and bearer token verification."""
from datetime import datetime, timedelta, timezone
from typing import Annotated
from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pymongo.asynchronous.database import AsyncDatabase
from app.core.config import get_settings
from app.core.database import get_database

passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return passwords.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password without accepting oversized bcrypt inputs."""
    if len(password.encode("utf-8")) > 72:
        return False
    return passwords.verify(password, hashed)


def create_access_token(user: dict) -> str:
    """Issue an eight-hour signed token for the current account revision."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user["_id"]), "userId": str(user["_id"]), "role": user["role"], "ver": user.get("tokenVersion", 0), "iat": now, "exp": now + timedelta(hours=8)}, get_settings().JWT_SECRET, algorithm="HS256")


async def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: Annotated[AsyncDatabase, Depends(get_database)]) -> dict:
    """Resolve a valid token to an active, current account."""
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise error
    try:
        claims = jwt.decode(credentials.credentials, get_settings().JWT_SECRET, algorithms=["HS256"], options={"require_exp": True, "require_sub": True})
        subject = claims.get("sub")
        if not isinstance(subject, str) or not ObjectId.is_valid(subject) or claims.get("userId") != subject:
            raise error
    except JWTError as exc:
        raise error from exc
    user = await db.users.find_one({"_id": ObjectId(subject)})
    if not user or user.get("status") != "Active" or user.get("role") != claims.get("role") or user.get("tokenVersion", 0) != claims.get("ver"):
        raise error
    return user


async def require_ready_user(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Deny normal access until a mandatory password change is complete."""
    if user.get("mustChangePassword", False):
        raise HTTPException(status_code=403, detail="Change your initial password first")
    return user
