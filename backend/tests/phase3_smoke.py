"""
Phase 3 smoke test: prompt versions and experiments.

Runs against a real Postgres. Redis and the model providers are faked, so no
keys or money are involved. Use a throwaway database, the test creates users and rows.

    pip install fakeredis
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/llmgateway_test python -m tests.phase3_smoke
"""
import asyncio
import json
import os
import uuid
from collections import Counter

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
# The test sends well over 20 chats a minute for one user, which the real rate limiter would reject.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import fakeredis.aioredis  # noqa: E402
import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app import redis_client  # noqa: E402

redis_client._pool = fakeredis.aioredis.FakeRedis(decode_responses=True)

import app.providers as providers  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.experiments import bucket_for, pick_variant  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ExperimentAssignment, RequestLog  # noqa: E402
from app.prompts import MissingVariables, render_template, template_variables  # noqa: E402
from app.providers.base import BaseProvider, ProviderResponse, StreamChunk  # noqa: E402

SEEN: list[tuple[str, list[dict]]] = []  # what each provider call received


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def estimate_cost(self, input_tokens, output_tokens, model):
        return input_tokens * 1e-6 + output_tokens * 2e-6

    async def chat(self, messages, model, temperature=0.7, max_tokens=1024):
        return ProviderResponse("hi", 100, 50, model, self.name, 12.0, 0.0002)

    async def chat_stream(self, messages, model, temperature=0.7, max_tokens=1024):
        if self.api_key.startswith("bad"):
            raise RuntimeError("boom")
        SEEN.append((model, [{"role": m.role, "content": m.content} for m in messages]))
        yield StreamChunk(delta="hello ")
        yield StreamChunk(delta="world")
        yield StreamChunk(delta="", finished=True, input_tokens=100, output_tokens=50, cost_usd=0.0002, latency_ms=12.0)


for _name in list(providers._PROVIDER_CLASSES):
    providers._PROVIDER_CLASSES[_name] = FakeProvider


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = block.strip().split("\n")
        ev = next((l[6:].strip() for l in lines if l.startswith("event:")), None)
        data = next((l[5:].strip() for l in lines if l.startswith("data:")), None)
        if ev and data:
            events.append((ev, json.loads(data)))
    return events


passed = 0


def check(condition, label):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"  ok  {label}")


def unit_tests():
    print("template rendering")
    check(template_variables("Hi {{ name }}, {{tone}} and {{name}} again") == ["name", "tone"], "variables listed once each, in order")
    check(render_template("Hi {{ name }}!", {"name": "Sam"}) == "Hi Sam!", "spaces inside the braces are allowed")
    check(render_template("{{a}}", {"a": "{{b}}", "b": "X"}) == "{{b}}", "a value that looks like a placeholder is not expanded")
    check(render_template("{{n}} items", {"n": 3}) == "3 items", "numbers are rendered as text")
    check(render_template("no placeholders", {"unused": 1}) == "no placeholders", "extra variables are ignored")
    try:
        render_template("{{a}} {{b}} {{c}}", {"b": 1})
        check(False, "missing variables raise")
    except MissingVariables as e:
        check(e.names == ["a", "c"], "missing variables are named")

    print("bucket assignment")
    exp_id = uuid.uuid4()
    check(bucket_for(exp_id, "u1") == bucket_for(exp_id, "u1"), "same subject gets the same bucket every time")
    check(bucket_for(exp_id, "u1") != bucket_for(uuid.uuid4(), "u1") or bucket_for(exp_id, "u2") != bucket_for(uuid.uuid4(), "u2"),
          "buckets depend on the experiment, not only the subject")
    counts = Counter(bucket_for(exp_id, f"user-{i}") // 10 for i in range(10_000))
    check(all(800 < n < 1200 for n in counts.values()), "10,000 subjects spread evenly over the buckets")
    seventy = [{"name": "a", "percent": 70}, {"name": "b", "percent": 30}]
    check(pick_variant(seventy, 0)["name"] == "a" and pick_variant(seventy, 69)["name"] == "a", "buckets 0 to 69 are the 70% variant")
    check(pick_variant(seventy, 70)["name"] == "b" and pick_variant(seventy, 99)["name"] == "b", "buckets 70 to 99 are the 30% variant")
    share = sum(pick_variant(seventy, bucket_for(exp_id, f"s{i}"))["name"] == "a" for i in range(10_000)) / 10_000
    check(0.67 < share < 0.73, f"a 70/30 split gives about 70% (got {share:.1%})")


async def main():
    unit_tests()
    await init_db()

    async with SessionLocal() as s:
        cols = {r[0] for r in await s.execute(text("select column_name from information_schema.columns where table_name='request_logs'"))}
        check({"experiment_id", "variant", "prompt_name", "prompt_version"} <= cols, "migration added the request_logs columns")
        tables = {r[0] for r in await s.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
        check({"prompts", "experiments", "experiment_assignments"} <= tables, "new tables exist")
    await init_db()
    check(True, "init_db is safe to run twice")

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

        async def chat(h, text_="What is 2+2?", **extra):
            r = await c.post("/api/chat/stream", json={"messages": [{"role": "user", "content": text_}], **extra}, headers=h)
            return r, (parse_sse(r.text) if r.status_code == 200 else [])

        def metas(ev):
            return [d for e, d in ev if e == "meta"]

        A = await signup("a")
        B = await signup("b")
        for h in (A, B):
            await connect(h, "openai", "good-openai-key")
            await connect(h, "anthropic", "good-anthropic-key")

        print("access control")
        for method, path in [("get", "/api/prompts"), ("post", "/api/prompts"), ("get", "/api/prompts/x"),
                             ("get", "/api/prompts/x/versions"), ("post", "/api/prompts/x/versions"),
                             ("get", "/api/experiments"), ("post", "/api/experiments"),
                             ("get", f"/api/experiments/{uuid.uuid4()}/results"), ("get", "/api/models")]:
            r = await getattr(c, method)(path)
            check(r.status_code == 401, f"{method.upper()} {path} needs a key")

        print("models list")
        models = (await c.get("/api/models", headers=A)).json()
        check(any(m["model"] == "gpt-4o" and m["connected"] for m in models), "connected provider shows as connected")

        print("prompts")
        tpl1 = "You are a {{tone}} assistant for {{company}}."
        r = await c.post("/api/prompts", json={"name": "Support-Greeting", "template": tpl1}, headers=A)
        check(r.status_code == 200 and r.json()["version"] == 1, "create starts at version 1")
        check(r.json()["name"] == "support-greeting", "names are lowercased")
        check(r.json()["variables"] == ["tone", "company"], "variables are detected")
        check((await c.post("/api/prompts", json={"name": "support-greeting", "template": "x"}, headers=A)).status_code == 409, "duplicate name is a 409")
        check((await c.post("/api/prompts", json={"name": "Bad Name!", "template": "x"}, headers=A)).status_code == 422, "invalid name is a 422")
        check((await c.post("/api/prompts", json={"name": "other", "template": ""}, headers=A)).status_code == 422, "empty template is a 422")
        check((await c.post("/api/prompts", json={"name": "other", "template": "x", "target_model": "nope"}, headers=A)).status_code == 400, "unknown target model is a 400")

        tpl2 = "Be {{tone}}. You work for {{company}}. Keep answers short."
        r = await c.post("/api/prompts/support-greeting/versions", json={"template": tpl2, "target_model": "gpt-4o"}, headers=A)
        check(r.status_code == 200 and r.json()["version"] == 2, "publishing makes version 2")
        latest = (await c.get("/api/prompts/support-greeting", headers=A)).json()
        check(latest["version"] == 2 and latest["template"] == tpl2, "GET returns the latest version")
        pinned = (await c.get("/api/prompts/support-greeting", params={"version": 1}, headers=A)).json()
        check(pinned["version"] == 1 and pinned["template"] == tpl1, "?version=1 returns the old text unchanged")
        history = (await c.get("/api/prompts/support-greeting/versions", headers=A)).json()
        check([v["version"] for v in history] == [2, 1], "history is newest first")
        check((await c.get("/api/prompts/support-greeting", params={"version": 9}, headers=A)).status_code == 404, "unknown version is a 404")
        check((await c.get("/api/prompts/nope", headers=A)).status_code == 404, "unknown prompt is a 404")
        check((await c.post("/api/prompts/nope/versions", json={"template": "x"}, headers=A)).status_code == 404, "publishing to an unknown prompt is a 404")

        listing = (await c.get("/api/prompts", headers=A)).json()
        row = next(p for p in listing if p["name"] == "support-greeting")
        check(row["version"] == 2 and row["version_count"] == 2, "list shows the latest version and the version count")
        check((await c.get("/api/prompts/support-greeting", headers=B)).status_code == 404, "another user cannot see my prompt")
        check((await c.post("/api/prompts", json={"name": "support-greeting", "template": "mine"}, headers=B)).status_code == 200, "another user can reuse the same name")
        check((await c.get("/api/prompts", headers=B)).json()[0]["template"] == "mine", "and gets their own text back")

        await c.post("/api/prompts", json={"name": "racy", "template": "v1"}, headers=A)
        rs = await asyncio.gather(*[c.post("/api/prompts/racy/versions", json={"template": f"t{i}"}, headers=A) for i in range(6)])
        check(all(r.status_code in (200, 409) for r in rs), "simultaneous publishes never give a 500")
        vs = [v["version"] for v in (await c.get("/api/prompts/racy/versions", headers=A)).json()]
        check(len(vs) == len(set(vs)), "version numbers stay unique under a race")

        print("chat with a prompt")
        vars_ = {"tone": "friendly", "company": "Acme"}
        SEEN.clear()
        r, ev = await chat(A, "Hello", prompt="support-greeting", prompt_version=1, variables=vars_)
        check(r.status_code == 200, "chat with a pinned prompt works")
        model, sent = SEEN[-1]
        check(sent[0] == {"role": "system", "content": "You are a friendly assistant for Acme."}, "version 1 text is rendered into a system message")
        check(sent[-1] == {"role": "user", "content": "Hello"}, "the user message follows it")
        check(metas(ev)[-1]["prompt"] == {"name": "support-greeting", "version": 1}, "meta event reports the prompt and version")

        SEEN.clear()
        r, ev = await chat(A, "Hello", prompt="support-greeting", variables=vars_)
        model, sent = SEEN[-1]
        check(sent[0]["content"] == "Be friendly. You work for Acme. Keep answers short.", "no version means the latest")
        check(model == "gpt-4o", "the prompt's target model is used when nothing else pins one")
        r, ev = await chat(A, "Hello", prompt="support-greeting", variables=vars_, model="gpt-4o-mini")
        check(metas(ev)[-1]["model"] == "gpt-4o-mini", "a model in the request beats the prompt's target model")

        r, ev = await chat(A, "Hello", prompt="support-greeting", variables=vars_)
        check(metas(ev)[0]["cache_hit"] is True, "same prompt and variables is a cache hit")
        r, ev = await chat(A, "Hello", prompt="support-greeting", variables={"tone": "formal", "company": "Acme"})
        check(metas(ev)[0]["cache_hit"] is False, "different variables are not a cache hit")

        r, ev = await chat(A, "Hello", prompt="support-greeting", variables={"tone": "x"})
        check(r.status_code == 400 and "company" in r.json()["detail"], "missing variables give a 400 that names them")
        r, ev = await chat(A, "Hello", prompt="nope")
        check(r.status_code == 404, "unknown prompt gives a 404")
        r, ev = await chat(B, "Hello", prompt="support-greeting", prompt_version=2, variables=vars_)
        check(r.status_code == 404, "version 2 of my prompt does not exist for another user")
        r, ev = await chat(A, "Hello", model="not-a-model")
        check(r.status_code == 400, "an unknown model is a 400, not a crash")

        async with SessionLocal() as s:
            row = (await s.execute(select(RequestLog).where(RequestLog.prompt_name == "support-greeting").order_by(RequestLog.created_at))).scalars().first()
        check(row is not None and row.prompt_version == 1 and row.experiment_id is None, "the request log records prompt name and version")

        print("experiment validation")
        def exp_body(**over):
            body = {"name": "Greeting test", "feature_tag": "greeting_test", "variants": [
                {"name": "control", "percent": 50},
                {"name": "treatment", "percent": 50, "model": "gpt-4o", "prompt_name": "support-greeting"},
            ]}
            body.update(over)
            return body

        async def make(body, h=A):
            return await c.post("/api/experiments", json=body, headers=h)

        v = lambda *vs: {"variants": list(vs)}  # noqa: E731
        check((await make(exp_body(**v({"name": "a", "percent": 100})))).status_code == 422, "one variant is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 0, "model": "gpt-4o"}, {"name": "b", "percent": 100})))).status_code == 422, "0 percent is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 60}, {"name": "b", "percent": 30, "model": "gpt-4o"})))).status_code == 400, "percentages must add up to 100")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "a", "percent": 50, "model": "gpt-4o"})))).status_code == 400, "duplicate variant names are rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "b", "percent": 50, "model": "nope"})))).status_code == 400, "unknown model is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "b", "percent": 50, "prompt_name": "missing"})))).status_code == 400, "unknown prompt is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "b", "percent": 50, "prompt_name": "support-greeting", "prompt_version": 7})))).status_code == 400, "unknown prompt version is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "b", "percent": 50, "prompt_version": 1})))).status_code == 400, "prompt_version without a prompt_name is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50, "model": "gpt-4o"}, {"name": "b", "percent": 50, "model": "gpt-4o"})))).status_code == 400, "two identical variants are rejected")
        check((await make(exp_body(feature_tag="Bad Tag"))).status_code == 422, "bad feature tag is rejected")
        check((await make(exp_body(**v({"name": "a", "percent": 50}, {"name": "b", "percent": 50, "prompt_name": "racy"})), B)).status_code == 400,
              "a prompt that only another user has cannot be used in my experiment")

        print("running an experiment")
        r = await make(exp_body())
        check(r.status_code == 200 and r.json()["status"] == "active", "valid experiment is created")
        exp = r.json()
        treat = next(x for x in exp["variants"] if x["name"] == "treatment")
        check(treat["prompt_version"] == 2, "a missing prompt version is pinned to the latest at creation")
        check((await make(exp_body())).status_code == 409, "second running experiment on the same tag is a 409")
        await c.post("/api/prompts/support-greeting/versions", json={"template": "Version three {{tone}} {{company}}"}, headers=A)
        check((await c.get(f"/api/experiments/{exp['id']}", headers=A)).json()["variants"][1]["prompt_version"] == 2, "publishing a newer prompt does not change a running experiment")
        check((await c.get(f"/api/experiments/{exp['id']}", headers=B)).status_code == 404, "another user cannot read my experiment")
        check((await c.get("/api/experiments/not-a-uuid", headers=A)).status_code == 422, "a malformed id is a 422")

        print("sticky assignment")
        seen_variants = {}
        for sid in ("sub-1", "sub-2", "sub-3"):
            got = set()
            for i in range(4):
                r, ev = await chat(A, f"Question {sid} {i}", feature_tag="greeting_test", subject_id=sid, variables=vars_)
                got.add(metas(ev)[-1]["variant"])
            check(len(got) == 1, f"{sid} always lands in the same variant")
            seen_variants[sid] = got.pop()
        for sid in ("sub-1", "sub-2", "sub-3"):
            _, ev = await chat(A, "Another one", feature_tag="greeting_test", subject_id=sid, variables=vars_)
            check(metas(ev)[-1]["variant"] == seen_variants[sid], f"{sid} still gets the same variant on a later request")
        async with SessionLocal() as s:
            n = (await s.execute(select(func.count()).select_from(ExperimentAssignment).where(ExperimentAssignment.experiment_id == uuid.UUID(exp["id"])))).scalar_one()
        check(n == 3, "one assignment row per subject, not per request")

        for i in range(40):
            await chat(A, f"Spread {i}", feature_tag="greeting_test", subject_id=f"spread-{i}", variables=vars_)
        async with SessionLocal() as s:
            names = set((await s.execute(select(ExperimentAssignment.variant).where(ExperimentAssignment.experiment_id == uuid.UUID(exp["id"])))).scalars().all())
        check(names == {"control", "treatment"}, "both variants get subjects")

        print("variants change what runs")
        SEEN.clear()
        got_model, got_system, treatment_meta, control_meta = None, None, None, None
        for i in range(60):
            r, ev = await chat(A, f"Effect {i}", feature_tag="greeting_test", subject_id=f"effect-{i}", variables=vars_)
            m = metas(ev)[-1]
            if m["variant"] == "treatment" and got_system is None:
                got_model, got_system, treatment_meta = m["model"], SEEN[-1][1][0], m
            if m["variant"] == "control" and control_meta is None:
                control_meta = m
        check(treatment_meta["prompt"] == {"name": "support-greeting", "version": 2}, "treatment reports its pinned prompt")
        check("prompt" not in control_meta, "control runs with no prompt")
        check(got_model == "gpt-4o", "treatment runs on its model")
        check(got_system["role"] == "system" and got_system["content"] == "Be friendly. You work for Acme. Keep answers short.", "treatment sends its pinned prompt version")

        async def assignment_count():
            async with SessionLocal() as s:
                return (await s.execute(select(func.count()).select_from(ExperimentAssignment).where(ExperimentAssignment.experiment_id == uuid.UUID(exp["id"])))).scalar_one()

        subjects_before = await assignment_count()
        got = set()
        for i in range(30):
            r, ev = await chat(A, f"Anon {i}", feature_tag="greeting_test", variables=vars_)
            got.add(metas(ev)[-1]["variant"])
        check(got == {"control", "treatment"}, "with no subject_id both variants show up (random per request)")
        check(await assignment_count() == subjects_before, "requests without a subject_id are not stored as assignments")

        r, ev = await chat(B, "Same tag, other user", feature_tag="greeting_test")
        check("variant" not in metas(ev)[-1], "another user's traffic is not affected by my experiment")
        r, ev = await chat(A, "Different tag", feature_tag="something_else")
        check("variant" not in metas(ev)[-1], "other feature tags are not affected")
        r, ev = await chat(A, "No tag at all")
        check("variant" not in metas(ev)[-1], "untagged requests are not affected")

        print("results")
        res = (await c.get(f"/api/experiments/{exp['id']}/results", headers=A)).json()
        async with SessionLocal() as s:
            db_total = (await s.execute(select(func.count()).select_from(RequestLog).where(RequestLog.experiment_id == uuid.UUID(exp["id"])))).scalar_one()
            db_cache = (await s.execute(select(func.count()).select_from(RequestLog).where(RequestLog.experiment_id == uuid.UUID(exp["id"]), RequestLog.cache_hit.is_(True)))).scalar_one()
            db_cost = (await s.execute(select(func.sum(RequestLog.cost_usd)).where(RequestLog.experiment_id == uuid.UUID(exp["id"])))).scalar_one()
        check(res["total_requests"] == db_total, "total matches the request log")
        rv = {x["name"]: x for x in res["variants"]}
        check(rv["control"]["requests"] + rv["treatment"]["requests"] == db_total, "variant request counts add up")
        check(abs(sum(x["observed_percent"] for x in res["variants"]) - 100) < 0.2, "observed percentages add up to about 100")
        check(sum(x["cache_hits"] for x in res["variants"]) == db_cache and db_cache > 0, "cache hits are counted")
        check(abs(sum(x["cost_usd"] for x in res["variants"]) - db_cost) < 1e-9, "total cost matches the request log")
        check(all(x["avg_latency_ms"] == 12.0 for x in res["variants"]), "average latency ignores cache hits")
        check(all(abs(x["avg_cost_usd"] - 0.0002) < 1e-9 for x in res["variants"]), "average cost ignores cache hits")
        check(all(x["p50_latency_ms"] == 12.0 and x["p95_latency_ms"] == 12.0 for x in res["variants"]), "percentile latencies are reported")
        check(all(x["success_rate"] == 1.0 for x in res["variants"]), "success rate is 100% when nothing failed")
        check(rv["control"]["subjects"] + rv["treatment"]["subjects"] == subjects_before, "subject counts come from the assignments")
        check(all(x["low_sample"] is False for x in res["variants"]) or any(x["requests"] < 30 for x in res["variants"]), "low_sample flag follows the threshold")
        check((await c.get(f"/api/experiments/{exp['id']}/results", headers=B)).status_code == 404, "another user cannot read my results")

        listing = (await c.get("/api/experiments", headers=A)).json()
        check(next(e for e in listing if e["id"] == exp["id"])["requests"] == db_total, "experiment list shows request counts")

        print("fallback shows up in the outcome proxy")
        await c.post("/api/prompts", json={"name": "fb-prompt", "template": "Be brief."}, headers=B)
        fb = await make({"name": "Fallback test", "feature_tag": "fb_test", "variants": [
            {"name": "control", "percent": 50},
            {"name": "claude", "percent": 50, "model": "claude-haiku-4-5-20251001"},
        ]}, B)
        check(fb.status_code == 200, "second user can run an experiment on the same kind of tag")
        await connect(B, "anthropic", "bad-anthropic-key")
        for i in range(40):
            await chat(B, f"Fallback {i}", feature_tag="fb_test", subject_id=f"fb-{i}")
        fres = (await c.get(f"/api/experiments/{fb.json()['id']}/results", headers=B)).json()
        fv = {x["name"]: x for x in fres["variants"]}
        check(fv["claude"]["fallbacks"] > 0 and fv["claude"]["success_rate"] < 1.0, "a variant whose model fails shows fallbacks and a lower success rate")
        check(fv["control"]["fallbacks"] == 0 and fv["control"]["success_rate"] == 1.0, "the other variant is unaffected")

        print("stopping")
        r = await c.post(f"/api/experiments/{exp['id']}/stop", headers=A)
        check(r.json()["status"] == "stopped" and r.json()["stopped_at"], "stop marks the experiment stopped")
        check((await c.post(f"/api/experiments/{exp['id']}/stop", headers=A)).status_code == 200, "stopping twice is harmless")
        r, ev = await chat(A, "After stop", feature_tag="greeting_test", subject_id="sub-1", variables=vars_)
        check("variant" not in metas(ev)[-1], "a stopped experiment no longer applies")
        res2 = (await c.get(f"/api/experiments/{exp['id']}/results", headers=A)).json()
        check(res2["total_requests"] == db_total, "results are kept after stopping")
        check((await make(exp_body())).status_code == 200, "a new experiment can start on the same tag after stopping")
        check((await c.post(f"/api/experiments/{exp['id']}/stop", headers=B)).status_code == 404, "another user cannot stop my experiment")

    print(f"\nall {passed} checks passed")


asyncio.run(main())
