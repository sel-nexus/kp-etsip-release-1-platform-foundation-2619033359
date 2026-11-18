"""Compose the API and manage its MongoDB lifespan."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import AsyncMongoClient
from app.auth.router import router as identity_router
from app.core.config import get_settings
from app.core.database import create_indexes
from app.core.seed import seed_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open one async MongoDB client and close it at shutdown."""
    settings = get_settings()
    client = AsyncMongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
    try:
        app.state.db = client.get_database(settings.MONGODB_DB)
        await client.admin.command("ping")
        await create_indexes(app.state.db)
        if settings.SEED_ON_STARTUP:
            await seed_database(app.state.db, settings)
        yield
    finally:
        await client.close()


settings = get_settings()
app = FastAPI(title="KP ETSIP API", version="1.0.0", description="Local identity and quality inventory foundation", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(identity_router, prefix="/api")


@app.get("/api/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Report process liveness without querying external services."""
    return {"status": "ok"}
