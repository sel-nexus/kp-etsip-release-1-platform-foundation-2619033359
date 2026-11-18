"""Expose administrator-only user and role management endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from pymongo.asynchronous.database import AsyncDatabase
from app.admin import service
from app.admin.repository import AdminRepository
from app.admin.schemas import PublicRole, RoleInput, RolePage, UserInput, UserPage
from app.auth.schemas import PublicUser
from app.core.database import get_database
from app.core.security import require_ready_user

router = APIRouter(tags=['Administration'])
DB = Annotated[AsyncDatabase, Depends(get_database)]
User = Annotated[dict, Depends(require_ready_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get('/users', response_model=UserPage)
async def list_users(db: DB, user: User, limit: Limit = 25, offset: Offset = 0) -> dict:
    """Return a bounded list of accounts."""
    repo = AdminRepository(db)
    await service.authorize(repo, user)
    items, total = await repo.list_users(limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.post('/users', response_model=PublicUser, status_code=201)
async def create_user(body: UserInput, db: DB, user: User) -> dict:
    """Create a local account."""
    return await service.save_user(AdminRepository(db), user, body.model_dump())


@router.get('/users/{identifier}', response_model=PublicUser)
async def get_user(identifier: str, db: DB, user: User) -> dict:
    """Read an account without exposing credentials."""
    repo = AdminRepository(db)
    await service.authorize(repo, user)
    return await service.get_user(repo, identifier)


@router.put('/users/{identifier}', response_model=PublicUser)
async def update_user(identifier: str, body: UserInput, db: DB, user: User) -> dict:
    """Update a local account."""
    return await service.save_user(AdminRepository(db), user, body.model_dump(), identifier)


@router.delete('/users/{identifier}', status_code=204)
async def deactivate_user(identifier: str, db: DB, user: User) -> Response:
    """Deactivate an account while retaining its audit history."""
    await service.deactivate(AdminRepository(db), user, identifier)
    return Response(status_code=204)


@router.get('/admin/portfolios')
async def portfolio_options(db: DB, user: User, limit: Limit = 25, offset: Offset = 0) -> dict:
    """List assignment options for authorized administrators."""
    repo = AdminRepository(db)
    await service.authorize(repo, user)
    items, total = await repo.list_portfolios(limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/roles', response_model=RolePage)
async def list_roles(db: DB, user: User, limit: Limit = 25, offset: Offset = 0) -> dict:
    """Return predefined roles and their editable permissions."""
    repo = AdminRepository(db)
    await service.authorize(repo, user)
    items, total = await repo.list_roles(limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.post('/roles', response_model=PublicRole, status_code=201)
async def create_role(body: RoleInput, db: DB, user: User) -> dict:
    """Create a missing predefined role."""
    return await service.save_role(AdminRepository(db), user, body.model_dump())


@router.put('/roles/{identifier}', response_model=PublicRole)
async def update_role(identifier: str, body: RoleInput, db: DB, user: User) -> dict:
    """Change a role's description or bounded permissions."""
    return await service.save_role(AdminRepository(db), user, body.model_dump(), identifier)
