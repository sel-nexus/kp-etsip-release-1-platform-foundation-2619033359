"""Persist identity records and audit events in MongoDB."""
from datetime import datetime, timezone
from pymongo.asynchronous.database import AsyncDatabase


def timestamp() -> str:
    """Return an ISO timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


class IdentityRepository:
    """Read and mutate accounts and audit records."""
    def __init__(self, db: AsyncDatabase) -> None:
        """Bind the shared database."""
        self.db = db

    async def by_email(self, email: str) -> dict | None:
        """Look up a normalized local account."""
        return await self.db.users.find_one({"email": email})

    async def audit(self, user: dict | None, label: str, details: str) -> None:
        """Persist a login event without credentials."""
        now = timestamp()
        await self.db.audit_logs.insert_one({"timestamp": now, "createdAt": now, "updatedAt": now, "userId": str(user["_id"]) if user else None, "userName": user["name"] if user else label, "action": "login", "entityType": "user", "entityId": str(user["_id"]) if user else None, "details": details})

    async def update(self, user: dict, fields: dict, *, increment_version: bool = False) -> dict:
        """Persist account changes and return the updated account."""
        fields["updatedAt"] = timestamp()
        update = {"$set": fields}
        if increment_version:
            update["$inc"] = {"tokenVersion": 1}
        from pymongo import ReturnDocument
        return await self.db.users.find_one_and_update({"_id": user["_id"], "status": "Active", "tokenVersion": user.get("tokenVersion", 0)}, update, return_document=ReturnDocument.AFTER)

    async def profile_audit(self, user: dict, details: str) -> None:
        """Record a successful profile update without sensitive values."""
        now = timestamp()
        await self.db.audit_logs.insert_one({"timestamp": now, "createdAt": now, "updatedAt": now, "userId": str(user["_id"]), "userName": user["name"], "action": "edit", "entityType": "user", "entityId": str(user["_id"]), "details": details})
