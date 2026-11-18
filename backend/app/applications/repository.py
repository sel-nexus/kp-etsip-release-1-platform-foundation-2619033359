"""Persist applications and coordinate portfolio references through MongoDB."""
from uuid import uuid4
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp


class ApplicationRepository:
    """Operate on applications using the shared asynchronous database."""
    def __init__(self, db: AsyncDatabase) -> None:
        """Bind the application database."""
        self.db = db

    async def allowed(self, role: str, action: str) -> bool:
        """Fail closed when the role lacks the editable permission."""
        role_doc = await self.db.roles.find_one({"name": role})
        return bool(role_doc and action in role_doc.get("permissions", []))

    async def reserve(self, portfolio_id: ObjectId) -> str | None:
        """Atomically reserve a live portfolio against concurrent deletion.

        Reservations are not leases: on uncertain failures they remain until an
        operator verifies that no writer is active and repairs the document.
        """
        token = uuid4().hex
        result = await self.db.portfolios.update_one(
            {"_id": portfolio_id, "deleting": {"$ne": True}},
            {"$addToSet": {"applicationReservations": token}},
        )
        return token if result.matched_count else None

    async def release(self, portfolio_id: ObjectId, token: str) -> None:
        """Release a reservation after the dependent write is acknowledged."""
        await self.db.portfolios.update_one({"_id": portfolio_id}, {"$pull": {"applicationReservations": token}})

    async def get(self, identifier: ObjectId) -> dict | None:
        """Find an application by identifier."""
        return await self.db.applications.find_one({"_id": identifier})

    async def list(self, query: dict, limit: int, offset: int) -> tuple[list[dict], int]:
        """Read a stable-order page and its total."""
        total = await self.db.applications.count_documents(query)
        items = await self.db.applications.find(query).sort([("name", 1), ("_id", 1)]).skip(offset).limit(limit).to_list(None)
        return items, total

    async def create(self, fields: dict) -> dict:
        """Insert a new application and return the persisted document."""
        now = timestamp()
        result = await self.db.applications.insert_one({**fields, "createdAt": now, "updatedAt": now})
        return await self.get(result.inserted_id)

    async def update(self, identifier: ObjectId, previous_portfolio: str, fields: dict) -> dict | None:
        """Update only if its authorization-relevant portfolio is unchanged."""
        return await self.db.applications.find_one_and_update(
            {"_id": identifier, "portfolioId": previous_portfolio},
            {"$set": {**fields, "updatedAt": timestamp()}}, return_document=ReturnDocument.AFTER,
        )

    async def delete(self, identifier: ObjectId) -> bool:
        """Delete an application by identifier."""
        return (await self.db.applications.delete_one({"_id": identifier})).deleted_count == 1

    async def audit(self, user: dict, action: str, identifier: ObjectId | None) -> None:
        """Record the successful inventory operation."""
        now = timestamp()
        await self.db.audit_logs.insert_one({"timestamp": now, "createdAt": now, "updatedAt": now, "userId": str(user["_id"]), "userName": user["name"], "action": action, "entityType": "application", "entityId": str(identifier) if identifier else None, "details": f"Application {action}"})
