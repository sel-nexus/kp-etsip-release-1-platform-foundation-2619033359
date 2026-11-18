"""Idempotently seed the six roles and local demonstration accounts."""
from starlette.concurrency import run_in_threadpool
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp
from app.core.config import Settings
from app.core.security import hash_password

ROLES = {
    "Administrator": ["view", "create", "edit", "delete", "export", "administer"],
    "Executive": ["view", "export"],
    "Portfolio Leader": ["view", "create", "edit", "export"],
    "Engineer": ["view", "create", "edit", "export"],
    "Auditor": ["view", "export"],
    "Read Only": ["view"],
}


async def seed_database(db: AsyncDatabase, settings: Settings) -> None:
    """Insert missing roles and demo users without replacing existing changes."""
    now = timestamp()
    admin_hash = await run_in_threadpool(hash_password, settings.ADMIN_INITIAL_PASSWORD)
    demo_hash = await run_in_threadpool(hash_password, settings.DEMO_INITIAL_PASSWORD)
    for role, permissions in ROLES.items():
        await db.roles.update_one({"name": role}, {"$setOnInsert": {"name": role, "description": f"{role} access", "permissions": permissions, "createdAt": now, "updatedAt": now}}, upsert=True)
        slug = {"Administrator": "admin", "Portfolio Leader": "leader", "Read Only": "readonly"}.get(role, role.lower())
        email = f"{slug}@ketsip.local"
        user = {"name": f"Demo {role}", "email": email, "passwordHash": admin_hash if role == "Administrator" else demo_hash, "role": role, "portfolioAccess": [], "status": "Active", "lastLogin": None, "authSource": "local", "managerName": None, "vendorIndicator": False, "mustChangePassword": role == "Administrator", "defaultLandingPage": None, "tokenVersion": 0, "createdAt": now, "updatedAt": now}
        await db.users.update_one({"email": email}, {"$setOnInsert": user}, upsert=True)
