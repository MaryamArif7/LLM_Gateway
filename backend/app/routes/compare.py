
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import metrics, provider_health
from app.auth import get_current_user
from app.cache import check_rate_limit
from app.providers import MODEL_PROVIDER_MAP, get_provider
from app.providers.base import ChatMessage
from app.routes.chat import _load_provider_keys
from app.models import User
from app.usage_events import new_usage_row, record_usage
from app.schemas import CompareRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compare", tags=["compare"])

MAX_COMPARE_MODELS = 4  


async def _run_one(provider_name: str, model_name: str, prompt: str, temperature: float, max_tokens: int, api_key: str) -> dict:
    start = time.perf_counter()
    try:
        provider = get_provider(provider_name, api_key)
        resp = await provider.chat([ChatMessage(role="user", content=prompt)], model_name, temperature, max_tokens)
        metrics.ATTEMPTS.labels(provider_name, model_name, "success").inc()
        metrics.PROVIDER_DURATION.labels(provider_name, model_name).observe(time.perf_counter() - start)
        metrics.REQUESTS.labels("compare", provider_name, model_name, "success", "false").inc()
        await provider_health.record(provider_name, "ok")
        return {
            "provider": provider_name, "model": model_name, "content": resp.content,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": round(resp.cost_usd, 6), "latency_ms": round(resp.latency_ms, 1),
            "error": None,
        }
    except Exception as e: 
        kind = provider_health.classify_failure(e)
        metrics.ATTEMPTS.labels(provider_name, model_name, "upstream_error" if kind == "upstream" else "client_error").inc()
        metrics.REQUESTS.labels("compare", provider_name, model_name, "error", "false").inc()
        await provider_health.record(provider_name, kind)
        return {
            "provider": provider_name, "model": model_name, "content": None,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "error": str(e),
        }


@router.post("")
async def compare(req: CompareRequest, request: Request, response: Response, user: User = Depends(get_current_user)):
    
    allowed, _ = await check_rate_limit(str(user.id))
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a bit.")

    if not req.models or len(req.models) > MAX_COMPARE_MODELS:
        raise HTTPException(status_code=400, detail=f"Provide 1–{MAX_COMPARE_MODELS} models to compare")

    unknown = [m for m in req.models if m not in MODEL_PROVIDER_MAP]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown model(s): {unknown}")

    provider_keys = await _load_provider_keys(user.id)
    missing = [m for m in req.models if MODEL_PROVIDER_MAP[m] not in provider_keys]
    if missing:
        raise HTTPException(status_code=400, detail=f"Connect a provider key before comparing: {missing}")

    tasks = [
        _run_one(MODEL_PROVIDER_MAP[m], m, req.prompt, req.temperature, req.max_tokens, provider_keys[MODEL_PROVIDER_MAP[m]])
        for m in req.models
    ]
    results = await asyncio.gather(*tasks)
    response.headers["X-Gateway-Decision"] = (
        "strategy=parallel, providers=" + "+".join(dict.fromkeys(r["provider"] for r in results))
    )
    await _log_results(user.id, req.feature_tag, results)
    return {"prompt": req.prompt, "results": results}


async def _log_results(user_id, feature_tag: str | None, results: list[dict]) -> None:
    rows = [
        new_usage_row(
            provider=r["provider"], model=r["model"],
            classification="compare", route_reason="compare mode (router bypassed)",
            input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            cost_usd=r["cost_usd"], latency_ms=r["latency_ms"],
            cache_hit=False, fallback_used=False, error=r["error"],
            user_id=user_id, feature_tag=feature_tag,
        )
        for r in results
    ]
   
    outcomes = await asyncio.gather(*(record_usage(row) for row in rows), return_exceptions=True)
    try:
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                raise outcome
    except Exception:
        logger.exception("could not write compare request logs")
