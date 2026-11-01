import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import provider_health
from app.config import settings

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    if settings.METRICS_TOKEN:
        expected = f"Bearer {settings.METRICS_TOKEN}"
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid metrics token")
    try:
        await provider_health.refresh_state_gauges()
    except Exception:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
