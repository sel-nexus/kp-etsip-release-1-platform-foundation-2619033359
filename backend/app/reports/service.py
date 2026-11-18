"""Build scoped inventory report queries and stream complete CSV exports."""
import re
from bson import ObjectId
from app.applications.repository import ApplicationRepository
from app.applications.service import authorize
from app.audit.service import csv_line
from app.portfolios.repository import PortfolioRepository

APPLICATION_COLUMNS = ['id', 'name', 'portfolioId', 'criticality', 'tier', 'lifecycleStatus', 'applicationHealthScore', 'qualityScore', 'automationCoverage', 'openCriticalDefects', 'riskLevel']
PORTFOLIO_COLUMNS = ['id', 'name', 'owner', 'productArea', 'status', 'applicationCount', 'qualityScore']


async def application_query(repo: ApplicationRepository, user: dict, search: str, portfolio: str | None, criticality: str | None, risk: str | None, lifecycle: str | None, exporting: bool) -> dict:
    """Build a filter constrained to the caller's visible applications."""
    await authorize(repo, user, 'view', portfolio)
    if exporting:
        await authorize(repo, user, 'export', portfolio)
    query: dict = {}
    if user['role'] == 'Portfolio Leader':
        query['portfolioId'] = {'$in': user.get('portfolioAccess', [])}
    if portfolio:
        query['portfolioId'] = portfolio
    if search:
        query['name'] = {'$regex': re.escape(search), '$options': 'i'}
    for key, value in [('criticality', criticality), ('riskLevel', risk), ('lifecycleStatus', lifecycle)]:
        if value:
            query[key] = value
    return query


async def portfolio_query(repo: PortfolioRepository, user: dict, search: str, status: str | None, area: str | None, exporting: bool) -> dict:
    """Build a filter constrained to the caller's visible portfolios."""
    app_repo = ApplicationRepository(repo.db)
    await authorize(app_repo, user, 'view')
    if exporting:
        await authorize(app_repo, user, 'export')
    query: dict = {}
    if user['role'] == 'Portfolio Leader':
        query['_id'] = {'$in': [ObjectId(value) for value in user.get('portfolioAccess', []) if ObjectId.is_valid(value)]}
    if search:
        query['name'] = {'$regex': re.escape(search), '$options': 'i'}
    if status:
        query['status'] = status
    if area:
        query['productArea'] = area
    return query


async def export_rows(cursor, columns: list[str], portfolios: PortfolioRepository | None = None):
    """Stream every matching row and derive portfolio aggregates on demand."""
    yield csv_line(columns)
    async for doc in cursor:
        if portfolios is not None:
            doc = await portfolios.summary(doc)
        yield csv_line([str(doc['_id']) if key == 'id' else doc.get(key, '') for key in columns])
