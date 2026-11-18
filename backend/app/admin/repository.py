"""Persist administrative changes and coordinate safety-critical writes."""
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp


class AdminRepository:
    """Access administrative records in the shared MongoDB database."""
    def __init__(self, db: AsyncDatabase) -> None:
        """Bind the shared database."""
        self.db = db

    async def lock(self) -> None:
        """Serialize administrator mutations across application processes."""
        await self.db.admin_locks.insert_one({'_id': 'admin-mutations', 'createdAt': timestamp()})

    async def unlock(self) -> None:
        """Release a completed administrator mutation."""
        await self.db.admin_locks.delete_one({'_id': 'admin-mutations'})

    async def allowed(self) -> bool:
        """Check the administrator's current management permission."""
        role = await self.db.roles.find_one({'name': 'Administrator'})
        return bool(role and 'administer' in role.get('permissions', []))

    async def list_users(self, limit: int, offset: int) -> tuple[list[dict], int]:
        """Return a stable bounded account page."""
        return await self.db.users.find({}).sort([('name', 1), ('_id', 1)]).skip(offset).limit(limit).to_list(None), await self.db.users.count_documents({})

    async def user(self, identifier: ObjectId) -> dict | None:
        """Find an account by identifier."""
        return await self.db.users.find_one({'_id': identifier})

    async def active_admins(self) -> int:
        """Count active administrator accounts."""
        return await self.db.users.count_documents({'role': 'Administrator', 'status': 'Active'})

    async def create_user(self, fields: dict) -> dict:
        """Insert an account with timestamps and return it."""
        now = timestamp()
        doc = {**fields, 'createdAt': now, 'updatedAt': now}
        result = await self.db.users.insert_one(doc)
        return await self.user(result.inserted_id)

    async def update_user(self, old: dict, fields: dict, revoke: bool) -> dict | None:
        """Update only the observed account revision and optionally revoke tokens."""
        update = {'$set': {**fields, 'updatedAt': timestamp()}}
        if revoke:
            update['$inc'] = {'tokenVersion': 1}
        return await self.db.users.find_one_and_update({'_id': old['_id'], 'tokenVersion': old.get('tokenVersion', 0), 'updatedAt': old['updatedAt']}, update, return_document=ReturnDocument.AFTER)

    async def list_portfolios(self, limit: int, offset: int) -> tuple[list[dict], int]:
        """List portfolio identifiers and names for assignment independently of view permission."""
        query = {'deleting': {'$ne': True}}
        items = await self.db.portfolios.find(query, {'name': 1}).sort([('name', 1), ('_id', 1)]).skip(offset).limit(limit).to_list(None)
        return [{'id': str(item['_id']), 'name': item['name']} for item in items], await self.db.portfolios.count_documents(query)

    async def list_roles(self, limit: int, offset: int) -> tuple[list[dict], int]:
        """Return a stable bounded role page."""
        return await self.db.roles.find({}).sort([('name', 1), ('_id', 1)]).skip(offset).limit(limit).to_list(None), await self.db.roles.count_documents({})

    async def role(self, identifier: ObjectId) -> dict | None:
        """Find a role by identifier."""
        return await self.db.roles.find_one({'_id': identifier})

    async def create_role(self, fields: dict) -> dict:
        """Insert a predefined role when it does not already exist."""
        now = timestamp()
        result = await self.db.roles.insert_one({**fields, 'createdAt': now, 'updatedAt': now})
        return await self.role(result.inserted_id)

    async def update_role(self, identifier: ObjectId, fields: dict) -> dict | None:
        """Save permissions and description without changing the role identity."""
        return await self.db.roles.find_one_and_update({'_id': identifier}, {'$set': {**fields, 'updatedAt': timestamp()}}, return_document=ReturnDocument.AFTER)

    async def audit(self, actor: dict, action: str, entity: str, identifier: ObjectId) -> None:
        """Record a successful operation without account fields or credentials."""
        now = timestamp()
        await self.db.audit_logs.insert_one({'timestamp': now, 'createdAt': now, 'updatedAt': now, 'userId': str(actor['_id']), 'userName': actor['name'], 'action': action, 'entityType': entity, 'entityId': str(identifier), 'details': f'{entity.capitalize()} {action}'})
