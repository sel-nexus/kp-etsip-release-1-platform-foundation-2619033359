"""Idempotently seed the six roles and local demonstration accounts."""
from starlette.concurrency import run_in_threadpool
from pymongo.asynchronous.database import AsyncDatabase
from app.auth.repository import timestamp
from app.core.config import Settings
from app.core.security import hash_password
from app.applications.repository import ApplicationRepository

ROLES = {
    "Administrator": ["view", "create", "edit", "delete", "export", "administer"],
    "Executive": ["view", "export"],
    "Portfolio Leader": ["view", "create", "edit", "export"],
    "Engineer": ["view", "create", "edit", "export"],
    "Auditor": ["view", "export"],
    "Read Only": ["view"],
}


async def seed_database(db: AsyncDatabase, settings: Settings) -> None:
    """Insert missing roles and demo users without replacing existing changes."""
    now = timestamp()
    for name, owner, area in [("Payments", "Payments Team", "Payments"), ("Customer Platform", "Customer Team", "Customer"), ("Data & Analytics", "Data Team", "Data")]:
        await db.portfolios.update_one({"name": name}, {"$setOnInsert": {"name": name, "owner": owner, "description": "", "productArea": area, "status": "Active", "createdAt": now, "updatedAt": now}}, upsert=True)
    payments = await db.portfolios.find_one({"name": "Payments"})
    # Every seed insert follows the same reference protocol as API writes.
    applications = ApplicationRepository(db)
    samples = [
        ("Payment Gateway", "Payments", "High", 1, 91, 86, 74, 80, 8, 1, "Medium"),
        ("Settlement Hub", "Payments", "Critical", 1, 78, 76, 61, 72, 15, 3, "High"),
        ("Billing Console", "Payments", "Medium", 2, 87, 83, 68, 76, 7, 0, "Low"),
        ("Customer Profile", "Customer Platform", "High", 1, 89, 84, 79, 85, 9, 1, "Medium"),
        ("Member Portal", "Customer Platform", "Critical", 1, 82, 79, 65, 70, 13, 2, "High"),
        ("Contact Center", "Customer Platform", "Medium", 2, 94, 90, 82, 88, 4, 0, "Low"),
        ("Identity Directory", "Customer Platform", "High", 2, 88, 85, 73, 81, 6, 0, "Low"),
        ("Analytics Warehouse", "Data & Analytics", "High", 1, 85, 81, 70, 78, 10, 1, "Medium"),
        ("Quality Insights", "Data & Analytics", "Medium", 2, 92, 89, 83, 87, 5, 0, "Low"),
        ("Data Ingestion", "Data & Analytics", "High", 2, 76, 74, 58, 66, 17, 3, "High"),
    ]
    for name, portfolio_name, criticality, tier, health, quality, automation, unit, defects, critical, risk in samples:
        portfolio = await db.portfolios.find_one({"name": portfolio_name})
        if not portfolio:
            continue
        reservation = await applications.reserve(portfolio["_id"])
        if not reservation:
            continue
        fields = {"name": name, "description": f"{name} inventory service", "portfolioId": str(portfolio["_id"]), "productArea": portfolio["productArea"], "businessOwner": portfolio["owner"], "technologyOwner": "Technology Team", "etsOwner": "Quality Engineering", "criticality": criticality, "tier": tier, "lifecycleStatus": "Active", "technologyStack": "Python, APIs and MongoDB", "repositoryLink": None, "pipelineLink": None, "applicationHealthScore": health, "qualityScore": quality, "automationCoverage": automation, "unitTestCoverage": unit, "openDefects": defects, "openCriticalDefects": critical, "riskLevel": risk, "createdAt": now, "updatedAt": now}
        await db.applications.update_one({"name": name}, {"$setOnInsert": fields}, upsert=True)
        await applications.release(portfolio["_id"], reservation)
    admin_hash = await run_in_threadpool(hash_password, settings.ADMIN_INITIAL_PASSWORD)
    demo_hash = await run_in_threadpool(hash_password, settings.DEMO_INITIAL_PASSWORD)
    for role, permissions in ROLES.items():
        await db.roles.update_one({"name": role}, {"$setOnInsert": {"name": role, "description": f"{role} access", "permissions": permissions, "createdAt": now, "updatedAt": now}}, upsert=True)
        slug = {"Administrator": "admin", "Portfolio Leader": "leader", "Read Only": "readonly"}.get(role, role.lower())
        email = f"{slug}@ketsip.local"
        user = {"name": f"Demo {role}", "email": email, "passwordHash": admin_hash if role == "Administrator" else demo_hash, "role": role, "portfolioAccess": [str(payments["_id"])] if role == "Portfolio Leader" else [], "status": "Active", "lastLogin": None, "authSource": "local", "managerName": None, "vendorIndicator": False, "mustChangePassword": role == "Administrator", "defaultLandingPage": None, "tokenVersion": 0, "createdAt": now, "updatedAt": now}
        await db.users.update_one({"email": email}, {"$setOnInsert": user}, upsert=True)
