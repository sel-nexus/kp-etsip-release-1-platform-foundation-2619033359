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
    assert (await client.get('/api/users/' + identifier, headers=auth)).json()['id'] == identifier
    assert (await client.get('/api/users/bad', headers=auth)).status_code == 404
    listing = await client.get('/api/users?limit=2&offset=0', headers=auth)
    assert listing.status_code == 200 and len(listing.json()['items']) == 2 and listing.json()['total'] == 7
    assert 'passwordHash' not in listing.text
    assert (await client.delete('/api/portfolios/' + portfolio_id, headers=auth)).status_code == 409
    old_token = await login(client, 'person@example.com', payload['password'])
    changed = fields(email='person@example.com', role='Read Only', password=None)
    response = await client.put('/api/users/' + identifier, headers=auth, json=changed)
    assert response.status_code == 200 and response.json()['role'] == 'Read Only'
    assert (await client.get('/api/auth/me', headers=old_token)).status_code == 401
    assert (await client.delete('/api/users/' + identifier, headers=auth)).status_code == 204
    assert (await client.get('/api/users/' + identifier, headers=auth)).json()['status'] == 'Inactive'
    assert (await client.delete('/api/users/' + identifier, headers=auth)).status_code == 409
    events = await app.state.db.audit_logs.find({'entityId': identifier}).to_list(None)
    assert {'create', 'edit', 'roleChange', 'deactivate'} <= {event['action'] for event in events}
    assert payload['password'] not in str(events) and stored['passwordHash'] not in str(events)


async def test_password_and_status_changes_revoke_tokens(client):
    """Invalidate old sessions on password reset and status transitions."""
    auth = await admin(client)
    payload = fields()
    account = (await client.post('/api/users', headers=auth, json=payload)).json()
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
    current = (await client.get('/api/auth/me', headers=auth)).json()
    assert (await client.delete('/api/users/' + current['id'], headers=auth)).status_code == 409
    assert (await client.put('/api/users/' + current['id'], headers=auth, json=fields(email=current['email'], role='Read Only', password=None))).status_code == 409
    other = (await client.post('/api/users', headers=auth, json=fields(email='admin2@example.com', role='Administrator'))).json()
    second_login = await login(client, 'admin2@example.com', 'ExamplePassword123!')
    reset = await client.put('/api/profile/password', headers=second_login, json={'currentPassword': 'ExamplePassword123!', 'newPassword': 'SecondAdminPassword123!'})
    second_auth = {'Authorization': 'Bearer ' + reset.json()['token']}
    # Each administrator tries to deactivate the other concurrently.
    results = await asyncio.gather(client.delete('/api/users/' + other['id'], headers=auth), client.delete('/api/users/' + current['id'], headers=second_auth))
    assert sorted(response.status_code for response in results) in ([204, 401], [204, 403], [204, 409])
    assert await app.state.db.users.count_documents({'role': 'Administrator', 'status': 'Active'}) == 1


async def test_role_ceiling_and_enforcement(client):
    """Enforce fixed maxima and apply restrictions to existing routes immediately."""
    auth = await admin(client)
    role_page = (await client.get('/api/roles', headers=auth)).json()
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
    assert (await client.get('/api/admin/portfolios', headers=auth)).json()['total'] == 3
    assert (await client.put(path, headers=auth, json={'name': 'Engineer', 'description': '', 'permissions': ['administer']})).status_code == 422
    assert (await client.put('/api/roles/' + admin_role['id'], headers=auth, json={'name': 'Administrator', 'description': '', 'permissions': ['view']})).status_code == 409
    assert (await client.put(path, headers=auth, json={'name': 'Engineer', 'description': 'Restricted', 'permissions': ['view']})).status_code == 200
    engineer_auth = await login(client, 'engineer@ketsip.local', 'TestDemo123!')
    assert (await client.get('/api/applications', headers=engineer_auth)).status_code == 200
    assert (await client.post('/api/applications', headers=engineer_auth, json={})).status_code == 422
    from app.applications.service import authorize
    from app.applications.repository import ApplicationRepository
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await authorize(ApplicationRepository(app.state.db), {'role': 'Engineer'}, 'create')
    assert error.value.status_code == 403
    events = await app.state.db.audit_logs.find({'entityId': engineer['id']}).to_list(None)
    assert {'edit', 'permissionChange'} <= {event['action'] for event in events}
