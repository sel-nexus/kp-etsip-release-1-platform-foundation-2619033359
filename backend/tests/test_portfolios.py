"""Exercise portfolio endpoints against an isolated MongoDB database."""
import os
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("JWT_SECRET", "test-only-unique-secret-for-portfolio-tests")
from app.main import app
from app.core.config import get_settings
from app.core.seed import seed_database


@pytest.fixture
async def client(monkeypatch):
    """Run the application with a disposable real database."""
    values = {"JWT_SECRET": "test-only-unique-secret-for-portfolio-tests", "MONGODB_URI": os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017"), "MONGODB_DB": "portfolio_test_" + uuid4().hex, "SEED_ON_STARTUP": "true", "ADMIN_INITIAL_PASSWORD": "TestAdmin123!", "DEMO_INITIAL_PASSWORD": "TestDemo123!"}
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
    """Authenticate a seeded account and return its authorization header."""
    password = "TestAdmin123!" if role == "admin" else "TestDemo123!"
    response = await client.post('/api/auth/login', json={'email': f'{role}@ketsip.local', 'password': password})
    assert response.status_code == 200
    token = response.json()['token']
    if role == 'admin':
        changed = await client.put('/api/profile/password', headers={'Authorization': f'Bearer {token}'}, json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
        assert changed.status_code == 200
        token = changed.json()['token']
    return {'Authorization': f'Bearer {token}'}


async def test_seed_filter_pagination_and_validation(client):
    """Seed once, filter results, and validate list boundaries."""
    db = app.state.db
    await seed_database(db, get_settings())
    assert await db.portfolios.count_documents({}) == 3
    assert (await client.get('/api/portfolios')).status_code == 401
    auth = await login(client)
    result = await client.get('/api/portfolios', headers=auth, params={'search':'pay', 'status':'Active', 'productArea':'Payments'})
    assert result.status_code == 200 and result.json()['total'] == 1
    assert result.json()['items'][0]['name'] == 'Payments'
    assert result.json()['items'][0]['applicationCount'] == 3
    assert result.json()['items'][0]['qualityScore'] == 82
    _response = await client.get('/api/portfolios', headers=auth, params={'search':'.*'})
    assert _response.status_code == 200
    assert (_response).json()['total'] == 0
    _response = await client.get('/api/portfolios', headers=auth, params={'limit':1, 'offset':1})
    assert _response.status_code == 200
    assert len((_response).json()['items']) == 1
    for params in ({'limit':0}, {'limit':101}, {'offset':-1}, {'status':'Unknown'}):
        assert (await client.get('/api/portfolios', headers=auth, params=params)).status_code == 422


async def test_admin_crud_metrics_references_and_audit(client):
    """Persist mutations, derive metrics and reject referenced deletes."""
    auth = await login(client, 'admin')
    data = {'name':'New Portfolio', 'owner':'Owner', 'description':'Summary', 'productArea':'Area', 'status':'Active'}
    result = await client.post('/api/portfolios', headers=auth, json=data)
    assert result.status_code == 201
    identifier = result.json()['id']
    assert (await client.post('/api/portfolios', headers=auth, json=data)).status_code == 409
    assert (await client.post('/api/portfolios', headers=auth, json={**data, 'name':'  '})).status_code == 422
    assert (await client.post('/api/portfolios', headers=auth, json={**data, 'status':'Invalid'})).status_code == 422
    updated = await client.put('/api/portfolios/'+identifier, headers=auth, json={**data, 'name':'Updated'})
    assert updated.status_code == 200 and updated.json()['name'] == 'Updated'
    _response = await client.get('/api/portfolios/'+identifier, headers=auth)
    assert _response.status_code == 200
    assert (_response).json()['name'] == 'Updated'
    db = app.state.db
    await db.applications.insert_many([{'name':'One', 'portfolioId':identifier, 'qualityScore': 80}, {'name':'Two', 'portfolioId':identifier, 'qualityScore': 81}])
    _response = await client.get('/api/portfolios/'+identifier, headers=auth)
    assert _response.status_code == 200
    detail = (_response).json()
    assert detail['applicationCount'] == 2 and detail['qualityScore'] == 81
    _response = await client.get('/api/portfolios/'+identifier+'/applications', headers=auth, params={'limit':1})
    assert _response.status_code == 200
    apps = (_response).json()
    assert apps['total'] == 2 and apps['items'][0]['name'] == 'One' and 'id' in apps['items'][0]
    assert (await client.delete('/api/portfolios/'+identifier, headers=auth)).status_code == 409
    await db.applications.delete_many({'portfolioId':identifier})
    assert (await client.delete('/api/portfolios/'+identifier, headers=auth)).status_code == 204
    assert (await client.get('/api/portfolios/'+identifier, headers=auth)).status_code == 404
    assert (await client.delete('/api/portfolios/invalid', headers=auth)).status_code == 404
    events = await db.audit_logs.find({'entityType':'portfolio', 'entityId':identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit', 'delete']
    assert 'TestAdmin123!' not in str(events)


async def test_scope_role_ceiling_and_permission_restriction(client):
    """Deny out-of-scope access even when permissions are expanded."""
    leader = await login(client, 'leader')
    admin = await login(client, 'admin')
    _response = await client.get('/api/portfolios', headers=admin)
    assert _response.status_code == 200
    all_items = (_response).json()['items']
    _response = await client.get('/api/portfolios', headers=leader)
    assert _response.status_code == 200
    visible = (_response).json()['items']
    assert len(visible) == 1 and visible[0]['name'] == 'Payments'
    own = visible[0]
    other = next(item for item in all_items if item['id'] != own['id'])
    payload = {key: own[key] for key in ('name', 'owner', 'description', 'productArea', 'status')}
    assert (await client.put('/api/portfolios/'+own['id'], headers=leader, json={**payload, 'owner':'Leader'})).status_code == 200
    reread = await client.get('/api/portfolios/' + own['id'], headers=leader)
    assert reread.status_code == 200 and reread.json()['owner'] == 'Leader'
    for suffix in ('', '/applications'):
        assert (await client.get('/api/portfolios/'+other['id']+suffix, headers=leader)).status_code == 403
    assert (await client.put('/api/portfolios/'+other['id'], headers=leader, json=payload)).status_code == 403
    await app.state.db.roles.update_one({'name':'Portfolio Leader'}, {'$set':{'permissions':['view','create','edit','delete']}})
    assert (await client.post('/api/portfolios', headers=leader, json={**payload, 'name':'Forbidden'})).status_code == 403
    assert (await client.delete('/api/portfolios/'+own['id'], headers=leader)).status_code == 403
    await app.state.db.roles.update_one({'name':'Portfolio Leader'}, {'$set':{'permissions':['view']}})
    assert (await client.put('/api/portfolios/'+own['id'], headers=leader, json=payload)).status_code == 403
    await app.state.db.users.update_one({'email':'leader@ketsip.local'}, {'$set':{'portfolioAccess':[]}})
    _response = await client.get('/api/portfolios', headers=leader)
    assert _response.status_code == 200
    assert (_response).json()['total'] == 0
    assert (await client.get('/api/portfolios/'+own['id'], headers=leader)).status_code == 403
    for role in ('engineer', 'executive', 'auditor', 'readonly'):
        auth = await login(client, role)
        _response = await client.get('/api/portfolios', headers=auth)
        assert _response.status_code == 200
        assert (_response).json()['total'] == 3
        assert (await client.put('/api/portfolios/'+own['id'], headers=auth, json=payload)).status_code == 403


async def test_missing_and_invalid_portfolios_leave_database_unchanged(client):
    """Validate required fields and distinguish nonexistent resources from invalid bodies."""
    from bson import ObjectId
    auth = await login(client, 'admin')
    db = app.state.db
    before = await db.portfolios.count_documents({})
    for body in ({}, {'name': ''}, {'name': 'x' * 201}, {'name': {'$ne': ''}}, {'name': 'Valid', 'description': 'x' * 4001}, {'name': 'Valid', 'status': 'Unknown'}):
        response = await client.post('/api/portfolios', headers=auth, json=body)
        assert response.status_code == 422
    for identifier in ('invalid', str(ObjectId())):
        path = '/api/portfolios/' + identifier
        assert (await client.get(path, headers=auth)).status_code == 404
        assert (await client.get(path + '/applications', headers=auth)).status_code == 404
        assert (await client.put(path, headers=auth, json={'name': 'Valid'})).status_code == 404
        assert (await client.delete(path, headers=auth)).status_code == 404
    assert await db.portfolios.count_documents({}) == before


async def test_duplicate_portfolio_name_update_preserves_records(client):
    """A conflicting rename returns 409 without changing either portfolio."""
    auth = await login(client, 'admin')
    db = app.state.db
    first = await db.portfolios.find_one({'name': 'Payments'})
    second = await db.portfolios.find_one({'name': 'Customer Platform'})
    payload = {key: second[key] for key in ('name', 'owner', 'description', 'productArea', 'status')}
    response = await client.put('/api/portfolios/' + str(second['_id']), headers=auth, json={**payload, 'name': first['name']})
    assert response.status_code == 409
    assert await db.portfolios.find_one({'_id': first['_id']}) == first
    assert await db.portfolios.find_one({'_id': second['_id']}) == second


async def test_portfolio_field_boundaries_on_create_and_update(client):
    """Validate field limits and preserve records and audit on rejected writes."""
    from bson import ObjectId
    auth = await login(client, 'admin')
    db = app.state.db
    base = {'name': 'Boundary portfolio', 'owner': 'Owner', 'description': 'Description', 'productArea': 'Area', 'status': 'Active'}
    created = await client.post('/api/portfolios', headers=auth, json=base)
    assert created.status_code == 201
    identifier = created.json()['id']
    before = await db.portfolios.find({}).sort('_id', 1).to_list(None)
    events = await db.audit_logs.count_documents({})
    invalid = [{k: v for k, v in base.items() if k != 'name'}, {**base, 'name': ''}, {**base, 'name': ' '}, {**base, 'extra': 1}]
    for key, maximum in [('name', 200), ('owner', 200), ('description', 4000), ('productArea', 200)]:
        invalid += [{**base, key: value} for value in (None, {}, True, 'x' * (maximum + 1))]
    invalid += [{**base, 'status': value} for value in (None, {}, '', 'Invalid')]
    for body in invalid:
        for method, path in [('post', '/api/portfolios'), ('put', '/api/portfolios/' + identifier)]:
            response = await getattr(client, method)(path, headers=auth, json=body)
            assert response.status_code == 422, (method, body, response.text)
            assert await db.portfolios.find({}).sort('_id', 1).to_list(None) == before
            assert await db.audit_logs.count_documents({}) == events
    limits = {'name': 'n' * 200, 'owner': 'o' * 200, 'description': 'd' * 4000, 'productArea': 'a' * 200, 'status': 'Archived'}
    response = await client.put('/api/portfolios/' + identifier, headers=auth, json=limits)
    assert response.status_code == 200, response.text
    stored = await db.portfolios.find_one({'_id': ObjectId(identifier)})
    assert all(stored[key] == value for key, value in limits.items())
    limits['name'] = 'c' * 200
    response = await client.post('/api/portfolios', headers=auth, json=limits)
    assert response.status_code == 201, response.text
    stored = await db.portfolios.find_one({'_id': ObjectId(response.json()['id'])})
    assert all(stored[key] == value for key, value in limits.items())


async def test_leader_scope_and_permission_are_independent(client):
    """Changing assignments alone and permissions alone immediately changes reads."""
    leader = await login(client, 'leader')
    db = app.state.db
    own = await db.portfolios.find_one({'name': 'Payments'})
    other = await db.portfolios.find_one({'name': 'Customer Platform'})
    own_id, other_id = str(own['_id']), str(other['_id'])
    await db.users.update_one({'email': 'leader@ketsip.local'}, {'$set': {'portfolioAccess': [other_id]}})
    result = await client.get('/api/portfolios', headers=leader)
    assert result.status_code == 200 and [item['id'] for item in result.json()['items']] == [other_id]
    assert (await client.get('/api/portfolios/' + own_id, headers=leader)).status_code == 403
    assert (await client.get('/api/portfolios/' + other_id, headers=leader)).status_code == 200
    await db.roles.update_one({'name': 'Portfolio Leader'}, {'$set': {'permissions': ['edit']}})
    assert (await client.get('/api/portfolios', headers=leader)).status_code == 403
    assert (await client.get('/api/portfolios/' + other_id, headers=leader)).status_code == 403
