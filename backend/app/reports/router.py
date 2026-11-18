"""Expose scoped application and portfolio report views and exports."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pymongo.asynchronous.database import AsyncDatabase
from app.applications.repository import ApplicationRepository
from app.applications.schemas import ApplicationPage, Criticality, Lifecycle, Risk
from app.audit.repository import AuditRepository
from app.core.database import get_database
from app.core.security import require_ready_user
from app.portfolios.repository import PortfolioRepository
from app.portfolios.schemas import PortfolioPage
from app.reports import service

router = APIRouter(prefix='/reports', tags=['Reports'])
DB = Annotated[AsyncDatabase, Depends(get_database)]
User = Annotated[dict, Depends(require_ready_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get('/applications', response_model=ApplicationPage)
async def applications(db: DB, user: User, search: str = '', portfolioId: str | None = None, criticality: Criticality | None = None, riskLevel: Risk | None = None, lifecycleStatus: Lifecycle | None = None, format: Literal['json', 'csv'] = 'json', limit: Limit = 25, offset: Offset = 0):
    """Return a bounded application page or a complete filtered export."""
    repo = ApplicationRepository(db)
    query = await service.application_query(repo, user, search, portfolioId, criticality, riskLevel, lifecycleStatus, format == 'csv')
    if format == 'csv':
        await AuditRepository(db).export_event(user, 'application report')
        cursor = db.applications.find(query).sort([('name', 1), ('_id', 1)])
        return StreamingResponse(service.export_rows(cursor, service.APPLICATION_COLUMNS), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="application-report.csv"'})
    items, total = await repo.list(query, limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/portfolios', response_model=PortfolioPage)
async def portfolios(db: DB, user: User, search: str = '', status: Literal['Active', 'Archived'] | None = None, productArea: str | None = None, format: Literal['json', 'csv'] = 'json', limit: Limit = 25, offset: Offset = 0):
    """Return a bounded portfolio page or a complete filtered export."""
    repo = PortfolioRepository(db)
    query = await service.portfolio_query(repo, user, search, status, productArea, format == 'csv')
    if format == 'csv':
        await AuditRepository(db).export_event(user, 'portfolio report')
        cursor = db.portfolios.find(query).sort([('name', 1), ('_id', 1)])
        return StreamingResponse(service.export_rows(cursor, service.PORTFOLIO_COLUMNS, repo), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="portfolio-report.csv"'})
    items, total = await repo.list_portfolios(query, limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
