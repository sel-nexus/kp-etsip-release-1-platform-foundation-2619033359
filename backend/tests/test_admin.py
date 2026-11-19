"""Exercise administrative operations against an isolated real MongoDB database."""
import asyncio
import os
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from bson import ObjectId

os.environ.setdefault('JWT_SECRET', 'test-only-unique-secret-for-admin-tests-2025')
from app.main import app
from app.core.config import get_settings
from app.core.security import verify_password


@pytest.fixture
async def client(monkeypatch):
    """Start the application against a disposable Mongo database."""
    values = {'JWT_SECRET': 'test-only-unique-secret-for-admin-tests-2025', 'MONGODB_URI': os.getenv('TEST_MONGODB_URI', 'mongodb://127.0.0.1:27017'), 'MONGODB_DB': 'admin_test_' + uuid4().hex, 'SEED_ON_STARTUP': 'true', 'ADMIN_INITIAL_PASSWORD': 'TestAdmin123!', 'DEMO_INITIAL_PASSWORD': 'TestDemo123!'}
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


async def login(client, email, password):
    """Obtain an actual bearer session."""
    response = await client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}


async def admin(client):
    """Complete the initial administrator password change."""
    initial = await login(client, 'admin@ketsip.local', 'TestAdmin123!')
    response = await client.put('/api/profile/password', headers=initial, json={'currentPassword': 'TestAdmin123!', 'newPassword': 'NewAdminPassword123!'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}


def fields(**overrides):
    """Build a valid account payload for mutation tests."""
    return {'name': 'Example User', 'email': 'person@example.com', 'role': 'Engineer', 'status': 'Active', 'portfolioAccess': [], 'managerName': None, 'vendorIndicator': False, 'password': 'ExamplePassword123!', **overrides}


async def test_administration_is_not_accessible_to_other_roles(client):
    """Reject anonymous, auditor and other non-administrative requests."""
    assert (await client.get('/api/users')).status_code == 401
    for email in ['auditor@ketsip.local', 'engineer@ketsip.local', 'readonly@ketsip.local']:
        auth = await login(client, email, 'TestDemo123!')
        assert (await client.get('/api/users', headers=auth)).status_code == 403
        assert (await client.get('/api/roles', headers=auth)).status_code == 403
        assert (await client.post('/api/users', headers=auth, json=fields())).status_code == 403
        assert (await client.put('/api/roles/bad', headers=auth, json={'name': 'Auditor', 'description': '', 'permissions': ['view']})).status_code == 403
    initial = await login(client, 'admin@ketsip.local', 'TestAdmin123!')
    assert (await client.get('/api/users', headers=initial)).status_code == 403


async def test_user_crud_unique_email_hash_scope_and_audit(client):
    """Persist account changes, protect references and never disclose passwords."""
    auth = await admin(client)
    portfolio_response = await client.post('/api/portfolios', headers=auth, json={'name': 'Assigned Only', 'owner': '', 'description': '', 'productArea': '', 'status': 'Active'})
    assert portfolio_response.status_code == 201
    portfolio_id = portfolio_response.json()['id']
    payload = fields(email=' PERSON@EXAMPLE.COM ', portfolioAccess=[portfolio_id])
    response = await client.post('/api/users', headers=auth, json=payload)
    assert response.status_code == 201, response.text
    account = response.json(); identifier = account['id']
    assert account['email'] == 'person@example.com' and 'passwordHash' not in account and 'password' not in account
    stored = await app.state.db.users.find_one({'_id': ObjectId(identifier)})
    assert stored['passwordHash'].startswith('$2') and verify_password(payload['password'], stored['passwordHash'])
    assert (await client.post('/api/users', headers=auth, json=payload)).status_code == 409
    assert (await client.post('/api/users', headers=auth, json=fields(email='different@example.com', portfolioAccess=[str(ObjectId())]))).status_code == 422
    assert (await client.post('/api/users', headers=auth, json=fields(email='invalid'))).status_code == 422
    assert (await client.post('/api/users', headers=auth, json=fields(role='Superuser'))).status_code == 422
    assert (await client.post('/api/users', headers=auth, json=fields(password='é' * 40))).status_code == 422
    _response = await client.get('/api/users/' + identifier, headers=auth)
    assert _response.status_code == 200
    assert (_response).json()['id'] == identifier
    assert (await client.get('/api/users/bad', headers=auth)).status_code == 404
    listing = await client.get('/api/users?limit=2&offset=0', headers=auth)
    assert listing.status_code == 200 and len(listing.json()['items']) == 2 and listing.json()['total'] == 7
    assert 'passwordHash' not in listing.text
    assert (await client.delete('/api/portfolios/' + portfolio_id, headers=auth)).status_code == 409
    old_token = await login(client, 'person@example.com', payload['password'])
    changed = fields(email='person@example.com', role='Read Only', password=None)
    response = await client.put('/api/users/' + identifier, headers=auth, json=changed)
    assert response.status_code == 200 and response.json()['role'] == 'Read Only'
    reread = await client.get('/api/users/' + identifier, headers=auth)
    assert reread.status_code == 200 and reread.json()['role'] == 'Read Only'
    assert (await app.state.db.users.find_one({'_id': ObjectId(identifier)}))['role'] == 'Read Only'
    assert (await client.get('/api/auth/me', headers=old_token)).status_code == 401
    assert (await client.delete('/api/users/' + identifier, headers=auth)).status_code == 204
    _response = await client.get('/api/users/' + identifier, headers=auth)
    assert _response.status_code == 200
    assert (_response).json()['status'] == 'Inactive'
    assert (await client.delete('/api/users/' + identifier, headers=auth)).status_code == 409
    events = await app.state.db.audit_logs.find({'entityId': identifier}).to_list(None)
    assert {'create', 'edit', 'roleChange', 'delete'} <= {event['action'] for event in events}
    assert 'deactivate' not in {event['action'] for event in events}
    assert payload['password'] not in str(events) and stored['passwordHash'] not in str(events)


async def test_password_and_status_changes_revoke_tokens(client):
    """Invalidate old sessions on password reset and status transitions."""
    auth = await admin(client)
    payload = fields()
    _response = await client.post('/api/users', headers=auth, json=payload)
    assert _response.status_code == 201
    account = (_response).json()
    token = await login(client, payload['email'], payload['password'])
    replacement = fields(password='ReplacementPassword123!')
    assert (await client.put('/api/users/' + account['id'], headers=auth, json=replacement)).status_code == 200
    assert (await client.get('/api/auth/me', headers=token)).status_code == 401
    token = await login(client, payload['email'], replacement['password'])
    assert (await client.delete('/api/users/' + account['id'], headers=auth)).status_code == 204
    assert (await client.get('/api/auth/me', headers=token)).status_code == 401
    replacement.update(status='Active', password=None)
    assert (await client.put('/api/users/' + account['id'], headers=auth, json=replacement)).status_code == 200
    assert (await client.get('/api/auth/me', headers=token)).status_code == 401


async def test_admin_lockout_and_concurrent_demotions(client):
    """Keep an active administrator even when demotions race."""
    auth = await admin(client)
    _response = await client.get('/api/auth/me', headers=auth)
    assert _response.status_code == 200
    current = (_response).json()
    assert (await client.delete('/api/users/' + current['id'], headers=auth)).status_code == 409
    assert (await client.put('/api/users/' + current['id'], headers=auth, json=fields(email=current['email'], role='Read Only', password=None))).status_code == 409
    _response = await client.post('/api/users', headers=auth, json=fields(email='admin2@example.com', role='Administrator'))
    assert _response.status_code == 201
    other = (_response).json()
    second_login = await login(client, 'admin2@example.com', 'ExamplePassword123!')
    reset = await client.put('/api/profile/password', headers=second_login, json={'currentPassword': 'ExamplePassword123!', 'newPassword': 'SecondAdminPassword123!'})
    assert reset.status_code == 200
    second_auth = {'Authorization': 'Bearer ' + reset.json()['token']}
    # Each administrator tries to deactivate the other concurrently.
    results = await asyncio.gather(client.delete('/api/users/' + other['id'], headers=auth), client.delete('/api/users/' + current['id'], headers=second_auth))
    assert sorted(response.status_code for response in results) in ([204, 401], [204, 403], [204, 409])
    assert await app.state.db.users.count_documents({'role': 'Administrator', 'status': 'Active'}) == 1


async def test_role_ceiling_and_enforcement(client):
    """Enforce fixed maxima and apply restrictions to existing routes immediately."""
    auth = await admin(client)
    _response = await client.get('/api/roles', headers=auth)
    assert _response.status_code == 200
    role_page = (_response).json()
    assert role_page['total'] == 6
    engineer = next(role for role in role_page['items'] if role['name'] == 'Engineer')
    admin_role = next(role for role in role_page['items'] if role['name'] == 'Administrator')
    path = '/api/roles/' + engineer['id']
    assert (await client.post('/api/roles', headers=auth, json={'name': 'Engineer', 'description': '', 'permissions': ['view']})).status_code == 409
    assert (await client.post('/api/roles', headers=auth, json={'name': 'Unknown', 'description': '', 'permissions': ['view']})).status_code == 422
    removed = await app.state.db.roles.delete_one({'name': 'Auditor'})
    assert removed.deleted_count == 1
    created = await client.post('/api/roles', headers=auth, json={'name': 'Auditor', 'description': 'Restored', 'permissions': ['view']})
    assert created.status_code == 201 and created.json()['name'] == 'Auditor'
    assert (await app.state.db.roles.find_one({'_id': ObjectId(created.json()['id'])}))['description'] == 'Restored'
    options = await client.get('/api/admin/portfolios', headers=auth)
    assert options.status_code == 200 and options.json()['total'] == 3
    assert (await client.put(path, headers=auth, json={'name': 'Engineer', 'description': '', 'permissions': ['administer']})).status_code == 422
    assert (await client.put('/api/roles/' + admin_role['id'], headers=auth, json={'name': 'Administrator', 'description': '', 'permissions': ['view']})).status_code == 409
    assert (await client.put(path, headers=auth, json={'name': 'Engineer', 'description': 'Restricted', 'permissions': ['view']})).status_code == 200
    persisted = await app.state.db.roles.find_one({'_id': ObjectId(engineer['id'])})
    assert persisted['description'] == 'Restricted' and persisted['permissions'] == ['view']
    engineer_auth = await login(client, 'engineer@ketsip.local', 'TestDemo123!')
    assert (await client.get('/api/applications', headers=engineer_auth)).status_code == 200
    assert (await client.post('/api/applications', headers=engineer_auth, json={})).status_code == 422
    portfolio = await app.state.db.portfolios.find_one({'name': 'Payments'})
    count = await app.state.db.applications.count_documents({})
    denied = await client.post('/api/applications', headers=engineer_auth, json={'name': 'Permission denied', 'portfolioId': str(portfolio['_id'])})
    assert denied.status_code == 403
    assert await app.state.db.applications.count_documents({}) == count
    assert await app.state.db.applications.find_one({'name': 'Permission denied'}) is None
    from app.applications.service import authorize
    from app.applications.repository import ApplicationRepository
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await authorize(ApplicationRepository(app.state.db), {'role': 'Engineer'}, 'create')
    assert error.value.status_code == 403
    events = await app.state.db.audit_logs.find({'entityId': engineer['id']}).to_list(None)
    assert {'edit', 'permissionChange'} <= {event['action'] for event in events}


async def test_user_edit_deactivation_audit_and_missing_resources(client):
    """Audit an edit as edit, retain the account, and reject nonexistent IDs."""
    auth = await admin(client)
    created = await client.post('/api/users', headers=auth, json=fields(email='inactive@example.com'))
    assert created.status_code == 201
    identifier = created.json()['id']
    result = await client.put('/api/users/' + identifier, headers=auth, json=fields(email='inactive@example.com', status='Inactive', password=None))
    assert result.status_code == 200 and result.json()['status'] == 'Inactive'
    stored = await app.state.db.users.find_one({'_id': ObjectId(identifier)})
    assert stored['status'] == 'Inactive'
    events = await app.state.db.audit_logs.find({'entityType': 'user', 'entityId': identifier}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'edit']
    for missing in ('invalid', str(ObjectId())):
        path = '/api/users/' + missing
        assert (await client.get(path, headers=auth)).status_code == 404
        assert (await client.put(path, headers=auth, json=fields(password=None))).status_code == 404
        assert (await client.delete(path, headers=auth)).status_code == 404
    assert await app.state.db.users.count_documents({'email': 'inactive@example.com'}) == 1


async def test_user_and_role_invalid_fields_leave_database_unchanged(client):
    """Validate each applicable required field and each bounded optional field."""
    auth = await admin(client)
    db = app.state.db
    user = fields()
    cases = []
    for key in ('name', 'email', 'role'):
        cases.append({k: v for k, v in user.items() if k != key})
        for invalid in (None, {}, ''):
            cases.append({**user, key: invalid})
    for key, invalid in (
        ('name', 'x' * 201), ('email', 'x' * 255), ('role', 'x' * 201),
        ('password', None), ('password', ''), ('password', {}), ('password', 'x' * 73),
        ('portfolioAccess', None), ('portfolioAccess', {}), ('portfolioAccess', ['x'] * 501),
        ('status', None), ('status', {}), ('status', ''), ('status', 'x' * 201),
        ('managerName', {}), ('managerName', 'x' * 201), ('vendorIndicator', {}),
    ):
        cases.append({**user, key: invalid})
    before_users = await db.users.find({}).sort('_id', 1).to_list(None)
    for body in cases:
        response = await client.post('/api/users', headers=auth, json=body)
        assert response.status_code == 422, (body, response.text)
        assert await db.users.find({}).sort('_id', 1).to_list(None) == before_users

    created_user = await client.post('/api/users', headers=auth, json=user)
    assert created_user.status_code == 201
    user_id = created_user.json()['id']
    before_users = await db.users.find({}).sort('_id', 1).to_list(None)
    for body in cases:
        # A null password is intentionally allowed on updates (no reset).
        if body == {**user, 'password': None}:
            continue
        response = await client.put('/api/users/' + user_id, headers=auth, json=body)
        assert response.status_code == 422, (body, response.text)
        assert await db.users.find({}).sort('_id', 1).to_list(None) == before_users

    role = {'name': 'Auditor', 'description': 'Description', 'permissions': ['view']}
    role_cases = []
    for key in ('name', 'permissions'):
        role_cases.append({k: v for k, v in role.items() if k != key})
        for invalid in (None, {}, ''):
            role_cases.append({**role, key: invalid})
    role_cases += [{**role, 'name': 'x' * 201}, {**role, 'description': None},
                   {**role, 'description': {}}, {**role, 'description': 'x' * 1001},
                   {**role, 'permissions': ['view'] * 7}, {**role, 'permissions': ['view', 'view']}]
    before_roles = await db.roles.find({}).sort('_id', 1).to_list(None)
    for body in role_cases:
        response = await client.post('/api/roles', headers=auth, json=body)
        assert response.status_code == 422, (body, response.text)
        assert await db.roles.find({}).sort('_id', 1).to_list(None) == before_roles
    auditor = await db.roles.find_one({'name': 'Auditor'})
    for body in role_cases:
        response = await client.put('/api/roles/' + str(auditor['_id']), headers=auth, json=body)
        assert response.status_code == 422, (body, response.text)
        assert await db.roles.find({}).sort('_id', 1).to_list(None) == before_roles


async def test_duplicate_updates_assignments_and_missing_roles(client):
    """Reject conflicting account updates and invalid role references atomically."""
    auth = await admin(client)
    db = app.state.db
    first = await client.post('/api/users', headers=auth, json=fields(email='first@example.com'))
    second = await client.post('/api/users', headers=auth, json=fields(email='second@example.com'))
    assert first.status_code == 201 and second.status_code == 201
    identifier = second.json()['id']
    before = await db.users.find_one({'_id': ObjectId(identifier)})
    assert (await client.put('/api/users/' + identifier, headers=auth, json=fields(email='first@example.com', password=None))).status_code == 409
    portfolio = await db.portfolios.find_one({'name': 'Payments'})
    assignment = str(portfolio['_id'])
    assert (await client.put('/api/users/' + identifier, headers=auth, json=fields(email='second@example.com', password=None, portfolioAccess=[assignment, assignment]))).status_code == 422
    await db.roles.delete_one({'name': 'Engineer'})
    assert (await client.put('/api/users/' + identifier, headers=auth, json=fields(email='second@example.com', password=None))).status_code == 422
    assert await db.users.find_one({'_id': ObjectId(identifier)}) == before
    assert await db.users.count_documents({'email': 'first@example.com'}) == 1
    auditor = await db.roles.find_one({'name': 'Auditor'})
    for missing in ('invalid', str(ObjectId())):
        assert (await client.put('/api/roles/' + missing, headers=auth, json={'name': 'Auditor', 'permissions': ['view']})).status_code == 404
    renamed = await client.put('/api/roles/' + str(auditor['_id']), headers=auth, json={'name': 'Engineer', 'permissions': ['view']})
    assert renamed.status_code == 422
    assert await db.roles.find_one({'_id': auditor['_id']}) == auditor


async def test_role_stale_write_and_admin_options_denials(client, monkeypatch):
    """A disappeared role cannot be updated; options require admin permission."""
    from app.admin.repository import AdminRepository
    auth = await admin(client)
    engineer = await login(client, 'engineer@ketsip.local', 'TestDemo123!')
    assert (await client.get('/api/admin/portfolios')).status_code == 401
    assert (await client.get('/api/admin/portfolios', headers=engineer)).status_code == 403
    options = await client.get('/api/admin/portfolios', headers=auth, params={'limit': 1, 'offset': 1})
    assert options.status_code == 200 and options.json()['total'] == 3 and len(options.json()['items']) == 1
    db = app.state.db
    role = await db.roles.find_one({'name': 'Auditor'})
    events = await db.audit_logs.count_documents({'entityType': 'role', 'entityId': str(role['_id'])})
    original = AdminRepository.update_role
    async def disappear_before_write(self, identifier, fields):
        await self.db.roles.delete_one({'_id': identifier})
        return await original(self, identifier, fields)
    monkeypatch.setattr(AdminRepository, 'update_role', disappear_before_write)
    response = await client.put('/api/roles/' + str(role['_id']), headers=auth, json={'name': 'Auditor', 'permissions': ['view']})
    assert response.status_code == 409
    assert await db.roles.find_one({'_id': role['_id']}) is None
    assert await db.audit_logs.count_documents({'entityType': 'role', 'entityId': str(role['_id'])}) == events
    await db.roles.delete_one({'name': 'Administrator'})
    assert (await client.get('/api/admin/portfolios', headers=auth)).status_code == 403


async def test_stale_user_update_and_deactivation_conflict(client, monkeypatch):
    """Concurrent account revisions cause 409, release reservations and avoid audit."""
    from app.admin.repository import AdminRepository
    auth = await admin(client)
    db = app.state.db
    created = await client.post('/api/users', headers=auth, json=fields(email='stale@example.com'))
    assert created.status_code == 201
    identifier = created.json()['id']
    portfolio = await db.portfolios.find_one({'name': 'Payments'})
    original = AdminRepository.update_user
    async def concurrent_change(self, old, changes, revoke):
        await self.db.users.update_one({'_id': old['_id']}, {'$inc': {'tokenVersion': 1}, '$set': {'managerName': 'Concurrent'}})
        return await original(self, old, changes, revoke)
    monkeypatch.setattr(AdminRepository, 'update_user', concurrent_change)
    before = await db.audit_logs.count_documents({'entityType': 'user', 'entityId': identifier})
    response = await client.put('/api/users/' + identifier, headers=auth, json=fields(email='stale@example.com', password=None, portfolioAccess=[str(portfolio['_id'])]))
    assert response.status_code == 409 and 'changed' in response.json()['detail'].lower()
    stored = await db.users.find_one({'_id': ObjectId(identifier)})
    assert stored['managerName'] == 'Concurrent' and stored['portfolioAccess'] == [] and stored['status'] == 'Active'
    assert not (await db.portfolios.find_one({'_id': portfolio['_id']})).get('applicationReservations')
    assert await db.audit_logs.count_documents({'entityType': 'user', 'entityId': identifier}) == before
    response = await client.delete('/api/users/' + identifier, headers=auth)
    assert response.status_code == 409 and 'changed' in response.json()['detail'].lower()
    assert (await db.users.find_one({'_id': ObjectId(identifier)}))['status'] == 'Active'
    assert await db.audit_logs.count_documents({'entityType': 'user', 'entityId': identifier}) == before
