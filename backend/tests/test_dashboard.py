"""Verify dashboard aggregation and access against a real isolated MongoDB."""
import os
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("JWT_SECRET", "test-only-secret-for-dashboard-tests")
from app.core.config import get_settings
from app.dashboard.service import rounded_average
from app.main import app


@pytest.fixture
async def client(monkeypatch):
    """Start the application using a uniquely named disposable database."""
    values = {"JWT_SECRET": "test-only-secret-for-dashboard-tests", "MONGODB_URI": os.getenv("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017"), "MONGODB_DB": "dashboard_test_" + uuid4().hex, "SEED_ON_STARTUP": "true", "ADMIN_INITIAL_PASSWORD": "TestAdmin123!", "DEMO_INITIAL_PASSWORD": "TestDemo123!"}
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


async def login(client, role="executive"):
    """Obtain a real bearer token for a seeded account."""
    password = "TestAdmin123!" if role == "admin" else "TestDemo123!"
    response = await client.post('/api/auth/login', json={'email': f'{role}@ketsip.local', 'password': password})
    assert response.status_code == 200
    token = response.json()['token']
    return {'Authorization': f'Bearer {token}'}


async def populate():
    """Replace seed applications with deterministic score and scope fixtures."""
    db = app.state.db
    payments = await db.portfolios.find_one({'name': 'Payments'})
    customer = await db.portfolios.find_one({'name': 'Customer Platform'})
    await db.applications.delete_many({})
    await db.applications.insert_many([
        {'name': 'One', 'portfolioId': str(payments['_id']), 'productArea': 'Shared', 'qualityScore': 0, 'applicationHealthScore': 50, 'automationCoverage': 1, 'openCriticalDefects': 0, 'riskLevel': 'High'},
        {'name': 'Two', 'portfolioId': str(payments['_id']), 'productArea': 'Other', 'qualityScore': 1, 'applicationHealthScore': 51, 'automationCoverage': 0, 'openCriticalDefects': 2, 'riskLevel': 'Low'},
        {'name': 'Three', 'portfolioId': str(customer['_id']), 'productArea': 'Shared', 'qualityScore': 100, 'applicationHealthScore': 100, 'automationCoverage': 100, 'openCriticalDefects': 4, 'riskLevel': 'High'},
    ])
    return str(payments['_id']), str(customer['_id'])


def test_rounding_and_empty_average():
    """Keep zeros and round half scores up, with no average for no records."""
    assert rounded_average(0, 3) == 0
    assert rounded_average(1, 2) == 1
    assert rounded_average(4, 3) == 1
    assert rounded_average(0, 0) is None


async def test_exact_metrics_and_combined_filters(client):
    """Count selected applications, not empty portfolios, and aggregate exact values."""
    own, other = await populate()
    auth = await login(client)
    response = await client.get('/api/dashboard/executive', headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ('enterpriseQualityScore', 'applicationHealthScore', 'automationMaturityScore', 'openCriticalDefects', 'applicationsAtRisk', 'totalApplications', 'totalPortfolios')} == {'enterpriseQualityScore': 34, 'applicationHealthScore': 67, 'automationMaturityScore': 34, 'openCriticalDefects': 6, 'applicationsAtRisk': 2, 'totalApplications': 3, 'totalPortfolios': 2}
    rows = {row['portfolioId']: row for row in body['portfolios']}
    assert rows[own] == {'portfolioId': own, 'name': 'Payments', 'applicationCount': 2, 'qualityScore': 1, 'applicationsAtRisk': 1}
    assert rows[other]['qualityScore'] == 100 and rows[other]['applicationsAtRisk'] == 1
    filtered = (await client.get('/api/dashboard/executive', headers=auth, params={'portfolioId': own, 'productArea': 'Shared', 'riskLevel': 'High'})).json()
    assert filtered['totalApplications'] == 1 and filtered['totalPortfolios'] == 1
    assert filtered['enterpriseQualityScore'] == 0 and filtered['openCriticalDefects'] == 0
    assert filtered['portfolios'][0]['qualityScore'] == 0
    area = (await client.get('/api/dashboard/executive', headers=auth, params={'productArea': 'Shared'})).json()
    assert area['totalApplications'] == 2 and area['totalPortfolios'] == 2 and area['enterpriseQualityScore'] == 50
    risk = (await client.get('/api/dashboard/executive', headers=auth, params={'riskLevel': 'Low'})).json()
    assert risk['totalApplications'] == 1 and risk['applicationsAtRisk'] == 0
    empty = (await client.get('/api/dashboard/executive', headers=auth, params={'productArea': 'missing'})).json()
    assert empty == {'enterpriseQualityScore': None, 'applicationHealthScore': None, 'automationMaturityScore': None, 'openCriticalDefects': 0, 'applicationsAtRisk': 0, 'totalApplications': 0, 'totalPortfolios': 0, 'portfolios': []}
    assert (await client.get('/api/dashboard/executive', headers=auth, params={'riskLevel': 'Invalid'})).status_code == 422


async def test_auth_scope_permission_and_role_ceiling(client):
    """Enforce bearer, password readiness, editable view permission and leader scope."""
    own, other = await populate()
    assert (await client.get('/api/dashboard/executive')).status_code == 401
    assert (await client.get('/api/dashboard/executive', headers={'Authorization': 'Bearer invalid'})).status_code == 401
    admin = await login(client, 'admin')
    assert (await client.get('/api/dashboard/executive', headers=admin)).status_code == 403
    for role in ('executive', 'engineer', 'auditor', 'readonly'):
        result = await client.get('/api/dashboard/executive', headers=await login(client, role))
        assert result.status_code == 200 and result.json()['totalApplications'] == 3
    leader = await login(client, 'leader')
    scoped = await client.get('/api/dashboard/executive', headers=leader)
    assert scoped.status_code == 200 and scoped.json()['totalApplications'] == 2
    assert [item['portfolioId'] for item in scoped.json()['portfolios']] == [own]
    assert (await client.get('/api/dashboard/executive', headers=leader, params={'portfolioId': other})).status_code == 403
    await app.state.db.users.update_one({'email': 'leader@ketsip.local'}, {'$set': {'portfolioAccess': []}})
    assert (await client.get('/api/dashboard/executive', headers=leader)).json()['totalApplications'] == 0
    assert (await client.get('/api/dashboard/executive', headers=leader, params={'portfolioId': own})).status_code == 403
    await app.state.db.roles.update_one({'name': 'Executive'}, {'$set': {'permissions': ['export']}})
    assert (await client.get('/api/dashboard/executive', headers=await login(client))).status_code == 403
