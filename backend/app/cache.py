"""
Two Redis-backed concerns live here on purpose: response caching and rate
limiting. Both are "protect the gateway / protect the wallet" features, and
both are cheap single-key Redis ops, so they share a module rather than being
split across the codebase.
"""
import hashlib
import json
import time

from app.config import settings
from app.redis_client import get_redis


def fingerprint(model: str, messages: list[dict], temperature: float) -> str:
    """SHA-256 fingerprint of the exact request shape, for cache keys."""
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
    """
    Fixed-window rate limiter keyed per-minute.
    Returns (allowed, remaining). Not perfectly smooth (window edges can let
    ~2x through briefly) but simple, fast, and good enough for a v1 — a
    sliding-window/token-bucket upgrade is a natural next iteration.
    """
    r = get_redis()
    window = int(time.time() // 60)
    key = f"ratelimit:{identifier}:{window}"

    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)

    remaining = max(0, settings.RATE_LIMIT_PER_MINUTE - count)
    allowed = count <= settings.RATE_LIMIT_PER_MINUTE
    return allowed, remaining
