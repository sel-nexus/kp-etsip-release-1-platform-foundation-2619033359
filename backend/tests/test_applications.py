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
    assert result.status_code == 200
    token = result.json()['token']
    if role == 'admin':
        result = await client.put('/api/profile/password', headers={'Authorization': f'Bearer {token}'}, json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
        assert result.status_code == 200
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
    _response = await client.get('/api/applications', headers=auth, params={'search': '.*'})
    assert _response.status_code == 200
    assert (_response).json()['total'] == 0
    exported = await client.get('/api/applications/export', headers=auth, params={'portfolioId': str(payment['_id']), 'search': 'gateway'})
    assert exported.status_code == 200 and 'Payment Gateway' in exported.text and 'Member Portal' not in exported.text
    assert await db.audit_logs.count_documents({'entityType': 'application', 'action': 'export'}) == 1
    readonly = await login(client, 'readonly')
    assert (await client.get('/api/applications/export', headers=readonly)).status_code == 403
    _response = await client.get('/api/applications', headers=auth, params={'limit': 2, 'offset': 1})
    assert _response.status_code == 200
    assert len((_response).json()['items']) == 2
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
    stored = await app.state.db.applications.find_one({'_id': ObjectId(identifier)})
    assert stored['name'] == payload['name'] and stored['portfolioId'] == payload['portfolioId']
    assert (await client.post('/api/applications', headers=engineer, json=payload)).status_code == 409
    assert await app.state.db.applications.count_documents({'name': payload['name']}) == 1
    upper = await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Uppercase id', 'portfolioId': str(portfolio['_id']).upper()})
    assert upper.status_code == 201 and upper.json()['portfolioId'] == str(portfolio['_id'])
    for change in ({'name': ' '}, {'tier': 0}, {'tier': 5}, {'tier': 1.5}, {'qualityScore': 101}, {'unitTestCoverage': -1}, {'openDefects': -1}, {'repositoryLink': 'javascript:alert(1)'}, {'criticality': 'Severe'}, {'riskLevel': 'Critical'}, {'lifecycleStatus': 'Archived'}, {'portfolioId': 'bad'}):
        expected = 404 if change == {'portfolioId': 'bad'} else 422
        assert (await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Other', **change})).status_code == expected
    assert (await client.post('/api/applications', headers=engineer, json={**payload, 'name': 'Other', 'portfolioId': str(ObjectId())})).status_code == 409
    update = await client.put('/api/applications/' + identifier, headers=engineer, json={**payload, 'name': 'Changed', 'technologyOwner': 'Engineering'})
    assert update.status_code == 200 and update.json()['technologyOwner'] == 'Engineering'
    assert (await app.state.db.applications.find_one({'_id': ObjectId(identifier)}))['name'] == 'Changed'
    _response = await client.get('/api/applications/' + identifier, headers=engineer)
    assert _response.status_code == 200
    assert (_response).json()['name'] == 'Changed'
    assert (await client.delete('/api/applications/' + identifier, headers=engineer)).status_code == 403
    assert (await client.delete('/api/applications/' + identifier, headers=admin)).status_code == 204
    assert (await client.get('/api/applications/' + identifier, headers=engineer)).status_code == 404
    assert await app.state.db.applications.find_one({'_id': ObjectId(identifier)}) is None
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
    _response = await client.get('/api/applications', headers=leader)
    assert _response.status_code == 200
    visible = (_response).json()
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
        _response = await client.get('/api/applications', headers=auth)
        assert _response.status_code == 200
        assert (_response).json()['total'] == 10
        assert (await client.post('/api/applications', headers=auth, json={'name': 'Denied', 'portfolioId': own_id})).status_code == 403
    await db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['view']}})
    engineer = await login(client)
    _response = await client.get('/api/applications/capabilities', headers=engineer)
    assert _response.status_code == 200
    assert (_response).json()['edit'] is False
    assert (await client.put('/api/applications/' + own_app['id'], headers=engineer, json=payload)).status_code == 403
    await db.users.update_one({'email': 'leader@ketsip.local'}, {'$set': {'portfolioAccess': []}})
    _response = await client.get('/api/applications', headers=leader)
    assert _response.status_code == 200
    assert (_response).json()['total'] == 0
    _response = await client.get('/api/applications', headers=admin)
    assert _response.status_code == 200
    assert (_response).json()['total'] == 10


async def test_cross_process_coordination_and_transfer_races(client):
    """Competing MongoDB operations cannot delete a reserved destination."""
    admin = await login(client, 'admin')
    db = app.state.db
    app_repo = ApplicationRepository(db)
    portfolio_repo = PortfolioRepository(db)
    created = await client.post('/api/portfolios', headers=admin, json={'name': 'Race Destination'})
    assert created.status_code == 201
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
        assert created.status_code == 201
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
    assert created.status_code == 201
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


async def test_required_fields_types_lengths_and_missing_resources(client):
    """Reject invalid writes and missing resources without modifying inventory."""
    auth = await login(client, 'admin')
    db = app.state.db
    portfolio = await db.portfolios.find_one({'name': 'Payments'})
    valid = {'name': 'Validation test', 'portfolioId': str(portfolio['_id'])}
    initial = await db.applications.count_documents({})
    for payload in ({}, {'portfolioId': valid['portfolioId']}, {'name': valid['name']},
                    {**valid, 'name': ''}, {**valid, 'name': 'x' * 201},
                    {**valid, 'description': 'x' * 4001}, {**valid, 'name': {'$ne': ''}},
                    {**valid, 'portfolioId': {'$ne': ''}}, {**valid, 'tier': '1'},
                    {**valid, 'qualityScore': True}, {**valid, 'unexpected': 'x'}):
        result = await client.post('/api/applications', headers=auth, json=payload)
        assert result.status_code == 422, (payload, result.text)
    for identifier in ('invalid', str(ObjectId())):
        path = '/api/applications/' + identifier
        assert (await client.get(path, headers=auth)).status_code == 404
        assert (await client.put(path, headers=auth, json=valid)).status_code == 404
        assert (await client.delete(path, headers=auth)).status_code == 404
    assert await db.applications.count_documents({}) == initial
    assert await db.applications.find_one({'name': valid['name']}) is None


async def test_literal_injection_and_stored_markup_remain_data(client):
    """Preserve stored markup as JSON data and treat regex and operators literally."""
    auth = await login(client)
    db = app.state.db
    portfolio = await db.portfolios.find_one({'name': 'Payments'})
    markup = '<img src=x onerror=alert(1)>'
    payload = {'name': 'Literal .* name', 'portfolioId': str(portfolio['_id']), 'description': markup}
    created = await client.post('/api/applications', headers=auth, json=payload)
    assert created.status_code == 201
    identifier = created.json()['id']
    stored = await db.applications.find_one({'_id': ObjectId(identifier)})
    assert stored['description'] == markup
    read = await client.get('/api/applications/' + identifier, headers=auth)
    assert read.status_code == 200 and read.headers['content-type'].startswith('application/json')
    assert read.json()['description'] == markup
    search = await client.get('/api/applications', headers=auth, params={'search': '.*'})
    assert search.status_code == 200 and [x['id'] for x in search.json()['items']] == [identifier]
    rejected = await client.post('/api/applications', headers=auth, json={**payload, 'name': {'$ne': None}})
    assert rejected.status_code == 422
    assert await db.applications.count_documents({'name': 'Literal .* name'}) == 1


async def test_api_inventory_dashboard_portfolio_reports_and_audit_integration(client):
    """Trace real writes through scoped read models, reports, and audit history."""
    db = app.state.db
    admin = await login(client, 'admin')
    leader = await login(client, 'leader')
    own = await db.portfolios.find_one({'name': 'Payments'})
    other = await db.portfolios.find_one({'name': 'Customer Platform'})
    own_id, other_id = str(own['_id']), str(other['_id'])
    payload = {'name': 'Integration application', 'portfolioId': own_id, 'productArea': 'Integration area', 'qualityScore': 25, 'applicationHealthScore': 50, 'automationCoverage': 10, 'openCriticalDefects': 1, 'riskLevel': 'Low'}
    created = await client.post('/api/applications', headers=leader, json=payload)
    assert created.status_code == 201
    identifier = created.json()['id']
    payload.update(qualityScore=90, applicationHealthScore=80, automationCoverage=70, openCriticalDefects=3, riskLevel='High')
    updated = await client.put('/api/applications/' + identifier, headers=leader, json=payload)
    assert updated.status_code == 200 and updated.json()['qualityScore'] == 90
    stored = await db.applications.find_one({'_id': ObjectId(identifier)})
    assert all(stored[key] == payload[key] for key in payload)
    dashboard = await client.get('/api/dashboard/executive', headers=leader, params={'productArea': 'Integration area'})
    assert dashboard.status_code == 200
    metrics = dashboard.json()
    assert (metrics['enterpriseQualityScore'], metrics['applicationHealthScore'], metrics['automationMaturityScore'], metrics['openCriticalDefects'], metrics['applicationsAtRisk'], metrics['totalApplications']) == (90, 80, 70, 3, 1, 1)
    assert metrics['portfolios'][0]['portfolioId'] == own_id
    detail = await client.get('/api/portfolios/' + own_id, headers=leader)
    assert detail.status_code == 200
    docs = await db.applications.find({'portfolioId': own_id}).to_list(None)
    assert detail.json()['applicationCount'] == len(docs)
    assert detail.json()['qualityScore'] == (sum(d['qualityScore'] for d in docs) * 2 + len(docs)) // (2 * len(docs))
    linked = await client.get('/api/portfolios/' + own_id + '/applications', headers=leader)
    assert linked.status_code == 200 and any(item['id'] == identifier for item in linked.json()['items'])
    report = await client.get('/api/reports/applications', headers=leader, params={'search': 'Integration application'})
    assert report.status_code == 200 and report.json()['items'][0]['qualityScore'] == 90
    portfolios = await client.get('/api/reports/portfolios', headers=leader)
    assert portfolios.status_code == 200 and [row['id'] for row in portfolios.json()['items']] == [own_id]
    exported = await client.get('/api/reports/applications', headers=leader, params={'search': 'Integration application', 'format': 'csv'})
    assert exported.status_code == 200 and 'Integration application' in exported.text
    audit = await client.get('/api/audit-logs', headers=admin)
    assert audit.status_code == 200
    events = await db.audit_logs.find({'entityType': 'application', 'entityId': identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit']
    assert {event['action'] for event in audit.json()['items'] if event['entityId'] == identifier} == {'create', 'edit'}
    assert await db.audit_logs.count_documents({'action': 'export', 'entityType': 'application report'}) == 1
    before_events = await db.audit_logs.count_documents({})
    assert (await client.put('/api/applications/' + identifier, headers=leader, json={**payload, 'portfolioId': other_id})).status_code == 403
    assert (await client.post('/api/applications', headers=leader, json={**payload, 'name': 'Denied integration', 'portfolioId': other_id})).status_code == 403
    assert (await client.get('/api/dashboard/executive', headers=leader, params={'portfolioId': other_id})).status_code == 403
    assert (await client.get('/api/reports/applications', headers=leader, params={'portfolioId': other_id})).status_code == 403
    assert await db.applications.find_one({'_id': ObjectId(identifier)}) == stored
    assert await db.applications.find_one({'name': 'Denied integration'}) is None
    assert await db.audit_logs.count_documents({}) == before_events


async def test_concurrent_application_move_detects_stale_update(client, monkeypatch):
    """A stale update cannot overwrite an application moved to another portfolio."""
    auth = await login(client, 'admin')
    db = app.state.db
    source = await db.applications.find_one({'name': 'Payment Gateway'})
    destination = await db.portfolios.find_one({'name': 'Customer Platform'})
    original_update = ApplicationRepository.update
    async def move_before_update(self, identifier, previous_portfolio, fields):
        """Make a competing real database move before the guarded update."""
        await self.db.applications.update_one({'_id': identifier}, {'$set': {'portfolioId': str(destination['_id'])}})
        return await original_update(self, identifier, previous_portfolio, fields)
    monkeypatch.setattr(ApplicationRepository, 'update', move_before_update)
    payload = {key: value for key, value in source.items() if key not in ('_id', 'createdAt', 'updatedAt')}
    result = await client.put('/api/applications/' + str(source['_id']), headers=auth, json={**payload, 'name': 'Stale overwrite'})
    assert result.status_code == 409
    stored = await db.applications.find_one({'_id': source['_id']})
    assert stored['portfolioId'] == str(destination['_id']) and stored['name'] == source['name']
    assert await db.audit_logs.count_documents({'entityType': 'application', 'entityId': str(source['_id']), 'action': 'edit'}) == 0
    portfolio = await db.portfolios.find_one({'_id': ObjectId(source['portfolioId'])})
    assert not portfolio.get('applicationReservations')


async def test_capabilities_reflect_permissions_and_reject_anonymous(client):
    """Report effective capabilities before and after role restriction."""
    assert (await client.get('/api/applications/capabilities')).status_code == 401
    auth = await login(client)
    response = await client.get('/api/applications/capabilities', headers=auth)
    assert response.status_code == 200
    assert response.json() == {'view': True, 'create': True, 'edit': True, 'delete': False, 'export': True}
    await app.state.db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['view']}})
    response = await client.get('/api/applications/capabilities', headers=auth)
    assert response.status_code == 200
    assert response.json() == {'view': True, 'create': False, 'edit': False, 'delete': False, 'export': False}
    await app.state.db.roles.delete_one({'name': 'Engineer'})
    response = await client.get('/api/applications/capabilities', headers=auth)
    assert response.status_code == 200 and not any(response.json().values())


async def test_duplicate_application_name_update_preserves_both_records(client):
    """The unique name index protects existing applications on update."""
    auth = await login(client)
    db = app.state.db
    first = await db.applications.find_one({'name': 'Payment Gateway'})
    second = await db.applications.find_one({'_id': {'$ne': first['_id']}})
    payload = {key: value for key, value in second.items() if key not in ('_id', 'createdAt', 'updatedAt')}
    result = await client.put('/api/applications/' + str(second['_id']), headers=auth, json={**payload, 'name': first['name']})
    assert result.status_code == 409
    assert await db.applications.find_one({'_id': first['_id']}) == first
    assert await db.applications.find_one({'_id': second['_id']}) == second


async def test_application_field_matrix_create_and_update(client):
    """Enforce schema bounds, types and nullability on both writes without side effects."""
    auth = await login(client)
    db = app.state.db
    portfolio = await db.portfolios.find_one({'name': 'Payments'})
    base = {'name': 'Matrix application', 'portfolioId': str(portfolio['_id'])}
    response = await client.post('/api/applications', headers=auth, json=base)
    assert response.status_code == 201
    identifier = response.json()['id']
    before = await db.applications.find({}).sort('_id', 1).to_list(None)
    events = await db.audit_logs.count_documents({})
    invalid = [{k: v for k, v in base.items() if k != key} for key in ('name', 'portfolioId')]
    invalid += [{**base, 'name': ''}, {**base, 'name': ' '}, {**base, 'portfolioId': ''}, {**base, 'extra': 1}]
    for key, maximum in [('name', 200), ('description', 4000), ('productArea', 200), ('businessOwner', 200), ('technologyOwner', 200), ('etsOwner', 200), ('technologyStack', 4000)]:
        invalid += [{**base, key: value} for value in (None, {}, True, 'x' * (maximum + 1))]
    invalid += [{**base, 'portfolioId': value} for value in (None, {}, True)]
    for key in ('criticality', 'lifecycleStatus', 'riskLevel'):
        invalid += [{**base, key: value} for value in (None, {}, '', 'Invalid')]
    for key in ('tier', 'applicationHealthScore', 'qualityScore', 'automationCoverage', 'unitTestCoverage', 'openDefects', 'openCriticalDefects'):
        values = [None, {}, True, '1', 1.5, -1]
        if key == 'tier': values += [0, 5]
        if key in ('applicationHealthScore', 'qualityScore', 'automationCoverage', 'unitTestCoverage'): values += [101]
        invalid += [{**base, key: value} for value in values]
    for key in ('repositoryLink', 'pipelineLink'):
        invalid += [{**base, key: value} for value in ({}, True, 'javascript:alert(1)', 'not a url')]
    for body in invalid:
        for method, path in [('post', '/api/applications'), ('put', '/api/applications/' + identifier)]:
            result = await getattr(client, method)(path, headers=auth, json=body)
            assert result.status_code == 422, (method, body, result.text)
            assert await db.applications.find({}).sort('_id', 1).to_list(None) == before
            assert await db.audit_logs.count_documents({}) == events
    limits = {**base, 'name': 'n' * 200, 'description': 'd' * 4000, 'productArea': 'p' * 200,
              'businessOwner': 'b' * 200, 'technologyOwner': 't' * 200, 'etsOwner': 'e' * 200,
              'technologyStack': 's' * 4000, 'tier': 4, 'applicationHealthScore': 100,
              'qualityScore': 100, 'automationCoverage': 100, 'unitTestCoverage': 100,
              'openDefects': 0, 'openCriticalDefects': 0, 'repositoryLink': None, 'pipelineLink': ''}
    for method, path in [('put', '/api/applications/' + identifier), ('post', '/api/applications')]:
        if method == 'post': limits['name'] = 'c' * 200
        result = await getattr(client, method)(path, headers=auth, json=limits)
        assert result.status_code == (200 if method == 'put' else 201), result.text
        stored = await db.applications.find_one({'_id': ObjectId(result.json()['id'])})
        assert all(stored[key] == (None if key == 'pipelineLink' else value) for key, value in limits.items())
