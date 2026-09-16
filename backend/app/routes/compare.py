
import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import get_current_user
from app.cache import check_rate_limit
from app.providers import MODEL_PROVIDER_MAP, get_provider
from app.providers.base import ChatMessage
from app.routes.chat import _load_provider_keys
from app.schemas import CompareRequest
from app.models import User

router = APIRouter(prefix="/api/compare", tags=["compare"])

MAX_COMPARE_MODELS = 4  


async def _run_one(provider_name: str, model_name: str, prompt: str, temperature: float, max_tokens: int, api_key: str) -> dict:
    try:
        provider = get_provider(provider_name, api_key)
        start = time.perf_counter()
        resp = await provider.chat([ChatMessage(role="user", content=prompt)], model_name, temperature, max_tokens)
        return {
            "provider": provider_name, "model": model_name, "content": resp.content,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": round(resp.cost_usd, 6), "latency_ms": round(resp.latency_ms, 1),
            "error": None,
        }
    except Exception as e: 
        return {
            "provider": provider_name, "model": model_name, "content": None,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "latency_ms": round((time.perf_counter()), 1),
            "error": str(e),
        }


@router.post("")
async def compare(req: CompareRequest, request: Request, user: User = Depends(get_current_user)):
    
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
    return {"prompt": req.prompt, "results": results}
