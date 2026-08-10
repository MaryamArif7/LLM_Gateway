"""
Compare mode is a deliberately separate code path from /api/chat/stream.
It does NOT go through the router or the fallback chain — the whole point
is to see every requested model's real output side by side, so bypassing
the "pick one" logic is correct here, not a bug. This is also how you'd
generate the ground-truth data to validate the classifier in router/.
"""
import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from app.cache import check_rate_limit
from app.providers import MODEL_PROVIDER_MAP, get_provider
from app.providers.base import ChatMessage
from app.schemas import CompareRequest

router = APIRouter(prefix="/api/compare", tags=["compare"])

MAX_COMPARE_MODELS = 4  # guard against someone passing 20 models and nuking their bill


async def _run_one(provider_name: str, model_name: str, prompt: str, temperature: float, max_tokens: int) -> dict:
    try:
        provider = get_provider(provider_name)
        start = time.perf_counter()
        resp = await provider.chat([ChatMessage(role="user", content=prompt)], model_name, temperature, max_tokens)
        return {
            "provider": provider_name, "model": model_name, "content": resp.content,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": round(resp.cost_usd, 6), "latency_ms": round(resp.latency_ms, 1),
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "provider": provider_name, "model": model_name, "content": None,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "latency_ms": round((time.perf_counter()), 1),
            "error": str(e),
        }


@router.post("")
async def compare(req: CompareRequest, request: Request):
    client_id = request.client.host if request.client else "anonymous"
    # compare is expensive (N calls per request) — charge it against the same
    # per-minute budget as chat so it can't be used to dodge rate limits
    allowed, _ = await check_rate_limit(client_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a bit.")

    if not req.models or len(req.models) > MAX_COMPARE_MODELS:
        raise HTTPException(status_code=400, detail=f"Provide 1–{MAX_COMPARE_MODELS} models to compare")

    unknown = [m for m in req.models if m not in MODEL_PROVIDER_MAP]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown model(s): {unknown}")

    tasks = [
        _run_one(MODEL_PROVIDER_MAP[m], m, req.prompt, req.temperature, req.max_tokens)
        for m in req.models
    ]
    results = await asyncio.gather(*tasks)
    return {"prompt": req.prompt, "results": results}
