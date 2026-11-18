"""Expose scoped application inventory endpoints."""
import csv
import io
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from pymongo.asynchronous.database import AsyncDatabase
from app.applications import service
from app.applications.repository import ApplicationRepository
from app.applications.schemas import Application, ApplicationInput, ApplicationPage, Criticality, Lifecycle, Risk
from app.core.database import get_database
from app.core.security import require_ready_user

router = APIRouter(prefix="/applications", tags=["Applications"])
DB = Annotated[AsyncDatabase, Depends(get_database)]
User = Annotated[dict, Depends(require_ready_user)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/capabilities")
async def capabilities(db: DB, user: User) -> dict[str, bool]:
    """Expose effective resource-level controls without weakening route guards."""
    repo = ApplicationRepository(db)
    result = {}
    for action in ("view", "create", "edit", "delete", "export"):
        try:
            await service.authorize(repo, user, action)
        except service.HTTPException as exc:
            if exc.status_code != 403:
                raise
            result[action] = False
        else:
            result[action] = True
    return result


@router.get("/export")
async def export_applications(db: DB, user: User, search: str = "", portfolioId: str | None = None, criticality: Criticality | None = None, riskLevel: Risk | None = None, lifecycleStatus: Lifecycle | None = None) -> Response:
    """Export the filtered visible inventory and audit the export."""
    repo = ApplicationRepository(db)
    await service.authorize(repo, user, "export", portfolioId)
    output = io.StringIO(newline="")
    columns = ['name', 'portfolioId', 'criticality', 'tier', 'lifecycleStatus', 'applicationHealthScore', 'automationCoverage', 'openCriticalDefects', 'riskLevel']
    writer = csv.writer(output)
    writer.writerow(columns)
    offset = 0
    while True:
        page = await service.list_applications(repo, user, search, portfolioId, criticality, riskLevel, lifecycleStatus, 100, offset)
        for item in page['items']:
            row = []
            for column in columns:
                value = item.get(column, '')
                if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                    value = "'" + value
                row.append(value)
            writer.writerow(row)
        offset += len(page['items'])
        if not page['items'] or offset >= page['total']:
            break
    await repo.audit(user, 'export', None)
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="applications.csv"'})


@router.get("", response_model=ApplicationPage)
async def list_applications(db: DB, user: User, search: str = "", portfolioId: str | None = None, criticality: Criticality | None = None, riskLevel: Risk | None = None, lifecycleStatus: Lifecycle | None = None, limit: Limit = 25, offset: Offset = 0) -> dict:
    """List visible applications with search and filters."""
    return await service.list_applications(ApplicationRepository(db), user, search, portfolioId, criticality, riskLevel, lifecycleStatus, limit, offset)


@router.post("", response_model=Application, status_code=201)
async def create_application(body: ApplicationInput, db: DB, user: User) -> dict:
    """Create an application within an authorized portfolio."""
    return await service.save(ApplicationRepository(db), user, body.model_dump(mode="json"))


@router.get("/{identifier}", response_model=Application)
async def get_application(identifier: str, db: DB, user: User) -> dict:
    """Return a visible application."""
    return await service.fetch(ApplicationRepository(db), user, identifier)


@router.put("/{identifier}", response_model=Application)
async def update_application(identifier: str, body: ApplicationInput, db: DB, user: User) -> dict:
    """Replace editable attributes of an authorized application."""
    return await service.save(ApplicationRepository(db), user, body.model_dump(mode="json"), identifier)


@router.delete("/{identifier}", status_code=204)
async def delete_application(identifier: str, db: DB, user: User) -> Response:
    """Delete an application as an administrator."""
    await service.remove(ApplicationRepository(db), user, identifier)
    return Response(status_code=204)
