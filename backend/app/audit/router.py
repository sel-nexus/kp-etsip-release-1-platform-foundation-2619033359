"""Expose a separate authorized audit log view and export."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pymongo.asynchronous.database import AsyncDatabase
from app.audit import service
from app.audit.repository import AuditRepository
from app.core.database import get_database
from app.core.security import require_ready_user

router = APIRouter(prefix='/audit-logs', tags=['Audit'])
DB = Annotated[AsyncDatabase, Depends(get_database)]
User = Annotated[dict, Depends(require_ready_user)]


@router.get('')
async def audit_logs(db: DB, user: User, userId: str | None = None, action: str | None = None, from_date: Annotated[str | None, Query(alias='from')] = None, to: str | None = None, format: Literal['json', 'csv'] = 'json', limit: Annotated[int, Query(ge=1, le=100)] = 25, offset: Annotated[int, Query(ge=0)] = 0):
    """Filter events or export all matching events after authorization."""
    repo = AuditRepository(db)
    await service.authorize_audit(repo, user, format == 'csv')
    query = service.filters(userId, action, from_date, to)
    if format == 'csv':
        # The export event is recorded before the stream; it may be included in the result.
        await repo.export_event(user, 'audit')
        return StreamingResponse(service.csv_stream(repo.cursor(query), service.AUDIT_COLUMNS), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="audit.csv"'})
    items, total = await repo.page(query, limit, offset)
    return {'items': [service.public_event(item) for item in items], 'total': total, 'limit': limit, 'offset': offset}
