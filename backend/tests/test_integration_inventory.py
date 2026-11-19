"""Exercise the inventory lifecycle across APIs with a real MongoDB database."""
import csv
import io
import os
from uuid import uuid4

import pytest
from bson import ObjectId
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('JWT_SECRET', 'test-only-secret-for-inventory-integration')
from app.core.config import get_settings
from app.main import app


@pytest.fixture
async def client(monkeypatch):
    """Start the real app against an isolated seeded database and remove only it."""
    values = {
        'JWT_SECRET': 'test-only-secret-for-inventory-integration',
        'MONGODB_URI': os.getenv('TEST_MONGODB_URI', 'mongodb://127.0.0.1:27017'),
        'MONGODB_DB': 'integration_inventory_' + uuid4().hex,
        'SEED_ON_STARTUP': 'true',
        'ADMIN_INITIAL_PASSWORD': 'TestAdmin123!',
        'DEMO_INITIAL_PASSWORD': 'TestDemo123!',
    }
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
    """Sign in with a seeded account, satisfying the admin password change."""
    password = 'TestAdmin123!' if role == 'admin' else 'TestDemo123!'
    response = await client.post('/api/auth/login', json={
        'email': f'{role}@ketsip.local', 'password': password,
    })
    assert response.status_code == 200, response.text
    token = response.json()['token']
    if role == 'admin':
        response = await client.put('/api/profile/password',
            headers={'Authorization': f'Bearer {token}'},
            json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
        assert response.status_code == 200, response.text
        token = response.json()['token']
    return {'Authorization': f'Bearer {token}'}


async def test_inventory_lifecycle_propagates_to_portfolio_dashboard_reports_and_audit(client):
    """Follow successful and rejected writes through scoped, persisted read models."""
    db = app.state.db
    admin = await login(client, 'admin')
    leader = await login(client, 'leader')
    readonly = await login(client, 'readonly')
    own = await db.portfolios.find_one({'name': 'Payments'})
    other = await db.portfolios.find_one({'name': 'Customer Platform'})
    own_id, other_id = str(own['_id']), str(other['_id'])
    portfolio_path = f'/api/portfolios/{own_id}'
    payload = {
        'name': 'Cross feature inventory', 'portfolioId': own_id,
        'productArea': 'Integration only', 'qualityScore': 25,
        'applicationHealthScore': 50, 'automationCoverage': 10,
        'openCriticalDefects': 1, 'riskLevel': 'Low',
    }

    baseline = await client.get(portfolio_path, headers=leader)
    assert baseline.status_code == 200
    assert (baseline.json()['applicationCount'], baseline.json()['qualityScore']) == (3, 82)
    created = await client.post('/api/applications', headers=leader, json=payload)
    assert created.status_code == 201, created.text
    identifier = created.json()['id']
    app_path = f'/api/applications/{identifier}'
    stored = await db.applications.find_one({'_id': ObjectId(identifier)})
    assert all(stored[key] == value for key, value in payload.items())
    summary = await client.get(portfolio_path, headers=leader)
    assert summary.status_code == 200
    assert (summary.json()['applicationCount'], summary.json()['qualityScore']) == (4, 68)

    payload.update(qualityScore=90, applicationHealthScore=80, automationCoverage=70,
                   openCriticalDefects=3, riskLevel='High')
    updated = await client.put(app_path, headers=leader, json=payload)
    assert updated.status_code == 200, updated.text
    stored = await db.applications.find_one({'_id': ObjectId(identifier)})
    assert all(stored[key] == value for key, value in payload.items())
    summary = await client.get(portfolio_path, headers=leader)
    assert summary.status_code == 200
    assert (summary.json()['applicationCount'], summary.json()['qualityScore']) == (4, 84)
    linked = await client.get(portfolio_path + '/applications', headers=leader)
    assert linked.status_code == 200 and linked.json()['total'] == 4
    assert [row['qualityScore'] for row in linked.json()['items'] if row['id'] == identifier] == [90]

    params = {'portfolioId': own_id, 'productArea': 'Integration only', 'riskLevel': 'High'}
    dashboard = await client.get('/api/dashboard/executive', headers=leader, params=params)
    assert dashboard.status_code == 200
    assert dashboard.json() == {
        'enterpriseQualityScore': 90, 'applicationHealthScore': 80,
        'automationMaturityScore': 70, 'openCriticalDefects': 3,
        'applicationsAtRisk': 1, 'totalApplications': 1, 'totalPortfolios': 1,
        'portfolios': [{'portfolioId': own_id, 'name': 'Payments', 'applicationCount': 1,
                        'qualityScore': 90, 'applicationsAtRisk': 1}],
    }
    report_params = {'search': payload['name'], 'portfolioId': own_id, 'riskLevel': 'High'}
    report = await client.get('/api/reports/applications', headers=leader, params=report_params)
    assert report.status_code == 200 and report.json()['total'] == 1
    row = report.json()['items'][0]
    assert row['id'] == identifier and row['portfolioId'] == own_id and row['qualityScore'] == 90
    exported = await client.get('/api/reports/applications', headers=leader,
                                params={**report_params, 'format': 'csv'})
    assert exported.status_code == 200 and exported.headers['content-type'].startswith('text/csv')
    rows = list(csv.DictReader(io.StringIO(exported.text, newline='')))
    assert len(rows) == 1
    assert {key: rows[0][key] for key in ('id', 'name', 'portfolioId', 'qualityScore', 'riskLevel')} == {
        'id': identifier, 'name': payload['name'], 'portfolioId': own_id,
        'qualityScore': '90', 'riskLevel': 'High',
    }
    assert await db.audit_logs.count_documents({'action': 'export', 'entityType': 'application report'}) == 1

    # Denials and invalid upstream writes must leave both inventory and audit unchanged.
    before_events = await db.audit_logs.count_documents({})
    before_count = await db.applications.count_documents({})
    assert (await client.post('/api/applications', headers=leader, json=payload)).status_code == 409
    assert (await client.post('/api/applications', headers=admin, json={**payload, 'name': 'Missing destination', 'portfolioId': str(ObjectId())})).status_code == 409
    assert (await client.put(app_path, headers=leader, json={**payload, 'qualityScore': 101})).status_code == 422
    assert (await client.put(app_path, headers=leader, json={**payload, 'portfolioId': other_id})).status_code == 403
    assert (await client.post('/api/applications', headers=leader, json={**payload, 'name': 'Out of scope', 'portfolioId': other_id})).status_code == 403
    assert (await client.delete(app_path, headers=leader)).status_code == 403
    assert (await client.delete(portfolio_path, headers=admin)).status_code == 409
    assert (await client.get('/api/dashboard/executive', headers=leader, params={'portfolioId': other_id})).status_code == 403
    assert (await client.get('/api/reports/applications', headers=leader, params={'portfolioId': other_id})).status_code == 403
    assert (await client.get('/api/audit-logs', headers=leader)).status_code == 403
    assert (await client.get('/api/reports/applications', headers=readonly, params={**report_params, 'format': 'csv'})).status_code == 403
    assert await db.applications.find_one({'_id': ObjectId(identifier)}) == stored
    assert await db.applications.count_documents({}) == before_count
    assert await db.applications.find_one({'name': {'$in': ['Missing destination', 'Out of scope']}}) is None
    assert await db.portfolios.find_one({'_id': own['_id'], 'deleting': True}) is None
    assert await db.audit_logs.count_documents({}) == before_events

    deleted = await client.delete(app_path, headers=admin)
    assert deleted.status_code == 204
    assert await db.applications.find_one({'_id': ObjectId(identifier)}) is None
    assert (await client.get(app_path, headers=leader)).status_code == 404
    summary = await client.get(portfolio_path, headers=leader)
    assert summary.status_code == 200
    assert (summary.json()['applicationCount'], summary.json()['qualityScore']) == (3, 82)
    linked = await client.get(portfolio_path + '/applications', headers=leader)
    assert linked.status_code == 200 and linked.json()['total'] == 3
    assert all(row['id'] != identifier for row in linked.json()['items'])
    dashboard = await client.get('/api/dashboard/executive', headers=leader, params=params)
    assert dashboard.status_code == 200
    assert dashboard.json() == {'enterpriseQualityScore': None, 'applicationHealthScore': None,
        'automationMaturityScore': None, 'openCriticalDefects': 0, 'applicationsAtRisk': 0,
        'totalApplications': 0, 'totalPortfolios': 0, 'portfolios': []}
    report = await client.get('/api/reports/applications', headers=leader, params=report_params)
    assert report.status_code == 200 and report.json()['total'] == 0 and report.json()['items'] == []
    exported = await client.get('/api/reports/applications', headers=leader,
                                params={**report_params, 'format': 'csv'})
    assert exported.status_code == 200 and list(csv.DictReader(io.StringIO(exported.text))) == []
    events = await db.audit_logs.find({'entityType': 'application', 'entityId': identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit', 'delete']
    audit = await client.get('/api/audit-logs', headers=admin, params={'action': 'delete'})
    assert audit.status_code == 200
    assert [event['entityId'] for event in audit.json()['items'] if event['entityType'] == 'application'] == [identifier]


async def test_portfolio_lifecycle_in_dashboard_reports_audit_and_scope(client):
    """Propagate a portfolio's creation, rename and deletion across read models."""
    db = app.state.db
    admin = await login(client, 'admin')
    leader = await login(client, 'leader')
    readonly = await login(client, 'readonly')
    portfolio = {'name': 'Integration portfolio', 'owner': 'Team A', 'productArea': 'Cross portfolio', 'status': 'Active'}
    created = await client.post('/api/portfolios', headers=admin, json=portfolio)
    assert created.status_code == 201
    identifier = created.json()['id']
    path = '/api/portfolios/' + identifier
    assert (await client.get(path, headers=leader)).status_code == 403
    scoped_report = await client.get('/api/reports/portfolios', headers=leader, params={'search': portfolio['name']})
    assert scoped_report.status_code == 200 and scoped_report.json()['total'] == 0
    created_report = await client.get('/api/reports/portfolios', headers=admin, params={'search': portfolio['name']})
    assert created_report.status_code == 200 and created_report.json()['total'] == 1
    assert created_report.json()['items'][0]['id'] == identifier and created_report.json()['items'][0]['applicationCount'] == 0
    created_csv = await client.get('/api/reports/portfolios', headers=admin, params={'search': portfolio['name'], 'format': 'csv'})
    assert created_csv.status_code == 200
    assert [row['id'] for row in csv.DictReader(io.StringIO(created_csv.text))] == [identifier]
    application = await client.post('/api/applications', headers=admin, json={'name': 'Portfolio integration app', 'portfolioId': identifier, 'productArea': 'Cross portfolio', 'qualityScore': 73, 'riskLevel': 'High'})
    assert application.status_code == 201
    app_id = application.json()['id']
    portfolio.update(name='Renamed integration portfolio', owner='Team B', status='Archived')
    updated = await client.put(path, headers=admin, json=portfolio)
    assert updated.status_code == 200
    stored = await db.portfolios.find_one({'_id': ObjectId(identifier)})
    assert all(stored[key] == value for key, value in portfolio.items())
    dash = await client.get('/api/dashboard/executive', headers=admin, params={'portfolioId': identifier})
    assert dash.status_code == 200
    assert dash.json()['portfolios'] == [{'portfolioId': identifier, 'name': portfolio['name'], 'applicationCount': 1, 'qualityScore': 73, 'applicationsAtRisk': 1}]
    params = {'search': portfolio['name']}
    report = await client.get('/api/reports/portfolios', headers=admin, params=params)
    assert report.status_code == 200 and report.json()['total'] == 1
    assert {k: report.json()['items'][0][k] for k in ('id', 'name', 'owner', 'status', 'applicationCount', 'qualityScore')} == {'id': identifier, 'name': portfolio['name'], 'owner': 'Team B', 'status': 'Archived', 'applicationCount': 1, 'qualityScore': 73}
    exported = await client.get('/api/reports/portfolios', headers=admin, params={**params, 'format': 'csv'})
    assert exported.status_code == 200 and exported.headers['content-type'].startswith('text/csv')
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 1 and {k: rows[0][k] for k in ('id', 'name', 'owner', 'status', 'applicationCount', 'qualityScore')} == {'id': identifier, 'name': portfolio['name'], 'owner': 'Team B', 'status': 'Archived', 'applicationCount': '1', 'qualityScore': '73'}
    events_before = await db.audit_logs.count_documents({})
    assert (await client.put(path, headers=leader, json=portfolio)).status_code == 403
    assert (await client.get('/api/dashboard/executive', headers=leader, params={'portfolioId': identifier})).status_code == 403
    assert (await client.get('/api/reports/portfolios', headers=readonly, params={**params, 'format': 'csv'})).status_code == 403
    assert (await client.delete(path, headers=admin)).status_code == 409
    assert await db.audit_logs.count_documents({}) == events_before
    assert (await client.delete('/api/applications/' + app_id, headers=admin)).status_code == 204
    assert (await client.delete(path, headers=admin)).status_code == 204
    assert await db.portfolios.find_one({'_id': ObjectId(identifier)}) is None
    assert await db.applications.find_one({'_id': ObjectId(app_id)}) is None
    dash = await client.get('/api/dashboard/executive', headers=admin, params={'portfolioId': identifier})
    assert dash.status_code == 200 and dash.json()['totalApplications'] == 0 and dash.json()['portfolios'] == []
    report = await client.get('/api/reports/portfolios', headers=admin, params=params)
    assert report.status_code == 200 and report.json()['items'] == []
    exported = await client.get('/api/reports/portfolios', headers=admin, params={**params, 'format': 'csv'})
    assert exported.status_code == 200 and list(csv.DictReader(io.StringIO(exported.text))) == []
    events = await db.audit_logs.find({'entityType': 'portfolio', 'entityId': identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit', 'delete']
    audit = await client.get('/api/audit-logs', headers=admin)
    assert audit.status_code == 200
    assert {event['action'] for event in audit.json()['items'] if event['entityType'] == 'portfolio' and event['entityId'] == identifier} == {'create', 'edit', 'delete'}


async def test_admin_assignment_and_permission_changes_propagate_to_sessions_and_reports(client):
    """API-managed scope and export restrictions apply to old and fresh sessions."""
    db = app.state.db
    admin = await login(client, 'admin')
    existing = await login(client, 'leader')
    users = await client.get('/api/users', headers=admin)
    roles = await client.get('/api/roles', headers=admin)
    portfolios = await client.get('/api/portfolios', headers=admin)
    assert users.status_code == roles.status_code == portfolios.status_code == 200
    leader = next(item for item in users.json()['items'] if item['email'] == 'leader@ketsip.local')
    role = next(item for item in roles.json()['items'] if item['name'] == 'Portfolio Leader')
    own = next(item for item in portfolios.json()['items'] if item['name'] == 'Payments')
    other = next(item for item in portfolios.json()['items'] if item['name'] == 'Customer Platform')
    own_id, other_id = own['id'], other['id']
    baseline = await client.get('/api/dashboard/executive', headers=existing)
    assert baseline.status_code == 200 and [p['portfolioId'] for p in baseline.json()['portfolios']] == [own_id]

    user_fields = {key: leader[key] for key in ('name', 'email', 'role', 'status', 'managerName', 'vendorIndicator')}
    changed = await client.put('/api/users/' + leader['id'], headers=admin,
                               json={**user_fields, 'portfolioAccess': [other_id], 'password': None})
    assert changed.status_code == 200 and changed.json()['portfolioAccess'] == [other_id]
    stored_user = await db.users.find_one({'_id': ObjectId(leader['id'])})
    assert stored_user['portfolioAccess'] == [other_id]
    refreshed = await login(client, 'leader')
    for session in (existing, refreshed):
        me = await client.get('/api/auth/me', headers=session)
        assert me.status_code == 200 and me.json()['portfolioAccess'] == [other_id]
        assert (await client.get('/api/portfolios/' + own_id, headers=session)).status_code == 403
        visible = await client.get('/api/portfolios', headers=session)
        assert visible.status_code == 200 and [p['id'] for p in visible.json()['items']] == [other_id]
        dash = await client.get('/api/dashboard/executive', headers=session)
        assert dash.status_code == 200 and dash.json()['totalApplications'] == 4
        assert [p['portfolioId'] for p in dash.json()['portfolios']] == [other_id]
        assert (await client.get('/api/dashboard/executive', headers=session, params={'portfolioId': own_id})).status_code == 403
        apps = await client.get('/api/reports/applications', headers=session)
        assert apps.status_code == 200 and apps.json()['total'] == 4
        assert {item['portfolioId'] for item in apps.json()['items']} == {other_id}
        assert (await client.get('/api/reports/applications', headers=session, params={'portfolioId': own_id})).status_code == 403
        report = await client.get('/api/reports/portfolios', headers=session)
        assert report.status_code == 200 and [item['id'] for item in report.json()['items']] == [other_id]

    role_fields = {'name': role['name'], 'description': role['description'],
                   'permissions': [permission for permission in role['permissions'] if permission != 'export']}
    changed = await client.put('/api/roles/' + role['id'], headers=admin, json=role_fields)
    assert changed.status_code == 200 and changed.json()['permissions'] == role_fields['permissions']
    assert (await db.roles.find_one({'_id': ObjectId(role['id'])}))['permissions'] == role_fields['permissions']
    refreshed_after_restriction = await login(client, 'leader')
    inventory_before = await db.applications.find({}).sort('_id', 1).to_list(None)
    portfolios_before = await db.portfolios.find({}).sort('_id', 1).to_list(None)
    audit_before = await db.audit_logs.find({}).sort('_id', 1).to_list(None)
    for session in (existing, refreshed, refreshed_after_restriction):
        assert (await client.get('/api/auth/me', headers=session)).status_code == 200
        dash = await client.get('/api/dashboard/executive', headers=session)
        assert dash.status_code == 200 and dash.json()['totalApplications'] == 4
        assert [p['portfolioId'] for p in dash.json()['portfolios']] == [other_id]
        for path, expected in (('/api/reports/applications', 4), ('/api/reports/portfolios', 1)):
            report = await client.get(path, headers=session)
            assert report.status_code == 200 and report.json()['total'] == expected
            assert (await client.get(path, headers=session, params={'format': 'csv'})).status_code == 403
    assert await db.applications.find({}).sort('_id', 1).to_list(None) == inventory_before
    assert await db.portfolios.find({}).sort('_id', 1).to_list(None) == portfolios_before
    assert await db.audit_logs.find({}).sort('_id', 1).to_list(None) == audit_before
    user_events = await db.audit_logs.find({'entityType': 'user', 'entityId': leader['id']}).to_list(None)
    role_events = await db.audit_logs.find({'entityType': 'role', 'entityId': role['id']}).to_list(None)
    assert [event['action'] for event in user_events] == ['login', 'edit', 'login', 'login']
    assert [event['action'] for event in role_events] == ['edit', 'permissionChange']
    assert (await db.users.find_one({'_id': ObjectId(leader['id'])}))['portfolioAccess'] == [other_id]
