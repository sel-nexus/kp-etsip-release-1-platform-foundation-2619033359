"""Expose authenticated portfolio inventory endpoints."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Response
from pymongo.asynchronous.database import AsyncDatabase
from app.core.database import get_database
from app.core.security import require_ready_user
from app.portfolios import service
from app.portfolios.repository import PortfolioRepository
from app.portfolios.schemas import ApplicationPage, Portfolio, PortfolioInput, PortfolioPage

router = APIRouter(prefix="/portfolios", tags=["Portfolios"])
DB = Annotated[AsyncDatabase, Depends(get_database)]
User = Annotated[dict, Depends(require_ready_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("", response_model=PortfolioPage)
async def list_portfolios(db: DB, user: User, search: str = "", status: Literal["Active", "Archived"] | None = None, productArea: str | None = None, limit: Limit = 25, offset: Offset = 0) -> dict:
    """List visible portfolios with search and filters."""
    return await service.list_portfolios(PortfolioRepository(db), user, search, status, productArea, limit, offset)


@router.post("", response_model=Portfolio, status_code=201)
async def create_portfolio(body: PortfolioInput, db: DB, user: User) -> dict:
    """Create a portfolio for an authorized administrator."""
    return await service.save(PortfolioRepository(db), user, body.model_dump())


@router.get("/{identifier}", response_model=Portfolio)
async def get_portfolio(identifier: str, db: DB, user: User) -> dict:
    """Read a visible portfolio and its computed summary."""
    repo = PortfolioRepository(db)
    return await repo.summary(await service.fetch(repo, user, identifier))


@router.put("/{identifier}", response_model=Portfolio)
async def update_portfolio(identifier: str, body: PortfolioInput, db: DB, user: User) -> dict:
    """Update an authorized portfolio."""
    return await service.save(PortfolioRepository(db), user, body.model_dump(), identifier)


@router.delete("/{identifier}", status_code=204)
async def delete_portfolio(identifier: str, db: DB, user: User) -> Response:
    """Delete an empty portfolio as an administrator."""
    await service.remove(PortfolioRepository(db), user, identifier)
    return Response(status_code=204)


@router.get("/{identifier}/applications", response_model=ApplicationPage)
async def applications(identifier: str, db: DB, user: User, limit: Limit = 25, offset: Offset = 0) -> dict:
    """List applications belonging to a visible portfolio."""
    repo = PortfolioRepository(db)
    doc = await service.fetch(repo, user, identifier)
    items, total = await repo.applications(doc["_id"], limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
