"""Read and write audit events in the shared MongoDB database."""
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp


class AuditRepository:
    """Provide bounded audit reads and export event writes."""
    def __init__(self, db: AsyncDatabase) -> None:
        """Bind the shared database."""
        self.db = db

    async def page(self, query: dict, limit: int, offset: int) -> tuple[list[dict], int]:
        """Return a stable page and matching count."""
        total = await self.db.audit_logs.count_documents(query)
        cursor = self.db.audit_logs.find(query).sort([('timestamp', -1), ('_id', -1)]).skip(offset).limit(limit)
        return await cursor.to_list(None), total

    def cursor(self, query: dict):
        """Iterate all matching events without materializing the collection."""
        return self.db.audit_logs.find(query).sort([('timestamp', -1), ('_id', -1)])

    async def export_event(self, user: dict, entity: str) -> None:
        """Persist a non-secret description before starting an export."""
        now = timestamp()
        await self.db.audit_logs.insert_one({'timestamp': now, 'createdAt': now, 'updatedAt': now, 'userId': str(user['_id']), 'userName': user['name'], 'action': 'export', 'entityType': entity, 'entityId': None, 'details': f'{entity} export'})
