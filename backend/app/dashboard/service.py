"""Compute executive measures from authorized application inventory."""
from pymongo.asynchronous.database import AsyncDatabase
from app.applications.repository import ApplicationRepository
from app.applications.service import authorize


def rounded_average(total: int, count: int) -> int | None:
    """Round a non-negative score average to the nearest integer, with halves up."""
    return (2 * total + count) // (2 * count) if count else None


async def executive_dashboard(db: AsyncDatabase, user: dict, portfolio_id: str | None, product_area: str | None, risk: str | None) -> dict:
    """Aggregate only applications visible to the caller and matching the filters."""
    await authorize(ApplicationRepository(db), user, "view", portfolio_id)
    query: dict = {}
    if user["role"] == "Portfolio Leader":
        query["portfolioId"] = {"$in": user.get("portfolioAccess", [])}
    if portfolio_id:
        query["portfolioId"] = portfolio_id
    if product_area:
        query["productArea"] = product_area
    if risk:
        query["riskLevel"] = risk
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$portfolioId", "count": {"$sum": 1}, "quality": {"$sum": "$qualityScore"}, "health": {"$sum": "$applicationHealthScore"}, "automation": {"$sum": "$automationCoverage"}, "defects": {"$sum": "$openCriticalDefects"}, "risk": {"$sum": {"$cond": [{"$eq": ["$riskLevel", "High"]}, 1, 0]}}}},
        {"$lookup": {"from": "portfolios", "let": {"portfolioId": {"$convert": {"input": "$_id", "to": "objectId", "onError": None, "onNull": None}}}, "pipeline": [{"$match": {"$expr": {"$eq": ["$_id", "$$portfolioId"]}}}, {"$project": {"name": 1}}], "as": "portfolio"}},
        {"$project": {"count": 1, "quality": 1, "health": 1, "automation": 1, "defects": 1, "risk": 1, "name": {"$ifNull": [{"$arrayElemAt": ["$portfolio.name", 0]}, "Unknown portfolio"]}}},
        {"$sort": {"name": 1, "_id": 1}},
    ]
    rows = await (await db.applications.aggregate(pipeline)).to_list(None)
    count = sum(row["count"] for row in rows)
    return {
        "enterpriseQualityScore": rounded_average(sum(row["quality"] for row in rows), count),
        "applicationHealthScore": rounded_average(sum(row["health"] for row in rows), count),
        "automationMaturityScore": rounded_average(sum(row["automation"] for row in rows), count),
        "openCriticalDefects": sum(row["defects"] for row in rows),
        "applicationsAtRisk": sum(row["risk"] for row in rows),
        "totalApplications": count,
        "totalPortfolios": len(rows),
        "portfolios": [{"portfolioId": row["_id"], "name": row["name"], "applicationCount": row["count"], "qualityScore": rounded_average(row["quality"], row["count"]), "applicationsAtRisk": row["risk"]} for row in rows],
    }
