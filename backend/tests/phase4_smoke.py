"""
Phase 4 smoke test: metrics, the routing decision header, provider health and the circuit breaker.

Runs against a real Postgres. Redis and the model providers are faked, so no
keys or money are involved. Use a throwaway database, the test creates users and rows.

    pip install fakeredis
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/llmgateway_test python -m tests.phase4_smoke
"""
import asyncio
import json
import os
import uuid
from collections import Counter

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import fakeredis.aioredis  # noqa: E402
import httpx  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402

from app import provider_health, redis_client  # noqa: E402

redis_client._pool = fakeredis.aioredis.FakeRedis(decode_responses=True)

import app.providers as providers  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.base import BaseProvider, ProviderResponse, StreamChunk  # noqa: E402

settings.BREAKER_COOLDOWN_SECONDS = 1  # so the test can wait out a cooldown

HAIKU = "claude-haiku-4-5-20251001"
CALLS: Counter = Counter()  # provider calls, by provider name


class StatusError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _maybe_fail(self):
        CALLS[self.name] += 1
        if self.api_key.startswith("bad503"):
            raise StatusError(503)
        if self.api_key.startswith("bad401"):
            raise StatusError(401)
        if self.api_key.startswith("badtimeout"):
            raise TimeoutError("timed out")

    def estimate_cost(self, input_tokens, output_tokens, model):
        return 0.0002

    async def chat(self, messages, model, temperature=0.7, max_tokens=1024):
        self._maybe_fail()
        return ProviderResponse("hi", 100, 50, model, self.name, 12.0, 0.0002)

    async def chat_stream(self, messages, model, temperature=0.7, max_tokens=1024):
        self._maybe_fail()
        yield StreamChunk(delta="hello ")
        yield StreamChunk(delta="world")
        yield StreamChunk(delta="", finished=True, input_tokens=100, output_tokens=50, cost_usd=0.0002, latency_ms=12.0)


for _name in list(providers._PROVIDER_CLASSES):
    providers._PROVIDER_CLASSES[_name] = type(f"Fake_{_name}", (FakeProvider,), {"name": _name})


def parse_sse(body: str):
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = block.strip().split("\n")
        ev = next((l[6:].strip() for l in lines if l.startswith("event:")), None)
        data = next((l[5:].strip() for l in lines if l.startswith("data:")), None)
        if ev and data:
            events.append((ev, json.loads(data)))
    return events


def val(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def header_parts(value: str) -> dict:
    return dict(part.strip().split("=", 1) for part in value.split(","))


passed = 0


def check(condition, label):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"  ok  {label}")


def unit_tests():
    print("classifying failures")

    class Named(Exception):
        pass

    class APIConnectionError(Exception):  # same class name the openai and anthropic SDKs use
        pass

    class SubTimeout(TimeoutError):
        pass

    for status, expected in [(500, "upstream"), (502, "upstream"), (503, "upstream"), (504, "upstream"),
                             (529, "upstream"), (408, "upstream"),
                             (400, "client"), (401, "client"), (403, "client"), (404, "client"), (429, "client")]:
        check(provider_health.classify_failure(StatusError(status)) == expected, f"HTTP {status} is {expected}")

    class WithResponse(Exception):
        response = type("R", (), {"status_code": 502})()

    check(provider_health.classify_failure(WithResponse()) == "upstream", "a status on exc.response is found")

    class GoogleLike(Exception):
        code = 503

    check(provider_health.classify_failure(GoogleLike()) == "upstream", "a numeric code attribute is read as a status")

    class OpenAIStyle(Exception):
        code = "invalid_api_key"  # a string, not a status

    check(provider_health.classify_failure(OpenAIStyle()) == "client", "a string code is not mistaken for a status")
    check(provider_health.classify_failure(TimeoutError()) == "upstream", "timeouts are upstream")
    check(provider_health.classify_failure(SubTimeout()) == "upstream", "subclasses of timeouts are upstream")
    check(provider_health.classify_failure(ConnectionResetError()) == "upstream", "connection errors are upstream")
    check(provider_health.classify_failure(APIConnectionError()) == "upstream", "SDK connection errors are upstream by class name")
    check(provider_health.classify_failure(ValueError("bug")) == "client", "an unknown error is not blamed on the provider")
    check(provider_health.classify_failure(Named()) == "client", "an exception with no status is not blamed on the provider")


async def main():
    unit_tests()
    await init_db()
    redis = redis_client.get_redis()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:
        run = uuid.uuid4().hex[:8]

        async def signup(tag):
            r = await c.post("/api/auth/signup", params={"email": f"{tag}-{run}@example.com"})
            assert r.status_code == 200, r.text
            return {"Authorization": f"Bearer {r.json()['raw_key']}"}

        async def connect(h, provider, key):
            r = await c.post("/api/provider-keys", json={"provider": provider, "api_key": key}, headers=h)
            assert r.status_code == 200, r.text

        async def chat(h, text_=None, **extra):
            text_ = text_ or f"question {uuid.uuid4().hex}"
            r = await c.post("/api/chat/stream", json={"messages": [{"role": "user", "content": text_}], **extra}, headers=h)
            return r, (parse_sse(r.text) if r.status_code == 200 else [])

        async def health(h, provider):
            r = await c.get("/api/health/providers", headers=h)
            assert r.status_code == 200, r.text
            return next(p for p in r.json()["providers"] if p["provider"] == provider)

        A = await signup("a")
        await connect(A, "openai", "good-openai")
        await connect(A, "anthropic", "good-anthropic")

        print("http metrics")
        await c.get("/health")
        r = await c.get("/metrics")
        check(r.status_code == 200 and r.headers["content-type"].startswith("text/plain"), "GET /metrics serves the Prometheus text format")
        check('gateway_http_requests_total{method="GET",path="/health",status="200"}' in r.text, "requests are counted by method, route and status")
        check("/metrics" not in "".join(l for l in r.text.splitlines() if l.startswith("gateway_http_requests_total")), "scrapes are not counted")
        await c.get(f"/api/experiments/{uuid.uuid4()}", headers=A)
        await c.get("/definitely-not-a-route")
        text = (await c.get("/metrics")).text
        check('path="/api/experiments/{experiment_id}"' in text, "the label is the route template, not the raw URL")
        check("definitely-not-a-route" not in text and 'path="unmatched"' in text, "unknown URLs share one 'unmatched' label")
        check(val("gateway_http_request_duration_seconds_count", method="GET", path="/health") >= 1, "durations are recorded")

        settings.METRICS_TOKEN = "s3cret"
        check((await c.get("/metrics")).status_code == 401, "with a token set, no header is a 401")
        check((await c.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401, "a wrong token is a 401")
        check((await c.get("/metrics", headers={"Authorization": "Bearer s3cret"})).status_code == 200, "the right token works")
        settings.METRICS_TOKEN = ""

        r = await c.get("/health", headers={"Origin": "http://localhost:3000"})
        check("x-gateway-decision" in r.headers.get("access-control-expose-headers", "").lower(), "CORS exposes the decision header to browsers")

        print("decision header and chat metrics")
        await redis.flushall()
        miss0 = val("gateway_cache_lookups_total", result="miss")
        hit0 = val("gateway_cache_lookups_total", result="hit")
        prompt = f"cache me {uuid.uuid4().hex}"
        r, ev = await chat(A, prompt)
        check(r.status_code == 200, "chat works")
        h = header_parts(r.headers["x-gateway-decision"])
        check(set(h) == {"provider", "model", "strategy", "route"} and h["strategy"] == "direct", "the header names provider, model, strategy and route")
        meta = [d for e, d in ev if e == "meta"][-1]
        check(h["provider"] == meta["provider"] and h["model"] == meta["model"] and h["route"] == meta["classification"], "the header matches the meta event")
        check([e for e, _ in ev][0] == "meta" and [e for e, _ in ev][-1] == "done", "the stream still starts with meta and ends with done")
        check(val("gateway_requests_total", endpoint="chat", provider=h["provider"], model=h["model"], outcome="success", fallback="false") >= 1, "a successful request is counted")
        check(val("gateway_provider_attempts_total", provider=h["provider"], model=h["model"], result="success") >= 1, "the provider call is counted")
        check(val("gateway_provider_duration_seconds_count", provider=h["provider"], model=h["model"]) >= 1, "provider latency is recorded")
        check(val("gateway_cache_lookups_total", result="miss") == miss0 + 1, "a cache miss is counted")

        attempts0 = val("gateway_provider_attempts_total", provider=h["provider"], model=h["model"], result="success")
        r, ev = await chat(A, prompt)
        h2 = header_parts(r.headers["x-gateway-decision"])
        check(h2["strategy"] == "cache", "a cached answer says strategy=cache")
        check(val("gateway_cache_lookups_total", result="hit") == hit0 + 1, "a cache hit is counted")
        check(val("gateway_provider_attempts_total", provider=h["provider"], model=h["model"], result="success") == attempts0, "a cache hit makes no provider call")

        r = await c.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "x"}], "prompt": "nope"}, headers=A)
        check(r.status_code == 404 and "x-gateway-decision" not in r.headers, "an error before routing has no decision header")

        print("fallback")
        B = await signup("b")
        await connect(B, "openai", "good-openai")
        await connect(B, "anthropic", "bad503-anthropic")
        await redis.flushall()
        up0 = val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="upstream_error")
        r, ev = await chat(B, model=HAIKU)
        h = header_parts(r.headers["x-gateway-decision"])
        check(h["strategy"] == "fallback" and h["provider"] == "openai", "the header says the request was served by a fallback")
        check([e for e, _ in ev][:4] == ["meta", "provider_error", "meta", "delta"], "the failed attempt and the fallback are both in the stream, in order")
        check(val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="upstream_error") == up0 + 1, "the failed attempt is counted as an upstream error")
        check(val("gateway_requests_total", endpoint="chat", provider=h["provider"], model=h["model"], outcome="success", fallback="true") >= 1, "the request is counted as served by fallback")
        st = await health(B, "anthropic")
        check(st["upstream_failures"] == 1 and st["circuit"] == "closed", "one failure is recorded and the breaker stays closed")

        print("key problems never open the breaker")
        await redis.flushall()
        C = await signup("c")
        await connect(C, "openai", "good-openai")
        await connect(C, "anthropic", "bad401-anthropic")
        client0 = val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="client_error")
        for _ in range(8):
            r, _ev = await chat(C, model=HAIKU)
            check_ok = r.status_code == 200 and "skipped" not in r.headers["x-gateway-decision"]
            assert check_ok
        check(val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="client_error") == client0 + 8, "8 bad key calls are counted as client errors")
        st = await health(C, "anthropic")
        check(st["circuit"] == "closed" and st["client_failures"] == 8 and st["upstream_failures"] == 0, "8 bad key calls leave the breaker closed")
        check(st["status"] == "up", "and the provider is not shown as down")
        for _ in range(10):
            await provider_health.record("anthropic", "client")
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "closed", "even many more client errors do not trip it")

        print("intermittent failures do not trip it")
        await redis.flushall()
        for _ in range(20):
            await provider_health.record("openai", "ok")
        for _ in range(5):
            await provider_health.record("openai", "upstream")
        check((await provider_health.provider_states(["openai"]))["openai"] == "closed", "5 failures among 25 calls stay under the failure ratio")

        print("the breaker opens, skips, probes and recovers")
        await redis.flushall()
        D = await signup("d")
        await connect(D, "openai", "good-openai")
        await connect(D, "anthropic", "bad503-anthropic")
        trips0 = val("gateway_circuit_trips_total", provider="anthropic")
        for _ in range(4):
            await chat(D, model=HAIKU)
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "closed", "4 failures are not enough")
        await chat(D, model=HAIKU)
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "open", "the 5th upstream failure opens the breaker")
        check(val("gateway_circuit_trips_total", provider="anthropic") == trips0 + 1, "the trip is counted")
        st = await health(D, "anthropic")
        check(st["status"] == "down" and st["circuit"] == "open" and st["retry_in_seconds"] >= 1, "the status page says down, with a retry time")
        gauge_text = (await c.get("/metrics")).text
        check('gateway_circuit_state{provider="anthropic"} 2.0' in gauge_text, "the state gauge reads open (2) on a scrape")
        check('gateway_circuit_state{provider="openai"} 0.0' in gauge_text, "and closed (0) for a healthy provider")

        CALLS.clear()
        skipped0 = val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="skipped_open")
        r, ev = await chat(D, model=HAIKU)
        h = header_parts(r.headers["x-gateway-decision"])
        check(CALLS["anthropic"] == 0, "an open provider is not called")
        check(h["strategy"] == "fallback" and h["provider"] == "openai" and h.get("skipped") == "anthropic", "the header says who was skipped")
        check("provider_error" not in [e for e, _ in ev], "the skipped provider adds no error to the stream")
        check(val("gateway_provider_attempts_total", provider="anthropic", model=HAIKU, result="skipped_open") == skipped0 + 1, "the skip is counted")

        await asyncio.sleep(1.2)
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "half_open", "after the cooldown the breaker is half open")
        st = await health(D, "anthropic")
        check(st["status"] == "recovering", "the status page says recovering")

        CALLS.clear()
        r, ev = await chat(D, model=HAIKU)
        check(CALLS["anthropic"] == 1, "exactly one probe call goes through")
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "open", "a failed probe opens the breaker again")
        st = await health(D, "anthropic")
        check(st["consecutive_trips"] == 2, "and counts a second trip")
        r, ev = await chat(D, model=HAIKU)
        check("skipped=anthropic" in r.headers["x-gateway-decision"], "requests are skipped again straight away")

        await connect(D, "anthropic", "good-anthropic")  # the user fixes their key, the provider is fine
        await asyncio.sleep(2.2)  # the second cooldown is twice as long
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "half_open", "the backed off cooldown ends")
        check(await provider_health.claim_probe("anthropic") is True and await provider_health.claim_probe("anthropic") is False,
              "only one caller can hold the probe slot")
        await redis.delete("cb:anthropic:probe")
        CALLS.clear()
        r, ev = await chat(D, model=HAIKU)
        h = header_parts(r.headers["x-gateway-decision"])
        check(CALLS["anthropic"] == 1 and h["provider"] == "anthropic" and h["strategy"] == "direct", "a successful probe serves the request")
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "closed", "and closes the breaker")
        st = await health(D, "anthropic")
        check(st["status"] == "up" and st["circuit"] == "closed" and st["consecutive_trips"] == 0, "the status page is back to up")
        check('gateway_circuit_state{provider="anthropic"} 0.0' in (await c.get("/metrics")).text, "the gauge is back to closed")
        for _ in range(4):
            await provider_health.record("anthropic", "upstream")
        check((await provider_health.provider_states(["anthropic"]))["anthropic"] == "closed", "failures from before the outage do not count towards the next trip")

        print("every provider open")
        await redis.flushall()
        for p in ("openai", "anthropic"):
            for _ in range(5):
                await provider_health.record(p, "upstream")
        states = await provider_health.provider_states(["openai", "anthropic"])
        check(set(states.values()) == {"open"}, "both providers are open")
        CALLS.clear()
        r, ev = await chat(D, model=HAIKU)
        check(r.status_code == 200 and CALLS["anthropic"] == 1, "with everything open the gateway still tries the first provider")
        check("skipped" not in r.headers["x-gateway-decision"], "and nothing is reported as skipped")

        print("status levels")
        await redis.flushall()
        check((await health(A, "gemini"))["status"] == "unknown", "a provider with no recent calls is unknown")
        for _ in range(6):
            await provider_health.record("gemini", "ok")
        for _ in range(3):
            await provider_health.record("gemini", "upstream")
        st = await health(A, "gemini")
        check(st["status"] == "degraded" and st["upstream_failure_rate"] == 0.333, "3 failures in 9 calls is degraded")
        await redis.flushall()
        for _ in range(10):
            await provider_health.record("gemini", "ok")
        await provider_health.record("gemini", "upstream")
        check((await health(A, "gemini"))["status"] == "up", "a single failure among many is still up")
        r = await c.get("/api/health/providers", headers=A)
        body = r.json()
        check([p["provider"] for p in body["providers"]] == list(provider_health.PROVIDERS) and body["updated_at"], "the response lists every provider")
        check((await health(A, "gemini"))["last_success_at"] and (await health(A, "gemini"))["last_failure_at"], "last success and last failure times are reported")
        check((await c.get("/api/health/providers")).status_code == 401, "the status endpoint needs a key")
        check((await c.get("/health")).json() == {"status": "ok"}, "plain liveness still works with no key")

        print("compare mode")
        await redis.flushall()
        E = await signup("e")
        await connect(E, "openai", "good-openai")
        await connect(E, "anthropic", "bad401-anthropic")
        ok0 = val("gateway_requests_total", endpoint="compare", provider="openai", model="gpt-4o-mini", outcome="success", fallback="false")
        err0 = val("gateway_requests_total", endpoint="compare", provider="anthropic", model=HAIKU, outcome="error", fallback="false")
        r = await c.post("/api/compare", json={"prompt": "hello", "models": ["gpt-4o-mini", HAIKU]}, headers=E)
        check(r.status_code == 200 and r.headers["x-gateway-decision"] == "strategy=parallel, providers=openai+anthropic", "compare sets its own decision header")
        check(val("gateway_requests_total", endpoint="compare", provider="openai", model="gpt-4o-mini", outcome="success", fallback="false") == ok0 + 1, "a compare success is counted")
        check(val("gateway_requests_total", endpoint="compare", provider="anthropic", model=HAIKU, outcome="error", fallback="false") == err0 + 1, "a compare failure is counted")
        check((await health(E, "anthropic"))["client_failures"] == 1 and (await health(E, "anthropic"))["circuit"] == "closed", "a compare key error is a client failure and does not trip anything")

        print("every provider failing")
        await redis.flushall()
        F = await signup("f")
        await connect(F, "openai", "bad503-openai")
        await connect(F, "anthropic", "bad503-anthropic")
        none0 = val("gateway_requests_total", endpoint="chat", provider="none", model="none", outcome="error", fallback="true")
        r, ev = await chat(F, model=HAIKU)
        check(r.status_code == 200 and header_parts(r.headers["x-gateway-decision"])["strategy"] == "failed", "total failure says strategy=failed")
        check(header_parts(r.headers["x-gateway-decision"])["provider"] == "none", "and names no provider")
        check([e for e, _ in ev][-1] == "error" and [e for e, _ in ev].count("provider_error") == 2, "the stream has both provider errors, then the final error")
        check(val("gateway_requests_total", endpoint="chat", provider="none", model="none", outcome="error", fallback="true") == none0 + 1, "the failed request is counted")

        print("redis trouble never breaks chat")
        await redis.flushall()
        original = provider_health.get_redis

        def broken():
            raise ConnectionError("redis is down")

        provider_health.get_redis = broken
        try:
            r, ev = await chat(A)
            check(r.status_code == 200 and [e for e, _ in ev][-1] == "done", "chat still works when health tracking cannot reach Redis")
            check((await c.get("/api/health/providers", headers=A)).status_code == 503, "the status endpoint says 503 instead of guessing")
            check((await c.get("/metrics")).status_code == 200, "a metrics scrape still works")
        finally:
            provider_health.get_redis = original

    print(f"\nall {passed} checks passed")


asyncio.run(main())
