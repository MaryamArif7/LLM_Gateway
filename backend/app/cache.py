
import hashlib
import json
import time

from app.config import settings
from app.redis_client import get_redis


def fingerprint(model: str, messages: list[dict], temperature: float) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_cached_response(key: str) -> dict | None:
    r = get_redis()
    raw = await r.get(f"cache:{key}")
    return json.loads(raw) if raw else None


async def set_cached_response(key: str, value: dict) -> None:
    r = get_redis()
    await r.set(f"cache:{key}", json.dumps(value), ex=settings.CACHE_TTL_SECONDS)


async def check_rate_limit(identifier: str) -> tuple[bool, int]:

    r = get_redis()
    window = int(time.time() // 60)
    key = f"ratelimit:{identifier}:{window}"

    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)

    remaining = max(0, settings.RATE_LIMIT_PER_MINUTE - count)
    allowed = count <= settings.RATE_LIMIT_PER_MINUTE
    return allowed, remaining
