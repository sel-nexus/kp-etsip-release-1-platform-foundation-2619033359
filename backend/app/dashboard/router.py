"""Expose the scoped executive dashboard read model."""
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase
from app.applications.schemas import Risk
from app.core.database import get_database
from app.core.security import require_ready_user
from app.dashboard.service import executive_dashboard


class PortfolioMetrics(BaseModel):
    """Describe one represented portfolio's selected applications."""
    portfolioId: str
    name: str
    applicationCount: int
    qualityScore: int | None
    applicationsAtRisk: int


class DashboardMetrics(BaseModel):
    """Describe the dashboard's selected inventory measures."""
    enterpriseQualityScore: int | None
    applicationHealthScore: int | None
    automationMaturityScore: int | None
    openCriticalDefects: int
    applicationsAtRisk: int
    totalApplications: int
    totalPortfolios: int
    portfolios: list[PortfolioMetrics]


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/executive", response_model=DashboardMetrics)
async def executive(db: Annotated[AsyncDatabase, Depends(get_database)], user: Annotated[dict, Depends(require_ready_user)], portfolioId: str | None = None, productArea: str | None = None, riskLevel: Risk | None = None) -> dict:
    """Return aggregate measures for the caller's visible inventory."""
    return await executive_dashboard(db, user, portfolioId, productArea, riskLevel)
