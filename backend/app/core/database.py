"""Provide the lifespan-managed MongoDB database."""
from fastapi import Request
from pymongo.asynchronous.database import AsyncDatabase


def get_database(request: Request) -> AsyncDatabase:
    """Return the database belonging to this application instance."""
    return request.app.state.db


async def create_indexes(db: AsyncDatabase) -> None:
    """Protect natural keys and support audit lookups."""
    await db.users.create_index("email", unique=True)
    await db.roles.create_index("name", unique=True)
    await db.audit_logs.create_index("timestamp")
    await db.audit_logs.create_index("userId")
    await db.portfolios.create_index("name", unique=True)
    await db.applications.create_index("portfolioId")
