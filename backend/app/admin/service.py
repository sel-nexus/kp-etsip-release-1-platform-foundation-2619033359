"""Enforce administrative authorization, ceilings, and account safety."""
from contextlib import asynccontextmanager
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool
from app.admin.repository import AdminRepository
from app.applications.repository import ApplicationRepository
from app.core.security import hash_password
from app.core.seed import ROLES


async def authorize(repo: AdminRepository, actor: dict) -> None:
    """Require an active administrator with management permission."""
    current = await repo.user(actor['_id'])
    if not current or current.get('status') != 'Active' or current.get('role') != 'Administrator' or current.get('tokenVersion', 0) != actor.get('tokenVersion', 0) or not await repo.allowed():
        raise HTTPException(403, 'Permission denied')


def identifier(value: str, entity: str) -> ObjectId:
    """Translate an API identifier or report a missing entity."""
    if not ObjectId.is_valid(value):
        raise HTTPException(404, f'{entity} not found')
    return ObjectId(value)


@asynccontextmanager
async def mutation_lock(repo: AdminRepository):
    """Serialize changes that could otherwise remove the last administrator."""
    try:
        await repo.lock()
    except DuplicateKeyError as exc:
        raise HTTPException(409, 'Administration is busy; try again') from exc
    try:
        yield
    finally:
        await repo.unlock()


async def get_user(repo: AdminRepository, value: str) -> dict:
    """Find an account or return a not-found response."""
    doc = await repo.user(identifier(value, 'User'))
    if not doc:
        raise HTTPException(404, 'User not found')
    return doc


async def save_user(repo: AdminRepository, actor: dict, fields: dict, value: str | None = None) -> dict:
    """Create or update an account with safe scope and token revocation."""
    await authorize(repo, actor)
    async with mutation_lock(repo):
        await authorize(repo, actor)
        old = await get_user(repo, value) if value else None
        password = fields.pop('password')
        if old is None and not password:
            raise HTTPException(422, 'Password is required when creating a user')
        if old and old['_id'] == actor['_id'] and (fields['role'] != 'Administrator' or fields['status'] != 'Active'):
            raise HTTPException(409, 'You cannot deactivate or demote your own account')
        if old and old['role'] == 'Administrator' and old['status'] == 'Active' and (fields['role'] != 'Administrator' or fields['status'] != 'Active') and await repo.active_admins() <= 1:
            raise HTTPException(409, 'At least one active administrator is required')
        if len(fields['portfolioAccess']) != len(set(fields['portfolioAccess'])):
            raise HTTPException(422, 'Portfolio assignments must be unique')
        if not await repo.db.roles.find_one({'name': fields['role']}):
            raise HTTPException(422, 'Role does not exist')
        reservations = []
        applications = ApplicationRepository(repo.db)
        release = False
        try:
            for item in fields['portfolioAccess']:
                if not ObjectId.is_valid(item) or str(ObjectId(item)) != item:
                    raise HTTPException(422, 'Invalid portfolio assignment')
                token = await applications.reserve(ObjectId(item))
                if not token:
                    raise HTTPException(422, 'Portfolio does not exist or is being deleted')
                reservations.append((ObjectId(item), token))
            if password:
                fields['passwordHash'] = await run_in_threadpool(hash_password, password)
                fields['mustChangePassword'] = True
            if old is None:
                fields.update({'authSource': 'local', 'lastLogin': None, 'defaultLandingPage': None, 'tokenVersion': 0})
                doc = await repo.create_user(fields)
            else:
                revoke = bool(password or old['role'] != fields['role'] or old['status'] != fields['status'])
                doc = await repo.update_user(old, fields, revoke)
            release = True
        except (DuplicateKeyError, HTTPException) as exc:
            release = True
            if isinstance(exc, DuplicateKeyError):
                raise HTTPException(409, 'An account with this email already exists') from exc
            raise
        finally:
            if release:
                for portfolio, token in reservations:
                    await applications.release(portfolio, token)
        if not doc:
            raise HTTPException(409, 'Account changed; reload and try again')
        await repo.audit(actor, 'create' if old is None else 'edit', 'user', doc['_id'])
        if old and old['role'] != doc['role']:
            await repo.audit(actor, 'roleChange', 'user', doc['_id'])
        if old and old['status'] == 'Active' and doc['status'] == 'Inactive':
            await repo.audit(actor, 'deactivate', 'user', doc['_id'])
        return doc


async def deactivate(repo: AdminRepository, actor: dict, value: str) -> None:
    """Deactivate an account without deleting its audit identity."""
    await authorize(repo, actor)
    async with mutation_lock(repo):
        await authorize(repo, actor)
        old = await get_user(repo, value)
        if old['_id'] == actor['_id']:
            raise HTTPException(409, 'You cannot deactivate your own account')
        if old['status'] != 'Active':
            raise HTTPException(409, 'Account is already inactive')
        if old['role'] == 'Administrator' and await repo.active_admins() <= 1:
            raise HTTPException(409, 'At least one active administrator is required')
        doc = await repo.update_user(old, {'status': 'Inactive'}, True)
        if not doc:
            raise HTTPException(409, 'Account changed; reload and try again')
        await repo.audit(actor, 'deactivate', 'user', doc['_id'])


def validate_role(fields: dict) -> None:
    """Reject permissions above the fixed role ceiling and admin lockout."""
    if not set(fields['permissions']).issubset(ROLES[fields['name']]):
        raise HTTPException(422, 'Permissions exceed the role ceiling')
    if fields['name'] == 'Administrator' and 'administer' not in fields['permissions']:
        raise HTTPException(409, 'Administrator must retain administer permission')


async def save_role(repo: AdminRepository, actor: dict, fields: dict, value: str | None = None) -> dict:
    """Create or edit a predefined role and audit permission changes."""
    await authorize(repo, actor)
    validate_role(fields)
    async with mutation_lock(repo):
        await authorize(repo, actor)
        old = await repo.role(identifier(value, 'Role')) if value else None
        if value and not old:
            raise HTTPException(404, 'Role not found')
        if old and old['name'] != fields['name']:
            raise HTTPException(422, 'Role names cannot be changed')
        try:
            doc = await repo.update_role(old['_id'], fields) if old else await repo.create_role(fields)
        except DuplicateKeyError as exc:
            raise HTTPException(409, 'Role already exists') from exc
        if not doc:
            raise HTTPException(409, 'Role changed; reload and try again')
        await repo.audit(actor, 'edit' if old else 'create', 'role', doc['_id'])
        if old is None or set(old['permissions']) != set(doc['permissions']):
            await repo.audit(actor, 'permissionChange', 'role', doc['_id'])
        return doc
