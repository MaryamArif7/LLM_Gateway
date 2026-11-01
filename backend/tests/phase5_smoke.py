
import asyncio
import base64
import json
import os
import time
import uuid

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import fakeredis.aioredis
import httpx  
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer 
from confluent_kafka import Producer as MockCluster  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app import redis_client  # noqa: E402

redis_client._pool = fakeredis.aioredis.FakeRedis(decode_responses=True)

import app.consumer.worker as worker_module  # noqa: E402
import app.providers as providers  # noqa: E402
from app import usage_events  # noqa: E402
from app.config import settings  # noqa: E402
from app.consumer.worker import UsageConsumer  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Conversation, RequestLog  # noqa: E402
from app.providers.base import BaseProvider, ProviderResponse, StreamChunk  # noqa: E402
from app.usage_events import (  # noqa: E402
    EventError, decode_event, encode_event, insert_directly, new_usage_row, normalize_row, publisher,
)

# A Kafka protocol endpoint on localhost for as long as this object lives.
_mock = MockCluster({"test.mock.num.brokers": 1})
BROKERS = [f"{b.host}:{b.port}" for b in _mock.list_topics(timeout=10).brokers.values()]

RUN = uuid.uuid4().hex[:8]
settings.KAFKA_USAGE_TOPIC = f"usage-events-{RUN}"
settings.KAFKA_DLQ_TOPIC = f"usage-events-dlq-{RUN}"
settings.KAFKA_CONSUMER_GROUP = f"usage-consumer-{RUN}"
settings.KAFKA_TOPIC_PARTITIONS = 3
worker_module.RETRY_START = 0.2


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def estimate_cost(self, input_tokens, output_tokens, model):
        return 0.0002

    async def chat(self, messages, model, temperature=0.7, max_tokens=1024):
        return ProviderResponse("hi", 100, 50, model, self.name, 12.0, 0.0002)

    async def chat_stream(self, messages, model, temperature=0.7, max_tokens=1024):
        yield StreamChunk(delta="hello ")
        yield StreamChunk(delta="world")
        yield StreamChunk(delta="", finished=True, input_tokens=100, output_tokens=50, cost_usd=0.0002, latency_ms=12.0)


for _name in list(providers._PROVIDER_CLASSES):
    providers._PROVIDER_CLASSES[_name] = type(f"Fake_{_name}", (FakeProvider,), {"name": _name})


def val(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


passed = 0


def check(condition, label):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"  ok  {label}")


async def wait_until(predicate, timeout=30.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(step)
    return None


async def rows_of(user_id) -> list:
    async with SessionLocal() as s:
        return list((await s.execute(
            select(RequestLog).where(RequestLog.user_id == user_id).order_by(RequestLog.created_at)
        )).scalars().all())


async def count_of(user_id) -> int:
    async with SessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(RequestLog).where(RequestLog.user_id == user_id))).scalar_one()


async def read_topic(topic, expected, timeout=20.0):
    """Everything on a topic from the start, using a throwaway consumer."""
    consumer = AIOKafkaConsumer(topic, bootstrap_servers=BROKERS, group_id=f"inspect-{uuid.uuid4().hex[:6]}",
                                auto_offset_reset="earliest", enable_auto_commit=False)
    await consumer.start()
    out = []
    try:
        end = time.monotonic() + timeout
        while len(out) < expected and time.monotonic() < end:
            got = await consumer.getmany(timeout_ms=500)
            out.extend(r for rs in got.values() for r in rs)
    finally:
        await consumer.stop()
    return out


def unit_tests():
    print("events")
    uid = uuid.uuid4()
    row = new_usage_row(user_id=uid, provider="openai", model="gpt-4o", input_tokens=10, route_reason="x" * 400)
    check(isinstance(row["id"], uuid.UUID) and row["created_at"].tzinfo is not None, "a new row has an id and a timezone aware time")
    check(len(row["route_reason"]) == 255, "a long route reason is cut to the column size")
    try:
        new_usage_row(provider="a", model="b", bogus=1)
        check(False, "unknown fields are refused")
    except ValueError:
        check(True, "unknown fields are refused")

    event = decode_event(encode_event(row))
    check(event["v"] == 1 and event["id"] == str(row["id"]) and event["user_id"] == str(uid), "an event carries a version and string ids")
    back = normalize_row(event)
    check(back["id"] == row["id"] and back["user_id"] == uid and back["created_at"] == row["created_at"], "decoding gives back the same row")
    check(back["cost_usd"] == 0.0 and back["cache_hit"] is False, "missing numbers and flags get defaults")
    check("bogus" not in normalize_row({**event, "bogus": 1}), "a field the consumer does not know is ignored")

    for label, raw, expected in [
        ("an empty message", b"", "empty"),
        ("text that is not JSON", b"hello", "not valid JSON"),
        ("a JSON list", b"[1]", "not a JSON object"),
        ("an unknown version", b'{"v": 2}', "unsupported event version"),
        ("no version", b"{}", "unsupported event version"),
    ]:
        try:
            decode_event(raw)
            check(False, f"{label} is rejected")
        except EventError as e:
            check(expected in str(e), f"{label} is rejected")

    for label, change, expected in [
        ("a missing provider", {"provider": None}, "missing field: provider"),
        ("a bad id", {"id": "nope"}, "not a valid uuid"),
        ("a bad time", {"created_at": "yesterday"}, "not a valid time"),
        ("tokens as text", {"input_tokens": "ten"}, "must be a whole number"),
        ("a boolean as cost", {"cost_usd": True}, "must be a number"),
    ]:
        try:
            normalize_row({**event, **change})
            check(False, f"{label} is rejected")
        except EventError as e:
            check(expected in str(e), f"{label} is rejected")


async def main():
    unit_tests()
    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as c:

        async def signup(tag):
            r = await c.post("/api/auth/signup", params={"email": f"{tag}-{RUN}@example.com"})
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {r.json()['raw_key']}"}
            await c.post("/api/provider-keys", json={"provider": "openai", "api_key": "good"}, headers=h)
            return h

        async def user_id_of(h):
            r = await c.get("/api/usage/logs", headers=h)
            assert r.status_code == 200
            async with SessionLocal() as s:
                from app.models import User
                from app.crypto import hash_gateway_key
                from app.models import ApiKey
                key_hash = hash_gateway_key(h["Authorization"].split()[1])
                return (await s.execute(select(ApiKey.user_id).where(ApiKey.key_hash == key_hash))).scalar_one()

        async def chat(h, text=None, **extra):
            text = text or f"q {uuid.uuid4().hex}"
            r = await c.post("/api/chat/stream", json={"messages": [{"role": "user", "content": text}], **extra}, headers=h)
            assert r.status_code == 200, r.text
            return r

        # ---------------------------------------------------------------- direct mode
        print("without kafka (the default)")
        settings.KAFKA_BOOTSTRAP_SERVERS = ""
        check(not publisher.enabled, "the pipeline is off when no brokers are configured")
        U1 = await signup("direct")
        uid1 = await user_id_of(U1)
        direct0 = val("gateway_usage_events_total", result="direct_db")
        await chat(U1)
        rows = await rows_of(uid1)
        check(len(rows) == 1, "the usage row is in postgres as soon as the request is done")
        check(rows[0].ingested_at is not None and abs((rows[0].ingested_at - rows[0].created_at).total_seconds()) < 5, "ingested_at is set and close to created_at")
        check(val("gateway_usage_events_total", result="direct_db") == direct0 + 1, "the direct write is counted")
        fresh = (await c.get("/api/usage/summary", headers=U1)).json()["freshness"]
        check(fresh["pipeline"] == "direct" and fresh["last_event_at"] and fresh["last_ingest_lag_seconds"] < 5, "the dashboard reports the direct pipeline with almost no delay")

        # ---------------------------------------------------------------- gateway publishes
        print("gateway side, with kafka")
        settings.KAFKA_BOOTSTRAP_SERVERS = ",".join(BROKERS)
        settings.KAFKA_RECONNECT_SECONDS = 0.2
        publisher.kick()
        check(await wait_until(lambda: asyncio.sleep(0, publisher.connected), 15), "the publisher connects in the background")

        U2 = await signup("kafka")
        uid2 = await user_id_of(U2)
        published0 = val("gateway_usage_events_total", result="published")
        sent_at = time.time()
        for i in range(3):
            await chat(U2, f"first batch {i}")
        check(val("gateway_usage_events_total", result="published") == published0 + 3, "three requests, three published events")
        check(await count_of(uid2) == 0, "nothing is written to postgres while the consumer is not running")
        async with SessionLocal() as s:
            convos = (await s.execute(select(func.count()).select_from(Conversation))).scalar_one()
        check(convos >= 3, "the conversation history is still saved straight away")
        check(val("gateway_usage_publish_seconds_count") >= 3, "publish time is recorded")

        events = await read_topic(settings.KAFKA_USAGE_TOPIC, 3)
        mine = [e for e in events if e.key == str(uid2).encode()]
        check(len(mine) == 3, "events are keyed by user id")
        body = json.loads(mine[0].value)
        check(body["v"] == 1 and body["provider"] and body["model"] and body["user_id"] == str(uid2), "an event has a version, provider, model and user")
        check(len({json.loads(e.value)["id"] for e in mine}) == 3, "each event has its own row id")
        fresh = (await c.get("/api/usage/summary", headers=U2)).json()["freshness"]
        check(fresh["pipeline"] == "kafka" and fresh["last_event_at"] is None, "before the consumer runs the dashboard has no rows to show yet")

        # ---------------------------------------------------------------- consumer
        print("consumer")
        gap = time.time() - sent_at
        worker = UsageConsumer()
        task = asyncio.create_task(worker.run())
        got = await wait_until(lambda: _rows_ready(uid2, 3), 40)
        check(got, "the consumer writes the events to postgres")
        rows = await rows_of(uid2)
        check(len(rows) == 3 and worker.stats["inserted"] >= 3, "exactly one row per event")
        check(all(r.created_at.timestamp() >= sent_at - 1 and r.created_at.timestamp() <= sent_at + gap for r in rows), "created_at is when the request happened, not when the row was written")
        check(all((r.ingested_at - r.created_at).total_seconds() > 0.3 for r in rows), "ingested_at is later than created_at")
        fresh = (await c.get("/api/usage/summary", headers=U2)).json()["freshness"]
        check(fresh["last_event_at"] and fresh["last_ingest_lag_seconds"] > 0.3, "the dashboard now reports the delay between a request and its row")
        check(worker.status == "running" and worker.stats["batches"] >= 1, "the consumer reports running and counts its batches")

        # a gateway row and its published twin: one row
        print("repeats are harmless")
        twin = new_usage_row(user_id=uid2, provider="openai", model="gpt-4o", input_tokens=7)
        await insert_directly(twin)
        before = worker.stats["duplicates"]
        await publisher.publish(twin)
        await wait_until(lambda: asyncio.sleep(0, worker.stats["duplicates"] > before), 20)
        check(worker.stats["duplicates"] == before + 1, "an event for a row that already exists is counted as a duplicate")
        check(await count_of(uid2) == 4, "and does not create a second row")

        # restart: offsets were committed, nothing is read twice
        worker.request_stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        worker2 = UsageConsumer()
        task2 = asyncio.create_task(worker2.run())
        await asyncio.sleep(6)
        check(worker2.stats["events"] == 0, "a restarted consumer does not read old events again (offsets were committed)")

        # ---------------------------------------------------------------- poison messages
        print("events that can never be stored")
        valid_a = new_usage_row(user_id=uid2, provider="openai", model="gpt-4o")
        valid_b = new_usage_row(user_id=uid2, provider="openai", model="gpt-4o")
        no_provider = json.loads(encode_event(new_usage_row(user_id=uid2, provider="x", model="y")))
        del no_provider["provider"]
        bad_id = json.loads(encode_event(new_usage_row(user_id=uid2, provider="x", model="y")))
        bad_id["id"] = "not-a-uuid"
        junk = [b"not json at all", b"", b"{}", json.dumps(no_provider).encode(), json.dumps(bad_id).encode()]
        raw = AIOKafkaProducer(bootstrap_servers=BROKERS)
        await raw.start()
        try:
            await raw.send_and_wait(settings.KAFKA_USAGE_TOPIC, encode_event(valid_a), key=b"p")
            for j in junk:
                await raw.send_and_wait(settings.KAFKA_USAGE_TOPIC, j, key=b"p")
            await raw.send_and_wait(settings.KAFKA_USAGE_TOPIC, encode_event(valid_b), key=b"p")
        finally:
            await raw.stop()
        check(await wait_until(lambda: asyncio.sleep(0, worker2.stats["dead_lettered"] >= 5), 30), "the consumer dead letters every bad event")
        check(await count_of(uid2) == 6, "the good events around them are still stored")
        dead = await read_topic(settings.KAFKA_DLQ_TOPIC, 5)
        reasons = sorted(json.loads(d.value)["reason"] for d in dead)
        check(len(dead) == 5, "five dead letters are on the dead letter topic")
        check(any("not valid JSON" in r for r in reasons) and any("empty message" in r for r in reasons)
              and any("missing field: provider" in r for r in reasons) and any("not a valid uuid" in r for r in reasons),
              "each carries the reason it was rejected")
        by_payload = {base64.b64decode(json.loads(d.value)["payload_b64"]) for d in dead}
        check(b"not json at all" in by_payload, "and the original bytes, so nothing is lost")
        src = json.loads(dead[0].value)["source"]
        check(src["topic"] == settings.KAFKA_USAGE_TOPIC and "partition" in src and "offset" in src, "and where it came from")

        # ---------------------------------------------------------------- foreign key
        print("one bad row inside a good batch")
        worker2.request_stop()
        task2.cancel()
        await asyncio.gather(task2, return_exceptions=True)
        ghost = new_usage_row(user_id=uuid.uuid4(), provider="openai", model="gpt-4o")  # a user that does not exist
        goods = [new_usage_row(user_id=uid2, provider="openai", model="gpt-4o") for _ in range(4)]
        raw = AIOKafkaProducer(bootstrap_servers=BROKERS)
        await raw.start()
        try:
            for r in goods[:2] + [ghost] + goods[2:]:
                await raw.send_and_wait(settings.KAFKA_USAGE_TOPIC, encode_event(r), key=b"fk")
        finally:
            await raw.stop()
        worker3 = UsageConsumer()
        task3 = asyncio.create_task(worker3.run())
        check(await wait_until(lambda: asyncio.sleep(0, worker3.stats["dead_lettered"] >= 1 and worker3.stats["inserted"] >= 4), 30),
              "the row with an unknown user is dead lettered, the others are stored")
        check(await count_of(uid2) == 10, "all four good rows were stored")
        dead = await read_topic(settings.KAFKA_DLQ_TOPIC, 6)
        check(any("database rejected the row" in json.loads(d.value)["reason"] for d in dead), "the reason names the database")

        # ---------------------------------------------------------------- database outage
        print("a database problem while processing")
        real_insert = worker3._insert
        failures = {"left": 2}

        async def flaky(rows):
            if failures["left"] > 0:
                failures["left"] -= 1
                raise OperationalError("insert", {}, Exception("connection lost"))
            return await real_insert(rows)

        worker3._insert = flaky
        retries0 = worker3.stats["retries"]
        stuck = [new_usage_row(user_id=uid2, provider="openai", model="gpt-4o") for _ in range(3)]
        raw = AIOKafkaProducer(bootstrap_servers=BROKERS)
        await raw.start()
        try:
            for r in stuck:
                await raw.send_and_wait(settings.KAFKA_USAGE_TOPIC, encode_event(r), key=b"db")
        finally:
            await raw.stop()
        seen_degraded = await wait_until(lambda: asyncio.sleep(0, worker3.status == "degraded"), 10)
        check(seen_degraded, "the consumer reports degraded while the database is failing")
        check(await wait_until(lambda: _rows_ready(uid2, 13), 30), "once the database is back the same events are stored")
        check(worker3.stats["retries"] >= retries0 + 2, "it retried instead of skipping them")
        check(worker3.status == "running" and worker3.last_error is None, "and goes back to running with the error cleared")
        check(await count_of(uid2) == 13, "nothing was stored twice")
        worker3._insert = real_insert

        # ---------------------------------------------------------------- big batches
        print("batching")
        settings.CONSUMER_BATCH_SIZE = 200
        batches0, events0, inserted0 = worker3.stats["batches"], worker3.stats["events"], worker3.stats["inserted"]
        raw = AIOKafkaProducer(bootstrap_servers=BROKERS, linger_ms=20)
        await raw.start()
        try:
            futures = [await raw.send(settings.KAFKA_USAGE_TOPIC, encode_event(new_usage_row(user_id=uid2, provider="openai", model="gpt-4o")), key=str(i % 7).encode())
                       for i in range(1200)]
            await asyncio.gather(*futures)
        finally:
            await raw.stop()
        check(await wait_until(lambda: _rows_ready(uid2, 1213), 60), "1200 events are all stored")
        check(await count_of(uid2) == 1213, "each exactly once")
        check(worker3.stats["inserted"] - inserted0 == 1200 and worker3.stats["events"] - events0 == 1200, "the consumer's counts agree")
        check(worker3.stats["batches"] - batches0 >= 6, "in batches of at most 200")

        # ---------------------------------------------------------------- compare
        print("compare mode")
        U3 = await signup("compare")
        uid3 = await user_id_of(U3)
        r = await c.post("/api/compare", json={"prompt": "hi", "models": ["gpt-4o-mini", "gpt-4o"]}, headers=U3)
        check(r.status_code == 200, "compare works with the pipeline on")
        check(await wait_until(lambda: _rows_ready(uid3, 2), 30), "both compare results arrive through the consumer")
        check({x.classification for x in await rows_of(uid3)} == {"compare"}, "as compare rows")

        worker3.request_stop()
        task3.cancel()
        await asyncio.gather(task3, return_exceptions=True)

        # ---------------------------------------------------------------- consumer health
        print("consumer health endpoint")
        import app.consumer.main as consumer_main
        async with consumer_main.app.router.lifespan_context(consumer_main.app):
            ctransport = httpx.ASGITransport(app=consumer_main.app)
            async with httpx.AsyncClient(transport=ctransport, base_url="http://c") as cc:
                async def healthy():
                    r = await cc.get("/consumer/health")
                    return r if r.status_code == 200 and r.json()["status"] == "running" else None

                r = await wait_until(healthy, 30)
                check(r is not None, "GET /consumer/health is 200 and running")
                body = r.json()
                check(body["topic"] == settings.KAFKA_USAGE_TOPIC and body["group"] == settings.KAFKA_CONSUMER_GROUP, "it names the topic and group")
                check(set(body["totals"]) >= {"batches", "events", "inserted", "duplicates", "dead_lettered", "retries"}, "it reports its totals")
                check(body["lag"] is not None and body["lag"]["total"] >= 0, "it reports how far behind it is")
                consumer_main.app.state.task.cancel()
                await asyncio.sleep(0.3)
                r = await cc.get("/consumer/health")
                check(r.status_code == 503 and r.json()["status"] == "unhealthy", "it says 503 once the loop has died")

        # ---------------------------------------------------------------- fallbacks
        print("when kafka is not available")
        await publisher.stop()
        settings.KAFKA_BOOTSTRAP_SERVERS = "127.0.0.1:1"   # nothing listens here
        publisher.kick()
        await asyncio.sleep(1.0)
        U4 = await signup("down")
        uid4 = await user_id_of(U4)
        fb0 = val("gateway_usage_events_total", result="fallback_db")
        t0 = time.perf_counter()
        await chat(U4, "while kafka is down")
        took = time.perf_counter() - t0
        check(took < 2.0, f"a request is not held up by a Kafka outage ({took:.2f}s)")
        check(await count_of(uid4) == 1, "its usage row went straight to postgres")
        check(val("gateway_usage_events_total", result="fallback_db") == fb0 + 1, "the fallback is counted")

        settings.KAFKA_BOOTSTRAP_SERVERS = ",".join(BROKERS)  # Kafka comes back
        await asyncio.sleep(0.5)
        await chat(U4, "kafka is back, this one retries the connection")
        check(await wait_until(lambda: asyncio.sleep(0, publisher.connected), 15), "the gateway reconnects by itself")
        pub0 = val("gateway_usage_events_total", result="published")
        await chat(U4, "now it is published")
        check(val("gateway_usage_events_total", result="published") == pub0 + 1, "and goes back to publishing")

        print("when kafka hangs")
        original_send = publisher._producer.send_and_wait

        async def hang(*a, **k):
            await asyncio.sleep(30)

        publisher._producer.send_and_wait = hang
        settings.KAFKA_PUBLISH_TIMEOUT_SECONDS = 0.3
        fb0 = val("gateway_usage_events_total", result="fallback_db")
        t0 = time.perf_counter()
        await chat(U4, "kafka is hanging")
        took = time.perf_counter() - t0
        check(0.25 < took < 2.0, f"the gateway gives up after the timeout ({took:.2f}s)")
        check(val("gateway_usage_events_total", result="fallback_db") == fb0 + 1, "and writes the row to postgres instead")
        publisher._producer.send_and_wait = original_send
        settings.KAFKA_PUBLISH_TIMEOUT_SECONDS = 3.0

        print("when nothing works")
        real_direct = usage_events.insert_directly
        failed0 = val("gateway_usage_events_total", result="failed")

        async def broken_db(row):
            raise OperationalError("insert", {}, Exception("postgres is down"))

        usage_events.insert_directly = broken_db
        original_send = publisher._producer.send_and_wait
        publisher._producer.send_and_wait = hang
        settings.KAFKA_PUBLISH_TIMEOUT_SECONDS = 0.2
        try:
            r = await chat(U4, "everything is down")
            check(r.status_code == 200 and "world" in r.text, "the user still gets their answer")
            check(val("gateway_usage_events_total", result="failed") == failed0 + 1, "the lost row is counted")
        finally:
            usage_events.insert_directly = real_direct
            publisher._producer.send_and_wait = original_send
            settings.KAFKA_PUBLISH_TIMEOUT_SECONDS = 3.0

        await publisher.stop()

    print(f"\nall {passed} checks passed")


async def _rows_ready(user_id, n):
    return (await count_of(user_id)) >= n


asyncio.run(main())
