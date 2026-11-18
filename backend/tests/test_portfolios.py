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
    token = response.json()['token']
    if role == 'admin':
        changed = await client.put('/api/profile/password', headers={'Authorization': f'Bearer {token}'}, json={'currentPassword': password, 'newPassword': 'NewAdminPassword123!'})
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
    assert (await client.get('/api/portfolios', headers=auth, params={'search':'.*'})).json()['total'] == 0
    assert len((await client.get('/api/portfolios', headers=auth, params={'limit':1, 'offset':1})).json()['items']) == 1
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
    assert (await client.get('/api/portfolios/'+identifier, headers=auth)).json()['name'] == 'Updated'
    db = app.state.db
    await db.applications.insert_many([{'name':'One', 'portfolioId':identifier, 'qualityScore': 80}, {'name':'Two', 'portfolioId':identifier, 'qualityScore': 81}])
    detail = (await client.get('/api/portfolios/'+identifier, headers=auth)).json()
    assert detail['applicationCount'] == 2 and detail['qualityScore'] == 81
    apps = (await client.get('/api/portfolios/'+identifier+'/applications', headers=auth, params={'limit':1})).json()
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
    all_items = (await client.get('/api/portfolios', headers=admin)).json()['items']
    visible = (await client.get('/api/portfolios', headers=leader)).json()['items']
    assert len(visible) == 1 and visible[0]['name'] == 'Payments'
    own = visible[0]
    other = next(item for item in all_items if item['id'] != own['id'])
    payload = {key: own[key] for key in ('name', 'owner', 'description', 'productArea', 'status')}
    assert (await client.put('/api/portfolios/'+own['id'], headers=leader, json={**payload, 'owner':'Leader'})).status_code == 200
    for suffix in ('', '/applications'):
        assert (await client.get('/api/portfolios/'+other['id']+suffix, headers=leader)).status_code == 403
    assert (await client.put('/api/portfolios/'+other['id'], headers=leader, json=payload)).status_code == 403
    await app.state.db.roles.update_one({'name':'Portfolio Leader'}, {'$set':{'permissions':['view','create','edit','delete']}})
    assert (await client.post('/api/portfolios', headers=leader, json={**payload, 'name':'Forbidden'})).status_code == 403
    assert (await client.delete('/api/portfolios/'+own['id'], headers=leader)).status_code == 403
    await app.state.db.roles.update_one({'name':'Portfolio Leader'}, {'$set':{'permissions':['view']}})
    assert (await client.put('/api/portfolios/'+own['id'], headers=leader, json=payload)).status_code == 403
    await app.state.db.users.update_one({'email':'leader@ketsip.local'}, {'$set':{'portfolioAccess':[]}})
    assert (await client.get('/api/portfolios', headers=leader)).json()['total'] == 0
    assert (await client.get('/api/portfolios/'+own['id'], headers=leader)).status_code == 403
    for role in ('engineer', 'executive', 'auditor', 'readonly'):
        auth = await login(client, role)
        assert (await client.get('/api/portfolios', headers=auth)).json()['total'] == 3
        assert (await client.put('/api/portfolios/'+own['id'], headers=auth, json=payload)).status_code == 403
