"""Persist portfolios and derive summaries from MongoDB applications."""
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp


class PortfolioRepository:
    """Use the shared database for inventory and audit operations."""
    def __init__(self, db: AsyncDatabase) -> None:
        """Bind the lifespan-managed database."""
        self.db = db

    async def allowed(self, role: str, permission: str) -> bool:
        """Check the editable role permission set, failing closed."""
        record = await self.db.roles.find_one({"name": role})
        return bool(record and permission in record.get("permissions", []))

    async def list_portfolios(self, query: dict, limit: int, offset: int) -> tuple[list[dict], int]:
        """Return matching portfolio documents and their derived metrics."""
        total = await self.db.portfolios.count_documents(query)
        docs = await self.db.portfolios.find(query).sort([("name", 1), ("_id", 1)]).skip(offset).limit(limit).to_list(None)
        return [await self.summary(doc) for doc in docs], total

    async def summary(self, doc: dict) -> dict:
        """Compute count and average from linked application documents."""
        cursor = await self.db.applications.aggregate([
            {"$match": {"portfolioId": str(doc["_id"])}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "average": {"$avg": "$qualityScore"}}},
        ])
        result = await cursor.to_list(None)
        average = result[0]["average"] if result else None
        public = {key: value for key, value in doc.items() if key not in ("applicationReservations", "deleting")}
        return {**public, "applicationCount": result[0]["count"] if result else 0, "qualityScore": int(average + 0.5) if average is not None else None}

    async def get(self, identifier: ObjectId) -> dict | None:
        """Find a portfolio by its identifier."""
        return await self.db.portfolios.find_one({"_id": identifier})

    async def create(self, fields: dict) -> dict:
        """Insert a portfolio and return the stored document."""
        now = timestamp()
        doc = {**fields, "createdAt": now, "updatedAt": now}
        result = await self.db.portfolios.insert_one(doc)
        return await self.get(result.inserted_id)

    async def update(self, identifier: ObjectId, fields: dict) -> dict | None:
        """Replace editable fields while preserving creation metadata."""
        return await self.db.portfolios.find_one_and_update({"_id": identifier}, {"$set": {**fields, "updatedAt": timestamp()}}, return_document=ReturnDocument.AFTER)

    async def begin_delete(self, identifier: ObjectId) -> bool:
        """Block new reservations only when no application writer holds one."""
        result = await self.db.portfolios.update_one(
            {"_id": identifier, "deleting": {"$ne": True}, "applicationReservations.0": {"$exists": False}},
            {"$set": {"deleting": True}},
        )
        return result.modified_count == 1

    async def cancel_delete(self, identifier: ObjectId) -> None:
        """Unblock application writers after a definite reference check."""
        await self.db.portfolios.update_one({"_id": identifier, "deleting": True}, {"$unset": {"deleting": ""}})

    async def delete(self, identifier: ObjectId) -> bool:
        """Delete a portfolio with its deletion marker held."""
        return (await self.db.portfolios.delete_one({"_id": identifier, "deleting": True})).deleted_count == 1

    async def applications(self, identifier: ObjectId, limit: int, offset: int) -> tuple[list[dict], int]:
        """Return a bounded list of linked application records."""
        query = {"portfolioId": str(identifier)}
        total = await self.db.applications.count_documents(query)
        docs = await self.db.applications.find(query).sort([("name", 1), ("_id", 1)]).skip(offset).limit(limit).to_list(None)
        for doc in docs:
            doc["id"] = str(doc.pop("_id"))
        return docs, total

    async def has_applications(self, identifier: ObjectId) -> bool:
        """Determine whether an application references the portfolio."""
        return bool(await self.db.applications.find_one({"portfolioId": str(identifier)}, {"_id": 1}))

    async def audit(self, user: dict, action: str, identifier: ObjectId) -> None:
        """Record a successful mutation without sensitive fields."""
        now = timestamp()
        await self.db.audit_logs.insert_one({"timestamp": now, "createdAt": now, "updatedAt": now, "userId": str(user["_id"]), "userName": user["name"], "action": action, "entityType": "portfolio", "entityId": str(identifier), "details": f"Portfolio {action}"})
