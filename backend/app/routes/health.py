import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, func, select

from app.auth import get_current_user
from app.database import SessionLocal
from app import provider_health
from app.models import RequestLog, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness only. It does not touch Redis or Postgres, so a slow dependency never gets the pod restarted."""
    return {"status": "ok"}


@router.get("/api/health/providers")
async def providers_health(user: User = Depends(get_current_user)):
    """
    Status of each provider, worked out from real traffic through this gateway
    (see app/provider_health.py). A provider nobody called recently is "unknown".
    """
    try:
        providers = await provider_health.snapshot()
    except Exception:
        logger.warning("could not read provider health", exc_info=True)
        raise HTTPException(status_code=503, detail="Health data is unavailable right now")
    return {"updated_at": datetime.now(timezone.utc).isoformat(), "providers": providers}


@router.get("/api/stats")
async def stats(user: User = Depends(get_current_user)):
   
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                RequestLog.provider,
                func.count(RequestLog.id).label("requests"),
                func.sum(RequestLog.cost_usd).label("total_cost"),
                func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
                func.sum(RequestLog.cache_hit.cast(Integer)).label("cache_hits"),
            ).where(RequestLog.user_id == user.id).group_by(RequestLog.provider)
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
