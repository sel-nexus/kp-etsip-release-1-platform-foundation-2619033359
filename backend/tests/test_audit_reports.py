"""Exercise audit and report APIs against isolated real MongoDB."""
import csv
import io
import os
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('JWT_SECRET', 'test-only-secret-for-reports-tests')
from app.core.config import get_settings
from app.main import app


@pytest.fixture
async def client(monkeypatch):
    """Use a fresh seeded MongoDB database per test."""
    values = {'JWT_SECRET': 'test-only-secret-for-reports-tests', 'MONGODB_URI': os.getenv('TEST_MONGODB_URI', 'mongodb://127.0.0.1:27017'), 'MONGODB_DB': 'reports_test_' + uuid4().hex, 'SEED_ON_STARTUP': 'true', 'ADMIN_INITIAL_PASSWORD': 'TestAdmin123!', 'DEMO_INITIAL_PASSWORD': 'TestDemo123!'}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        async with app.router.lifespan_context(app):
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http:
                    yield http
            finally:
                await app.state.db.client.drop_database(values['MONGODB_DB'])
    finally:
        get_settings.cache_clear()


async def login(client, role):
    """Sign in using the real seeded credentials."""
    password = 'TestAdmin123!' if role == 'admin' else 'TestDemo123!'
    result = await client.post('/api/auth/login', json={'email': f'{role}@ketsip.local', 'password': password})
    assert result.status_code == 200
    token = result.json()['token']
    if role == 'admin':
        result = await client.put('/api/profile/password', headers={'Authorization': 'Bearer ' + token}, json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
        assert result.status_code == 200
        token = result.json()['token']
    return {'Authorization': 'Bearer ' + token}


async def test_audit_access_filters_export_and_validation(client):
    """Restrict audit to eligible roles and persist safe export events."""
    assert (await client.get('/api/audit-logs')).status_code == 401
    for role in ('executive', 'leader', 'engineer', 'readonly'):
        auth = await login(client, role)
        assert (await client.get('/api/audit-logs', headers=auth)).status_code == 403
    auditor = await login(client, 'auditor')
    assert (await client.get('/api/users', headers=auditor)).status_code == 403
    assert (await client.get('/api/roles', headers=auditor)).status_code == 403
    admin = await login(client, 'admin')
    assert (await client.get('/api/audit-logs', headers=admin)).status_code == 200
    user = await app.state.db.users.find_one({'email': 'auditor@ketsip.local'})
    await app.state.db.audit_logs.insert_one({'timestamp': '2024-04-03T12:00:00+00:00', 'userId': str(user['_id']), 'userName': '=HYPERLINK("bad")', 'action': 'edit', 'entityType': 'test', 'entityId': None, 'details': '\t=1'})
    params = {'userId': str(user['_id']), 'action': 'edit', 'from': '2024-04-03', 'to': '2024-04-03', 'limit': 1}
    response = await client.get('/api/audit-logs', headers=auditor, params=params)
    assert response.status_code == 200 and response.json()['total'] == 1
    assert response.json()['items'][0]['userName'].startswith('=')
    response = await client.get('/api/audit-logs', headers=auditor, params={**params, 'format': 'csv'})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]['userName'].startswith("'=") and rows[0]['details'].startswith("'\t")
    event = await app.state.db.audit_logs.find_one({'action': 'export', 'entityType': 'audit'})
    assert event and 'password' not in str(event).lower()
    for invalid in ({'from': 'bad'}, {'from': '2024-04-05', 'to': '2024-04-03'}, {'limit': 101}, {'format': 'pdf'}):
        assert (await client.get('/api/audit-logs', headers=auditor, params=invalid)).status_code == 422
    await app.state.db.roles.update_one({'name': 'Auditor'}, {'$set': {'permissions': ['view']}})
    assert (await client.get('/api/audit-logs', headers=auditor)).status_code == 200
    assert (await client.get('/api/audit-logs?format=csv', headers=auditor)).status_code == 403
    await app.state.db.roles.update_one({'name': 'Auditor'}, {'$set': {'permissions': ['export']}})
    assert (await client.get('/api/audit-logs', headers=auditor)).status_code == 403


async def test_reports_scope_filters_and_csv(client):
    """Enforce portfolio scope, editable permissions and safe complete exports."""
    leader = await login(client, 'leader')
    readonly = await login(client, 'readonly')
    engineer = await login(client, 'engineer')
    own = await app.state.db.portfolios.find_one({'name': 'Payments'})
    other = await app.state.db.portfolios.find_one({'name': 'Customer Platform'})
    own_id, other_id = str(own['_id']), str(other['_id'])
    assert (await client.get('/api/reports/applications', headers=leader, params={'portfolioId': other_id})).status_code == 403
    for kind in ('applications', 'portfolios'):
        assert (await client.get('/api/reports/' + kind, headers=readonly)).status_code == 200
        assert (await client.get('/api/reports/' + kind + '?format=csv', headers=readonly)).status_code == 403
        result = await client.get('/api/reports/' + kind, headers=leader)
        assert result.status_code == 200
        if kind == 'portfolios':
            assert all(item['id'] == own_id for item in result.json()['items'])
        else:
            assert all(item['portfolioId'] == own_id for item in result.json()['items'])
    await app.state.db.applications.update_one({'portfolioId': own_id}, {'$set': {'name': '=danger'}})
    result = await client.get('/api/reports/applications', headers=engineer, params={'search': '=danger', 'limit': 1})
    assert result.status_code == 200 and result.json()['total'] == 1
    result = await client.get('/api/reports/applications', headers=leader, params={'search': '=danger', 'format': 'csv', 'limit': 1, 'offset': 99})
    assert list(csv.DictReader(io.StringIO(result.text)))[0]['name'] == "'=danger"
    result = await client.get('/api/reports/portfolios', headers=engineer, params={'search': 'Payments', 'format': 'csv'})
    rows = list(csv.DictReader(io.StringIO(result.text)))
    assert len(rows) == 1 and rows[0]['id'] == own_id
    assert int(rows[0]['applicationCount']) == await app.state.db.applications.count_documents({'portfolioId': own_id})
    assert await app.state.db.audit_logs.count_documents({'action': 'export', 'entityType': {'$in': ['application report', 'portfolio report']}}) == 2
    assert (await client.get('/api/reports/applications', headers=engineer, params={'riskLevel': 'Invalid'})).status_code == 422
    assert (await client.get('/api/reports/portfolios', headers=engineer, params={'limit': 101})).status_code == 422
    await app.state.db.users.update_one({'email': 'leader@ketsip.local'}, {'$set': {'portfolioAccess': []}})
    assert (await client.get('/api/reports/portfolios', headers=leader)).json()['total'] == 0
    await app.state.db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['view']}})
    assert (await client.get('/api/reports/applications?format=csv', headers=engineer)).status_code == 403
    await app.state.db.roles.update_one({'name': 'Read Only'}, {'$set': {'permissions': ['view', 'export']}})
    assert (await client.get('/api/reports/portfolios?format=csv', headers=readonly)).status_code == 403
    await app.state.db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['export']}})
    assert (await client.get('/api/reports/portfolios?format=csv', headers=engineer)).status_code == 403


async def test_complete_filtered_csv_and_persisted_inventory(client):
    """Export beyond the JSON page limit using persisted inventory and filters."""
    auth = await login(client, 'engineer')
    portfolio = await app.state.db.portfolios.find_one({'name': 'Payments'})
    portfolio_id = str(portfolio['_id'])
    template = await app.state.db.applications.find_one({'portfolioId': portfolio_id})
    template.pop('_id')
    payloads = [{**template, 'name': f'Bulk {number:03}', 'riskLevel': 'High', 'qualityScore': 10} for number in range(105)]
    await app.state.db.applications.insert_many(payloads)
    params = {'search': 'Bulk', 'riskLevel': 'High', 'limit': 2, 'offset': 0}
    page = await client.get('/api/reports/applications', headers=auth, params=params)
    assert page.status_code == 200 and page.json()['total'] == 105 and len(page.json()['items']) == 2
    exported = await client.get('/api/reports/applications', headers=auth, params={**params, 'format': 'csv', 'offset': 100})
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 105 and all(row['portfolioId'] == portfolio_id for row in rows)
    assert await app.state.db.audit_logs.count_documents({'action': 'export', 'entityType': 'application report'}) == 1
    auditor = await login(client, 'auditor')
    result = await client.get('/api/audit-logs', headers=auditor, params={'action': 'export'})
    assert any(item['entityType'] == 'application report' for item in result.json()['items'])
