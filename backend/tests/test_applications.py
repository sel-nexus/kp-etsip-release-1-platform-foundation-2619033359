"""Exercise application inventory and portfolio coordination against real MongoDB."""
import asyncio
import os
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from bson import ObjectId
from pymongo.errors import AutoReconnect

os.environ.setdefault("JWT_SECRET", "test-only-unique-secret-for-application-tests")
from app.main import app
from app.core.config import get_settings
from app.core.seed import seed_database
from app.applications.repository import ApplicationRepository
from app.portfolios.repository import PortfolioRepository


@pytest.fixture
async def client(monkeypatch):
    """Start the API with an isolated, disposable MongoDB database."""
    values = {"JWT_SECRET": "test-only-unique-secret-for-application-tests", "MONGODB_URI": os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017"), "MONGODB_DB": "application_test_" + uuid4().hex, "SEED_ON_STARTUP": "true", "ADMIN_INITIAL_PASSWORD": "TestAdmin123!", "DEMO_INITIAL_PASSWORD": "TestDemo123!"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        async with app.router.lifespan_context(app):
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
                    yield http
            finally:
                await app.state.db.client.drop_database(values["MONGODB_DB"])
    finally:
        get_settings.cache_clear()


async def login(client, role="engineer"):
    """Authenticate one of the seeded accounts."""
    password = "TestAdmin123!" if role == "admin" else "TestDemo123!"
    result = await client.post('/api/auth/login', json={'email': f'{role}@ketsip.local', 'password': password})
    token = result.json()['token']
    if role == 'admin':
        result = await client.put('/api/profile/password', headers={'Authorization': f'Bearer {token}'}, json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
        token = result.json()['token']
    return {'Authorization': f'Bearer {token}'}


async def test_seed_search_filters_and_pagination(client):
    """Seed idempotently and filter only matching persisted records."""
    db = app.state.db
    await seed_database(db, get_settings())
    assert await db.applications.count_documents({}) == 10
    assert len(await db.applications.distinct('portfolioId')) == 3
    assert (await client.get('/api/applications')).status_code == 401
    auth = await login(client)
    payment = await db.portfolios.find_one({'name': 'Payments'})
    portfolios = await client.get('/api/portfolios', headers=auth)
    assert portfolios.status_code == 200 and len(portfolios.json()['items']) == 3
    assert all('applicationReservations' not in item and 'deleting' not in item for item in portfolios.json()['items'])
    result = await client.get('/api/applications', headers=auth, params={'portfolioId': str(payment['_id']), 'search': 'gateway', 'criticality': 'High', 'riskLevel': 'Medium', 'lifecycleStatus': 'Active'})
    assert result.status_code == 200 and result.json()['total'] == 1
    assert result.json()['items'][0]['name'] == 'Payment Gateway'
    assert (await client.get('/api/applications', headers=auth, params={'search': '.*'})).json()['total'] == 0
    exported = await client.get('/api/applications/export', headers=auth, params={'portfolioId': str(payment['_id']), 'search': 'gateway'})
    assert exported.status_code == 200 and 'Payment Gateway' in exported.text and 'Member Portal' not in exported.text
    assert await db.audit_logs.count_documents({'entityType': 'application', 'action': 'export'}) == 1
    readonly = await login(client, 'readonly')
    assert (await client.get('/api/applications/export', headers=readonly)).status_code == 403
    assert len((await client.get('/api/applications', headers=auth, params={'limit': 2, 'offset': 1})).json()['items']) == 2
    for params in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'criticality': 'Invalid'}, {'riskLevel': 'Critical'}, {'lifecycleStatus': 'Unknown'}):
        assert (await client.get('/api/applications', headers=auth, params=params)).status_code == 422


async def test_crud_validation_duplicate_and_audit(client):
    """Persist application changes, enforce bounds, and record successful actions."""
    engineer = await login(client)
    admin = await login(client, 'admin')
    portfolio = await app.state.db.portfolios.find_one({'name': 'Payments'})
    payload = {'name': 'New application', 'portfolioId': str(portfolio['_id']), 'tier': 4, 'applicationHealthScore': 100, 'qualityScore': 0, 'automationCoverage': 100, 'unitTestCoverage': 0, 'openDefects': 0, 'openCriticalDefects': 2, 'repositoryLink': 'https://example.com/repo', 'pipelineLink': None, 'criticality': 'Critical', 'riskLevel': 'High', 'lifecycleStatus': 'Retired'}
    result = await client.post('/api/applications', headers=engineer, json=payload)
    assert result.status_code == 201, result.text
    identifier = result.json()['id']
    assert (await client.post('/api/applications', headers=engineer, json=payload)).status_code == 409
    upper = await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Uppercase id', 'portfolioId': str(portfolio['_id']).upper()})
    assert upper.status_code == 201 and upper.json()['portfolioId'] == str(portfolio['_id'])
    for change in ({'name': ' '}, {'tier': 0}, {'tier': 5}, {'tier': 1.5}, {'qualityScore': 101}, {'unitTestCoverage': -1}, {'openDefects': -1}, {'repositoryLink': 'javascript:alert(1)'}, {'criticality': 'Severe'}, {'riskLevel': 'Critical'}, {'lifecycleStatus': 'Archived'}, {'portfolioId': 'bad'}):
        assert (await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Other', **change})).status_code in (404, 422)
    assert (await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Other', 'portfolioId': str(ObjectId())})).status_code == 409
    update = await client.put('/api/applications/' + identifier, headers=engineer, json={**payload, 'name': 'Changed', 'technologyOwner': 'Engineering'})
    assert update.status_code == 200 and update.json()['technologyOwner'] == 'Engineering'
    assert (await client.get('/api/applications/' + identifier, headers=engineer)).json()['name'] == 'Changed'
    assert (await client.delete('/api/applications/' + identifier, headers=engineer)).status_code == 403
    assert (await client.delete('/api/applications/' + identifier, headers=admin)).status_code == 204
    assert (await client.get('/api/applications/' + identifier, headers=engineer)).status_code == 404
    events = await app.state.db.audit_logs.find({'entityType': 'application', 'entityId': identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit', 'delete']


async def test_leader_scope_role_ceilings_and_permissions(client):
    """Enforce current and destination scope, role ceilings and permissions."""
    leader = await login(client, 'leader')
    admin = await login(client, 'admin')
    db = app.state.db
    own = await db.portfolios.find_one({'name': 'Payments'})
    other = await db.portfolios.find_one({'name': 'Customer Platform'})
    own_id, other_id = str(own['_id']), str(other['_id'])
    visible = (await client.get('/api/applications', headers=leader)).json()
    assert visible['total'] == 3 and all(item['portfolioId'] == own_id for item in visible['items'])
    other_app = await db.applications.find_one({'portfolioId': other_id})
    assert (await client.get('/api/applications/' + str(other_app['_id']), headers=leader)).status_code == 403
    assert (await client.get('/api/applications', headers=leader, params={'portfolioId': other_id})).status_code == 403
    assert (await client.post('/api/applications', headers=leader, json={'name': 'Denied', 'portfolioId': other_id})).status_code == 403
    own_app = visible['items'][0]
    payload = {key: value for key, value in own_app.items() if key not in ('id', 'createdAt', 'updatedAt')}
    assert (await client.put('/api/applications/' + own_app['id'], headers=leader, json={**payload, 'portfolioId': other_id})).status_code == 403
    assert (await client.delete('/api/applications/' + own_app['id'], headers=leader)).status_code == 403
    for role in ('executive', 'auditor', 'readonly'):
        auth = await login(client, role)
        assert (await client.get('/api/applications', headers=auth)).json()['total'] == 10
        assert (await client.post('/api/applications', headers=auth, json={'name': 'Denied', 'portfolioId': own_id})).status_code == 403
    await db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['view']}})
    engineer = await login(client)
    assert (await client.get('/api/applications/capabilities', headers=engineer)).json()['edit'] is False
    assert (await client.put('/api/applications/' + own_app['id'], headers=engineer, json=payload)).status_code == 403
    await db.users.update_one({'email': 'leader@ketsip.local'}, {'$set': {'portfolioAccess': []}})
    assert (await client.get('/api/applications', headers=leader)).json()['total'] == 0
    assert (await client.get('/api/applications', headers=admin)).json()['total'] == 10


async def test_cross_process_coordination_and_transfer_races(client):
    """Competing MongoDB operations cannot delete a reserved destination."""
    admin = await login(client, 'admin')
    db = app.state.db
    app_repo = ApplicationRepository(db)
    portfolio_repo = PortfolioRepository(db)
    created = await client.post('/api/portfolios', headers=admin, json={'name': 'Race Destination'})
    dest = created.json()['id']
    token = await app_repo.reserve(ObjectId(dest))
    assert token
    assert (await client.delete('/api/portfolios/' + dest, headers=admin)).status_code == 409
    await app_repo.release(ObjectId(dest), token)
    assert await portfolio_repo.begin_delete(ObjectId(dest))
    assert await app_repo.reserve(ObjectId(dest)) is None
    assert (await client.post('/api/applications', headers=admin, json={'name': 'Blocked', 'portfolioId': dest})).status_code == 409
    await portfolio_repo.cancel_delete(ObjectId(dest))
    source = await db.applications.find_one({'name': 'Payment Gateway'})
    payload = {key: value for key, value in source.items() if key not in ('_id', 'createdAt', 'updatedAt')}
    transfer, deletion = await asyncio.gather(client.put('/api/applications/' + str(source['_id']), headers=admin, json={**payload, 'portfolioId': dest}), client.delete('/api/portfolios/' + dest, headers=admin))
    assert transfer.status_code in (200, 409) and deletion.status_code in (204, 409)
    stored = await db.applications.find_one({'_id': source['_id']})
    assert await db.portfolios.find_one({'_id': ObjectId(stored['portfolioId'])}) is not None
    if transfer.status_code == 200:
        assert deletion.status_code == 409
    if deletion.status_code == 204:
        assert transfer.status_code == 409
    for number in range(10):
        created = await client.post('/api/portfolios', headers=admin, json={'name': f'Create race {number}'})
        dest = created.json()['id']
        creation, deletion = await asyncio.gather(
            client.post('/api/applications', headers=admin, json={'name': f'Concurrent {number}', 'portfolioId': dest}),
            client.delete('/api/portfolios/' + dest, headers=admin),
        )
        assert creation.status_code in (201, 409) and deletion.status_code in (204, 409)
        if creation.status_code == 201:
            assert deletion.status_code == 409
            assert await db.portfolios.find_one({'_id': ObjectId(dest)}) is not None
        if deletion.status_code == 204:
            assert creation.status_code == 409


async def test_uncertain_write_keeps_reservation(client, monkeypatch):
    """Keep the portfolio blocked when a write outcome cannot be known."""
    auth = await login(client, 'admin')
    created = await client.post('/api/portfolios', headers=auth, json={'name': 'Uncertain write'})
    identifier = created.json()['id']
    async def uncertain_create(self, fields):
        """Simulate loss of the acknowledgement after a database write."""
        await self.db.applications.insert_one({**fields, 'createdAt': 'now', 'updatedAt': 'now'})
        raise AutoReconnect('acknowledgement lost')
    monkeypatch.setattr(ApplicationRepository, 'create', uncertain_create)
    with pytest.raises(AutoReconnect):
        await client.post('/api/applications', headers=auth, json={'name': 'Uncertain', 'portfolioId': identifier})
    portfolio = await app.state.db.portfolios.find_one({'_id': ObjectId(identifier)})
    assert len(portfolio['applicationReservations']) == 1
    assert (await client.delete('/api/portfolios/' + identifier, headers=auth)).status_code == 409
    assert await app.state.db.applications.find_one({'name': 'Uncertain', 'portfolioId': identifier})
