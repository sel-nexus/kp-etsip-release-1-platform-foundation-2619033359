"""Enforce portfolio role ceilings, scope and business rules."""
import re
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from app.portfolios.repository import PortfolioRepository


async def authorize(repo: PortfolioRepository, user: dict, action: str, identifier: str | None = None) -> None:
    """Require both the fixed resource ceiling and the editable permission."""
    role = user.get("role")
    ceilings = {"view": {"Administrator", "Executive", "Portfolio Leader", "Engineer", "Auditor", "Read Only"}, "create": {"Administrator"}, "edit": {"Administrator", "Portfolio Leader"}, "delete": {"Administrator"}}
    if role not in ceilings[action] or not await repo.allowed(role, action):
        raise HTTPException(403, "Permission denied")
    if identifier is not None and role == "Portfolio Leader" and identifier not in user.get("portfolioAccess", []):
        raise HTTPException(403, "Portfolio is outside your assigned scope")


def object_id(identifier: str) -> ObjectId:
    """Reject malformed or unknown-looking identifiers consistently."""
    if not ObjectId.is_valid(identifier):
        raise HTTPException(404, "Portfolio not found")
    return ObjectId(identifier)


async def fetch(repo: PortfolioRepository, user: dict, identifier: str, action: str = "view") -> dict:
    """Check visibility before looking up the portfolio."""
    await authorize(repo, user, action, identifier)
    doc = await repo.get(object_id(identifier))
    if doc is None:
        raise HTTPException(404, "Portfolio not found")
    return doc


async def list_portfolios(repo: PortfolioRepository, user: dict, search: str, status: str | None, area: str | None, limit: int, offset: int) -> dict:
    """Apply visibility and user-supplied filters to a bounded page."""
    await authorize(repo, user, "view")
    query: dict = {}
    if user["role"] == "Portfolio Leader":
        query["_id"] = {"$in": [ObjectId(value) for value in user.get("portfolioAccess", []) if ObjectId.is_valid(value)]}
    if search:
        query["name"] = {"$regex": re.escape(search), "$options": "i"}
    if status:
        query["status"] = status
    if area:
        query["productArea"] = area
    items, total = await repo.list_portfolios(query, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def save(repo: PortfolioRepository, user: dict, fields: dict, identifier: str | None = None) -> dict:
    """Create or update a portfolio and audit the successful change."""
    action = "edit" if identifier else "create"
    if identifier:
        await fetch(repo, user, identifier, action)
    else:
        await authorize(repo, user, action)
    try:
        doc = await repo.update(object_id(identifier), fields) if identifier else await repo.create(fields)
    except DuplicateKeyError as exc:
        raise HTTPException(409, "A portfolio with this name already exists") from exc
    if doc is None:
        raise HTTPException(404, "Portfolio not found")
    await repo.audit(user, action, doc["_id"])
    return await repo.summary(doc)


async def remove(repo: PortfolioRepository, user: dict, identifier: str) -> None:
    """Reject referenced portfolios and audit successful deletion."""
    doc = await fetch(repo, user, identifier, "delete")
    if not await repo.begin_delete(doc["_id"]):
        raise HTTPException(409, "Portfolio is busy or being deleted; try again")
    if await repo.has_applications(doc["_id"]):
        await repo.cancel_delete(doc["_id"])
        raise HTTPException(409, "Cannot delete a portfolio containing applications")
    if not await repo.delete(doc["_id"]):
        raise HTTPException(404, "Portfolio not found")
    await repo.audit(user, "delete", doc["_id"])
