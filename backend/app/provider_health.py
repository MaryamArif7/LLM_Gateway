
import logging
import math
import secrets
import time
from datetime import datetime, timezone

from app import metrics
from app.config import settings
from app.providers import _PROVIDER_CLASSES
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

PROVIDERS = tuple(_PROVIDER_CLASSES)

MAX_EVENTS = 500       
STATE_TTL = 3600        
PROBE_LOCK_SECONDS = 20

_KIND_CODE = {"ok": "o", "upstream": "u", "client": "c"}

_UPSTREAM_CLASS_NAMES = {
    "APIConnectionError", "APITimeoutError",         
    "ConnectError", "ConnectTimeout", "ReadTimeout",  
    "WriteTimeout", "PoolTimeout", "TimeoutException",
    "RemoteProtocolError", "ReadError",
    "ServiceUnavailable", "DeadlineExceeded",        
}



def _as_http_status(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 100 <= number <= 599 else None


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "http_status", "status", "code"):
        status = _as_http_status(getattr(exc, attr, None))
        if status is not None:
            return status
    response = getattr(exc, "response", None)
    return _as_http_status(getattr(response, "status_code", None)) if response is not None else None


def classify_failure(exc: BaseException) -> str:

    status = _status_of(exc)
    if status is not None:
        return "upstream" if status == 408 or status >= 500 else "client"
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "upstream"
    if any(cls.__name__ in _UPSTREAM_CLASS_NAMES for cls in type(exc).__mro__):
        return "upstream"
  
    return "client"




def _events(p: str) -> str: return f"ph:{p}:ev"
def _last_ok(p: str) -> str: return f"ph:{p}:last_ok"
def _last_fail(p: str) -> str: return f"ph:{p}:last_fail"
def _open(p: str) -> str: return f"cb:{p}:open"
def _tripped(p: str) -> str: return f"cb:{p}:tripped"
def _trips(p: str) -> str: return f"cb:{p}:trips"
def _since(p: str) -> str: return f"cb:{p}:since"
def _probe(p: str) -> str: return f"cb:{p}:probe"


def _event_fields(member: str) -> tuple[float, str]:
    ts, code, _ = member.split(":", 2)
    return float(ts), code


def _state_name(is_open: bool, tripped: bool) -> str:
    return "open" if is_open else ("half_open" if tripped else "closed")




async def record(provider: str, kind: str) -> None:
    try:
        await _record(provider, kind)
    except Exception:
        logger.warning("could not record provider health", exc_info=True)


async def _record(provider: str, kind: str) -> None:
    r = get_redis()
    now = time.time()
    events = _events(provider)

    pipe = r.pipeline()
    pipe.zadd(events, {f"{now:.3f}:{_KIND_CODE[kind]}:{secrets.token_hex(3)}": now})
    pipe.zremrangebyscore(events, 0, now - settings.HEALTH_WINDOW_SECONDS)
    pipe.zremrangebyrank(events, 0, -(MAX_EVENTS + 1))
    pipe.expire(events, settings.HEALTH_WINDOW_SECONDS * 2)
    if kind == "ok":
        pipe.set(_last_ok(provider), f"{now:.0f}", ex=7 * 86400)
    elif kind == "upstream":
        pipe.set(_last_fail(provider), f"{now:.0f}", ex=7 * 86400)
    if kind == "client":
        await pipe.execute()
        return 

   
    pipe.zrangebyscore(events, now - settings.BREAKER_WINDOW_SECONDS, "+inf")
    pipe.get(_since(provider))
    pipe.exists(_tripped(provider))
    pipe.exists(_open(provider))
    pipe.get(_trips(provider))
    members, since, tripped, is_open, trips = (await pipe.execute())[-5:]

    if kind == "ok":
        if tripped:
            await _close(provider, now)
        return

    if is_open:
        return  
    trips = int(trips or 0)
    if tripped:
        await _trip(provider, trips + 1)  
        return

    since_ts = float(since) if since else 0.0
    counted = [code for ts, code in map(_event_fields, members) if ts >= since_ts]
    failures = counted.count("u")
    if (
        failures >= settings.BREAKER_FAILURE_THRESHOLD
        and failures / len(counted) >= settings.BREAKER_FAILURE_RATIO
    ):
        await _trip(provider, 1)


async def _trip(provider: str, trips: int) -> None:
    cooldown = min(settings.BREAKER_COOLDOWN_SECONDS * (2 ** (trips - 1)), settings.BREAKER_MAX_COOLDOWN_SECONDS)
    pipe = get_redis().pipeline()
    pipe.set(_open(provider), "1", px=max(1, int(cooldown * 1000)))
    pipe.set(_tripped(provider), "1", ex=STATE_TTL)
    pipe.set(_trips(provider), trips, ex=STATE_TTL)
    pipe.delete(_probe(provider))
    await pipe.execute()
    metrics.CIRCUIT_TRIPS.labels(provider).inc()
    metrics.CIRCUIT_STATE.labels(provider).set(metrics.CIRCUIT_VALUES["open"])
    logger.warning("circuit opened for %s, cooldown %.1fs (trip %d)", provider, cooldown, trips)


async def _close(provider: str, now: float) -> None:
    pipe = get_redis().pipeline()
    pipe.delete(_open(provider), _tripped(provider), _trips(provider), _probe(provider))
  
    pipe.set(_since(provider), f"{now:.3f}", ex=STATE_TTL)
    await pipe.execute()
    metrics.CIRCUIT_STATE.labels(provider).set(metrics.CIRCUIT_VALUES["closed"])
    logger.info("circuit closed for %s", provider)




async def _read_states(providers: list[str]) -> dict[str, str]:
    pipe = get_redis().pipeline()
    for p in providers:
        pipe.exists(_open(p))
        pipe.exists(_tripped(p))
    res = await pipe.execute()
    return {p: _state_name(bool(res[2 * i]), bool(res[2 * i + 1])) for i, p in enumerate(providers)}


async def provider_states(providers: list[str]) -> dict[str, str]:
    
    try:
        return await _read_states(providers)
    except Exception:
        logger.warning("could not read circuit state, treating all providers as closed", exc_info=True)
        return {p: "closed" for p in providers}


async def claim_probe(provider: str) -> bool:
   
    try:
        return bool(await get_redis().set(_probe(provider), "1", nx=True, ex=PROBE_LOCK_SECONDS))
    except Exception:
        logger.warning("could not claim a probe slot", exc_info=True)
        return True


async def refresh_state_gauges() -> None:
  
    try:
        states = await _read_states(list(PROVIDERS))
    except Exception:
        logger.warning("could not refresh circuit gauges", exc_info=True)
        return
    for provider, state in states.items():
        metrics.CIRCUIT_STATE.labels(provider).set(metrics.CIRCUIT_VALUES[state])




def _iso(ts: str | None) -> str | None:
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat() if ts else None


async def snapshot() -> list[dict]:
   
    now = time.time()
    window = settings.HEALTH_WINDOW_SECONDS
    per_provider = 7

    pipe = get_redis().pipeline()
    for p in PROVIDERS:
        pipe.zrangebyscore(_events(p), now - window, "+inf")
        pipe.get(_last_ok(p))
        pipe.get(_last_fail(p))
        pipe.pttl(_open(p))
        pipe.exists(_tripped(p))
        pipe.get(_trips(p))
        pipe.get(_since(p))
    res = await pipe.execute()

    out = []
    for i, p in enumerate(PROVIDERS):
        members, last_ok, last_fail, pttl, tripped, trips, since = res[i * per_provider:(i + 1) * per_provider]
        since_ts = float(since) if since else 0.0
        codes = [code for ts, code in map(_event_fields, members) if ts >= since_ts]
        ok, upstream, client = codes.count("o"), codes.count("u"), codes.count("c")
        total = len(codes)
        rate = upstream / total if total else None
        state = _state_name(pttl is not None and pttl > 0, bool(tripped))
        retry_in = math.ceil(pttl / 1000) if state == "open" else None

        if state == "open":
            status, reason = "down", f"Circuit open after repeated provider failures. Next probe in about {retry_in}s."
        elif state == "half_open":
            status, reason = "recovering", "Waiting for one probe request to succeed."
        elif total == 0:
            status, reason = "unknown", f"No calls to this provider in the last {max(1, window // 60)} minutes."
        elif upstream >= 2 and rate >= 0.25:
            status, reason = "degraded", f"{upstream} of {total} recent calls failed on the provider side."
        else:
            status, reason = "up", f"{total} recent calls, {upstream} failed on the provider side."

        out.append({
            "provider": p,
            "status": status,
            "circuit": state,
            "reason": reason,
            "window_seconds": window,
            "successes": ok,
            "upstream_failures": upstream,
            "client_failures": client,
            "upstream_failure_rate": round(rate, 3) if rate is not None else None,
            "last_success_at": _iso(last_ok),
            "last_failure_at": _iso(last_fail),
            "retry_in_seconds": retry_in,
            "consecutive_trips": int(trips or 0),
        })
    return out
