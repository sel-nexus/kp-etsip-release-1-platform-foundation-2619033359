"""Enforce application permissions, scope, validation and reference safety."""
import re
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from app.applications.repository import ApplicationRepository


async def authorize(repo: ApplicationRepository, user: dict, action: str, portfolio_id: str | None = None) -> None:
    """Apply fixed role ceilings, editable permissions, and leader scope."""
    ceilings = {"view": {"Administrator", "Executive", "Portfolio Leader", "Engineer", "Auditor", "Read Only"}, "create": {"Administrator", "Portfolio Leader", "Engineer"}, "edit": {"Administrator", "Portfolio Leader", "Engineer"}, "delete": {"Administrator"}, "export": {"Administrator", "Executive", "Portfolio Leader", "Engineer", "Auditor"}}
    if user.get("role") not in ceilings[action] or not await repo.allowed(user["role"], action):
        raise HTTPException(403, "Permission denied")
    if portfolio_id is not None and user["role"] == "Portfolio Leader" and portfolio_id not in user.get("portfolioAccess", []):
        raise HTTPException(403, "Portfolio is outside your assigned scope")


def object_id(identifier: str, entity: str = "Application") -> ObjectId:
    """Convert a valid identifier or report a missing resource."""
    if not ObjectId.is_valid(identifier):
        raise HTTPException(404, f"{entity} not found")
    return ObjectId(identifier)


async def fetch(repo: ApplicationRepository, user: dict, identifier: str, action: str = "view") -> dict:
    """Read a record only after enforcing its current portfolio scope."""
    await authorize(repo, user, action)
    doc = await repo.get(object_id(identifier))
    if doc is None:
        raise HTTPException(404, "Application not found")
    await authorize(repo, user, action, doc["portfolioId"])
    return doc


async def list_applications(repo: ApplicationRepository, user: dict, search: str, portfolio_id: str | None, criticality: str | None, risk: str | None, lifecycle: str | None, limit: int, offset: int) -> dict:
    """Filter visible applications and return a bounded page."""
    await authorize(repo, user, "view", portfolio_id)
    query: dict = {}
    if user["role"] == "Portfolio Leader":
        query["portfolioId"] = {"$in": user.get("portfolioAccess", [])}
    if portfolio_id:
        query["portfolioId"] = portfolio_id
    if search:
        query["name"] = {"$regex": re.escape(search), "$options": "i"}
    for field, value in (("criticality", criticality), ("riskLevel", risk), ("lifecycleStatus", lifecycle)):
        if value:
            query[field] = value
    items, total = await repo.list(query, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def save(repo: ApplicationRepository, user: dict, fields: dict, identifier: str | None = None) -> dict:
    """Save an application while holding its destination portfolio reservation."""
    action = "edit" if identifier else "create"
    previous = await fetch(repo, user, identifier, action) if identifier else None
    destination = object_id(fields["portfolioId"], "Portfolio")
    fields = {**fields, "portfolioId": str(destination)}
    await authorize(repo, user, action, fields["portfolioId"])
    token = await repo.reserve(destination)
    if not token:
        raise HTTPException(409, "Portfolio does not exist or is being deleted")
    # Release only after an acknowledged write or a definite duplicate rejection.
    # A network/DB exception may hide a committed write, so retain the reservation.
    try:
        if previous:
            doc = await repo.update(previous["_id"], previous["portfolioId"], fields)
        else:
            doc = await repo.create(fields)
    except DuplicateKeyError as exc:
        await repo.release(destination, token)
        raise HTTPException(409, "An application with this name already exists") from exc
    await repo.release(destination, token)
    if doc is None:
        raise HTTPException(409, "Application changed or was deleted; reload and try again")
    await repo.audit(user, action, doc["_id"])
    return doc


async def remove(repo: ApplicationRepository, user: dict, identifier: str) -> None:
    """Delete an application only for an authorized administrator."""
    doc = await fetch(repo, user, identifier, "delete")
    if not await repo.delete(doc["_id"]):
        raise HTTPException(404, "Application not found")
    await repo.audit(user, "delete", doc["_id"])
