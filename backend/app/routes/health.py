from fastapi import APIRouter
from sqlalchemy import Integer, func, select

from app.database import SessionLocal
from app.models import RequestLog

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/stats")
async def stats():
    """Minimal usage summary — swap for the Grafana/Kafka pipeline later;
    this is enough to power a simple in-app stats panel today."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                RequestLog.provider,
                func.count(RequestLog.id).label("requests"),
                func.sum(RequestLog.cost_usd).label("total_cost"),
                func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                func.sum(RequestLog.cache_hit.cast(Integer)).label("cache_hits"),
            ).group_by(RequestLog.provider)
        )
        rows = result.all()
        return {
            "by_provider": [
                {
                    "provider": r.provider,
                    "requests": r.requests,
                    "total_cost_usd": round(r.total_cost or 0, 6),
                    "avg_latency_ms": round(r.avg_latency_ms or 0, 1),
                    "cache_hits": r.cache_hits or 0,
                }
                for r in rows
            ]
        }
