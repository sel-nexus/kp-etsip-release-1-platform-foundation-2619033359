"""Apply audit access, date filters, and spreadsheet-safe CSV encoding."""
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from fastapi import HTTPException
from app.applications.repository import ApplicationRepository
from app.applications.service import authorize
from app.audit.repository import AuditRepository

AUDIT_COLUMNS = ['timestamp', 'userId', 'userName', 'action', 'entityType', 'entityId', 'details']


async def authorize_audit(repo: AuditRepository, user: dict, export: bool = False) -> None:
    """Restrict audit data to administrators and auditors with effective permissions."""
    if user.get('role') not in {'Administrator', 'Auditor'}:
        raise HTTPException(403, 'Permission denied')
    application_repo = ApplicationRepository(repo.db)
    await authorize(application_repo, user, 'view')
    if export:
        await authorize(application_repo, user, 'export')


def boundary(value: str, end: bool) -> tuple[datetime, bool]:
    """Parse a UTC date or timezone-aware instant for audit filtering."""
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            return datetime.combine(day + (timedelta(days=1) if end else timedelta()), time.min, timezone.utc), end
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            raise ValueError('Timezone required')
        return moment.astimezone(timezone.utc), False
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, 'Dates must be ISO dates or timezone-aware timestamps') from exc


def filters(user_id: str | None, action: str | None, start: str | None, end: str | None) -> dict:
    """Build safe exact-match and chronological audit filters."""
    query: dict = {}
    if user_id:
        query['userId'] = user_id
    if action:
        query['action'] = action
    low = boundary(start, False)[0] if start else None
    high, exclusive = boundary(end, True) if end else (None, False)
    if low and high and (low > high or (exclusive and low == high)):
        raise HTTPException(422, 'from must not be later than to')
    if low or high:
        parsed = {'$convert': {'input': '$timestamp', 'to': 'date', 'onError': None, 'onNull': None}}
        conditions = [{'$ne': [parsed, None]}]
        if low:
            conditions.append({'$gte': [parsed, low]})
        if high:
            conditions.append({'$lt' if exclusive else '$lte': [parsed, high]})
        query['$expr'] = {'$and': conditions}
    return query


def public_event(doc: dict) -> dict:
    """Return only public audit fields and the string identifier."""
    return {'id': str(doc['_id']), **{key: doc.get(key) for key in AUDIT_COLUMNS}}


def csv_line(values: list) -> str:
    """Encode one CSV row and neutralize spreadsheet formulas and controls."""
    output = io.StringIO(newline='')
    safe = []
    for value in values:
        if isinstance(value, str) and (value.lstrip(' ').startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@'))):
            value = "'" + value
        safe.append(value)
    csv.writer(output).writerow(safe)
    return output.getvalue()


async def csv_stream(cursor, columns: list[str]):
    """Stream a complete result set with constant memory."""
    yield csv_line(columns)
    async for doc in cursor:
        yield csv_line([str(doc['_id']) if column == 'id' else doc.get(column, '') for column in columns])
