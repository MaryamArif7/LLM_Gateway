
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import metrics
from app.config import settings
from app.database import SessionLocal
from app.models import RequestLog

logger = logging.getLogger(__name__)

EVENT_VERSION = 1

UUID_COLUMNS = ("id", "conversation_id", "user_id", "experiment_id")
ROW_COLUMNS = (
    *UUID_COLUMNS, "feature_tag", "provider", "model", "classification", "route_reason",
    "input_tokens", "output_tokens", "cost_usd", "latency_ms", "cache_hit", "fallback_used",
    "error", "variant", "prompt_name", "prompt_version", "created_at",
)
_DEFAULTS = {
    "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": 0.0,
    "cache_hit": False, "fallback_used": False,
}
_REQUIRED = ("id", "provider", "model")


class EventError(Exception):
   

def new_usage_row(**fields) -> dict:

    unknown = set(fields) - set(ROW_COLUMNS)
    if unknown:
        raise ValueError(f"unknown usage fields: {sorted(unknown)}")
    row = {"id": uuid.uuid4(), "created_at": datetime.now(timezone.utc), **fields}
    if row.get("route_reason"):
        row["route_reason"] = row["route_reason"][:255]
    return row


def normalize_row(raw: dict) -> dict:
    
    row = {}
    for column in ROW_COLUMNS:
        value = raw.get(column)
        if value is None:
            if column in _DEFAULTS:
                value = _DEFAULTS[column]
            elif column in _REQUIRED:
                raise EventError(f"missing field: {column}")
            elif column == "created_at":
                value = datetime.now(timezone.utc)
        elif column in UUID_COLUMNS:
            try:
                value = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except ValueError:
                raise EventError(f"{column} is not a valid uuid")
        elif column == "created_at":
            try:
                value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            except ValueError:
                raise EventError("created_at is not a valid time")
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
        row[column] = value

    for column in ("provider", "model"):
        if not isinstance(row[column], str) or not row[column]:
            raise EventError(f"{column} must be a non empty string")
    for column in ("input_tokens", "output_tokens"):
        if isinstance(row[column], bool) or not isinstance(row[column], int):
            raise EventError(f"{column} must be a whole number")
    for column in ("cost_usd", "latency_ms"):
        if isinstance(row[column], bool) or not isinstance(row[column], (int, float)):
            raise EventError(f"{column} must be a number")
    return row


def encode_event(row: dict) -> bytes:
    event = {"v": EVENT_VERSION}
    for column, value in row.items():
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        event[column] = value
    return json.dumps(event, separators=(",", ":")).encode()


def decode_event(raw: bytes | None) -> dict:
    if not raw:
        raise EventError("empty message")
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise EventError("not valid JSON")
    if not isinstance(event, dict):
        raise EventError("not a JSON object")
    version = event.get("v")
    if version != EVENT_VERSION:
        raise EventError(f"unsupported event version: {version!r}")
    return event



async def insert_rows(session, rows: list[dict]) -> int:

    if not rows:
        return 0
    result = await session.execute(pg_insert(RequestLog).values(rows).on_conflict_do_nothing(index_elements=["id"]))
    return result.rowcount or 0


async def insert_directly(row: dict) -> None:
    async with SessionLocal() as session:
        await insert_rows(session, [normalize_row(row)])
        await session.commit()



def kafka_connection_kwargs() -> dict:

    from aiokafka.helpers import create_ssl_context

    kwargs: dict = {
        "bootstrap_servers": [s.strip() for s in settings.KAFKA_BOOTSTRAP_SERVERS.split(",") if s.strip()],
        "security_protocol": settings.KAFKA_SECURITY_PROTOCOL,
    }
    if settings.KAFKA_SASL_MECHANISM:
        kwargs.update(
            sasl_mechanism=settings.KAFKA_SASL_MECHANISM,
            sasl_plain_username=settings.KAFKA_SASL_USERNAME,
            sasl_plain_password=settings.KAFKA_SASL_PASSWORD,
        )
    if settings.KAFKA_SECURITY_PROTOCOL in ("SSL", "SASL_SSL"):
        kwargs["ssl_context"] = create_ssl_context()
    return kwargs


class UsagePublisher:
 

    def __init__(self):
        self._producer = None
        self._connect_task: asyncio.Task | None = None
        self._next_attempt = 0.0

    @property
    def enabled(self) -> bool:
        return bool(settings.KAFKA_BOOTSTRAP_SERVERS.strip())

    @property
    def connected(self) -> bool:
        return self._producer is not None

    def kick(self) -> None:
      
        if not self.enabled or self._producer is not None:
            return
        if self._connect_task is not None and not self._connect_task.done():
            return
        if time.monotonic() < self._next_attempt:
            return
        self._connect_task = asyncio.get_running_loop().create_task(self._connect())

    async def _connect(self) -> None:
        from aiokafka import AIOKafkaProducer

        producer = None
        try:
            producer = AIOKafkaProducer(
                **kafka_connection_kwargs(),
                acks="all",
                enable_idempotence=True,
                request_timeout_ms=10_000,
            )
            await producer.start()
            self._producer = producer
            logger.info("connected to kafka")
        except Exception as e:
            self._next_attempt = time.monotonic() + settings.KAFKA_RECONNECT_SECONDS
            logger.warning("could not connect to kafka, usage rows go to postgres directly: %s", e)
            if producer is not None:
                try:
                    await producer.stop()
                except Exception:
                    pass

    async def publish(self, row: dict) -> bool:
      
        if self._producer is None:
            self.kick()
            return False
        key = str(row["user_id"]) if row.get("user_id") else str(row["id"])
        try:
            await asyncio.wait_for(
                self._producer.send_and_wait(settings.KAFKA_USAGE_TOPIC, value=encode_event(row), key=key.encode()),
                timeout=settings.KAFKA_PUBLISH_TIMEOUT_SECONDS,
            )
            return True
        except Exception as e:
            logger.warning("could not publish usage event (%s): %s", type(e).__name__, e)
            return False

    async def stop(self) -> None:
        if self._connect_task is not None and not self._connect_task.done():
            self._connect_task.cancel()
            await asyncio.gather(self._connect_task, return_exceptions=True)
        producer, self._producer = self._producer, None
        if producer is not None:
            try:
                await producer.stop()
            except Exception:
                logger.warning("error while stopping the kafka producer", exc_info=True)
        self._next_attempt = 0.0


publisher = UsagePublisher()


async def record_usage(row: dict) -> str:
 
    if not publisher.enabled:
        try:
            await insert_directly(row)
        except Exception:
            metrics.USAGE_EVENTS.labels("failed").inc()
            raise
        metrics.USAGE_EVENTS.labels("direct_db").inc()
        return "direct_db"

    start = time.perf_counter()
    published = await publisher.publish(row)
    metrics.USAGE_PUBLISH_SECONDS.observe(time.perf_counter() - start)
    if published:
        metrics.USAGE_EVENTS.labels("published").inc()
        return "published"

    try:
        await insert_directly(row)
    except Exception:
        metrics.USAGE_EVENTS.labels("failed").inc()
        raise
    metrics.USAGE_EVENTS.labels("fallback_db").inc()
    return "fallback_db"
