"""Exercise identity against an isolated real MongoDB database."""
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

# App construction validates settings during import; the fixture replaces these
# with a unique test database before its lifespan starts.
os.environ.setdefault("JWT_SECRET", "test-only-unique-secret-for-identity-tests-2025")
from app.main import app
from app.core.config import get_settings
from app.core.security import hash_password, verify_password


@pytest.fixture
async def client(monkeypatch):
    """Start the real application with a unique disposable database."""
    values = {"JWT_SECRET": "test-only-unique-secret-for-identity-tests-2025", "MONGODB_URI": os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017"), "MONGODB_DB": "identity_test_" + uuid4().hex, "SEED_ON_STARTUP": "true", "ADMIN_INITIAL_PASSWORD": "TestAdmin123!", "DEMO_INITIAL_PASSWORD": "TestDemo123!"}
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


async def authenticate(client, email="engineer@ketsip.local", password="TestDemo123!"):
    """Sign in through the real API."""
    return await client.post('/api/auth/login', json={'email': email, 'password': password})


def headers(token):
    """Construct a bearer authorization header."""
    return {'Authorization': f'Bearer {token}'}


def test_bcrypt_verification_and_byte_limit():
    """Hash valid secrets and reject wrong and oversized input."""
    hashed = hash_password('A sufficiently long password')
    assert hashed.startswith('$2')
    assert verify_password('A sufficiently long password', hashed)
    assert not verify_password('wrong', hashed)
    assert not verify_password('x' * 73, hashed)


async def test_login_audit_and_seed_are_real(client):
    """Persist successes and failures without credential leakage."""
    assert await app.state.db.roles.count_documents({}) == 6
    assert await app.state.db.users.count_documents({}) == 6
    bad = await authenticate(client, 'unknown@ketsip.local', 'wrong-secret')
    assert bad.status_code == 401
    bad_known = await authenticate(client, password='wrong-secret')
    assert bad_known.status_code == 401
    ok = await authenticate(client, ' ENGINEER@ketsip.local ', 'TestDemo123!')
    assert ok.status_code == 200
    body = ok.json()
    assert body['user']['role'] == 'Engineer'
    assert 'passwordHash' not in body['user']
    claims = jwt.decode(body['token'], get_settings().JWT_SECRET, algorithms=['HS256'])
    assert claims['userId'] == body['user']['id'] and claims['role'] == 'Engineer'
    assert claims['exp'] - claims['iat'] == 8 * 3600
    events = await app.state.db.audit_logs.find({}).to_list(None)
    assert [e['details'] for e in events] == ['Failed login', 'Failed login', 'Successful login']
    assert events[0]['userId'] is None and events[1]['userId'] == body['user']['id']
    assert 'wrong-secret' not in str(events) and 'TestDemo123!' not in str(events)
    doc = await app.state.db.users.find_one({'email':'engineer@ketsip.local'})
    assert doc['passwordHash'].startswith('$2') and doc['lastLogin']


async def test_auth_boundaries_and_validation(client):
    """Reject missing, malformed, forged, and inactive identities."""
    assert (await client.get('/api/health')).json() == {'status': 'ok'}
    for token in ['', 'nonsense', jwt.encode({'sub':'bad','userId':'bad','role':'Administrator','exp':1}, get_settings().JWT_SECRET, algorithm='HS256')]:
        assert (await client.get('/api/auth/me', headers=headers(token))).status_code == 401
    assert (await client.post('/api/auth/logout')).status_code == 401
    assert (await client.put('/api/profile/preferences', json={'defaultLandingPage':'dashboard'})).status_code == 401
    assert (await client.post('/api/auth/login', json={'email':{'$ne':''}, 'password':'anything'})).status_code == 422
    token = (await authenticate(client)).json()['token']
    await app.state.db.users.update_one({'email':'engineer@ketsip.local'}, {'$set':{'status':'Inactive'}})
    assert (await client.get('/api/auth/me', headers=headers(token))).status_code == 401
    assert (await authenticate(client)).status_code == 401


async def test_admin_password_gate_change_and_revocation(client):
    """Enforce first password change and invalidate old tokens."""
    result = await authenticate(client, 'admin@ketsip.local', 'TestAdmin123!')
    old = result.json()['token']
    assert result.json()['user']['mustChangePassword'] is True
    assert (await client.get('/api/auth/me', headers=headers(old))).status_code == 200
    assert (await client.put('/api/profile/preferences', headers=headers(old), json={'defaultLandingPage':'applications'})).status_code == 403
    assert (await client.put('/api/profile/password', headers=headers(old), json={'currentPassword':'wrong','newPassword':'NewAdminPassword123!'})).status_code == 400
    assert (await client.put('/api/profile/password', headers=headers(old), json={'currentPassword':'TestAdmin123!','newPassword':'short'})).status_code == 422
    result = await client.put('/api/profile/password', headers=headers(old), json={'currentPassword':'TestAdmin123!','newPassword':'NewAdminPassword123!'})
    assert result.status_code == 200 and not result.json()['user']['mustChangePassword']
    assert (await client.get('/api/auth/me', headers=headers(old))).status_code == 401
    assert (await authenticate(client, 'admin@ketsip.local', 'TestAdmin123!')).status_code == 401
    assert (await authenticate(client, 'admin@ketsip.local', 'NewAdminPassword123!')).status_code == 200
    assert (await client.post('/api/auth/logout', headers=headers(result.json()['token']))).status_code == 200


async def test_preferences_persist_and_validate(client):
    """Save the landing page and reject unsupported destinations."""
    token = (await authenticate(client)).json()['token']
    assert (await client.put('/api/profile/preferences', headers=headers(token), json={'defaultLandingPage':'other'})).status_code == 422
    saved = await client.put('/api/profile/preferences', headers=headers(token), json={'defaultLandingPage':'dashboard'})
    assert saved.status_code == 200 and saved.json()['defaultLandingPage'] == 'dashboard'
    assert (await client.get('/api/auth/me', headers=headers(token))).json()['defaultLandingPage'] == 'dashboard'
    assert (await app.state.db.users.find_one({'email':'engineer@ketsip.local'}))['defaultLandingPage'] == 'dashboard'
