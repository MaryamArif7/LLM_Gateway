
import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.usage_events import EventError, decode_event, insert_rows, kafka_connection_kwargs, normalize_row

logger = logging.getLogger(__name__)

POLL_MS = 1000       
LINGER_MS = 200     
RETRY_START = 1.0
RETRY_MAX = 30.0


class UsageConsumer:
    def __init__(self):
        self.status = "starting"   
        self.last_activity = time.monotonic()
        self.last_error: str | None = None
        self.last_batch_at: datetime | None = None
        self.stats = {"batches": 0, "events": 0, "inserted": 0, "duplicates": 0, "dead_lettered": 0, "retries": 0}
        self._consumer = None
        self._stopping = False

 

    async def _insert(self, rows: list[dict]) -> int:
        async with SessionLocal() as session:
            inserted = await insert_rows(session, rows)
            await session.commit()
        return inserted

    async def handle_batch(self, records) -> list[tuple]:
     
        good, dead = [], []
        for record in records:
            try:
                good.append((record, normalize_row(decode_event(record.value))))
            except EventError as e:
                dead.append((record, str(e)))

        if good:
            try:
                inserted = await self._insert([row for _, row in good])
                self.stats["inserted"] += inserted
                self.stats["duplicates"] += len(good) - inserted
            except IntegrityError:
    
                for record, row in good:
                    try:
                        inserted = await self._insert([row])
                        self.stats["inserted"] += inserted
                        self.stats["duplicates"] += 1 - inserted
                    except IntegrityError as e:
                        reason = str(getattr(e, "orig", e)).strip().splitlines()[0][:200]
                        dead.append((record, f"database rejected the row: {reason}"))
        return dead


    async def _send_dead_letter(self, dlq, record, reason: str) -> None:
        body = {
            "reason": reason,
            "source": {"topic": record.topic, "partition": record.partition, "offset": record.offset},
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "payload_b64": base64.b64encode(record.value or b"").decode(),
        }
        await dlq.send_and_wait(settings.KAFKA_DLQ_TOPIC, value=json.dumps(body).encode(), key=record.key)
        self.stats["dead_lettered"] += 1
        logger.warning("dead lettered %s[%s]@%s: %s", record.topic, record.partition, record.offset, reason)

    async def _process_with_retry(self, records, dlq) -> None:
        delay = RETRY_START
        sent: set[tuple[int, int]] = set()  
        while True:
            try:
                dead = await self.handle_batch(records)
                for record, reason in dead:
                    if (record.partition, record.offset) not in sent:
                        await self._send_dead_letter(dlq, record, reason)
                        sent.add((record.partition, record.offset))
                if self.status == "degraded":
                    self.status = "running"
                    self.last_error = None
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status = "degraded"
                self.last_error = f"{type(e).__name__}: {e}"[:300]
                self.stats["retries"] += 1
                logger.warning("batch of %d failed, retrying in %.0fs: %s", len(records), delay, self.last_error)
              
                waited = 0.0
                while waited < delay:
                    self.last_activity = time.monotonic()
                    await asyncio.sleep(min(1.0, delay - waited))
                    waited += 1.0
                delay = min(delay * 2, RETRY_MAX)


    async def _collect(self, consumer) -> list:
      
        got = await consumer.getmany(timeout_ms=POLL_MS, max_records=settings.CONSUMER_BATCH_SIZE)
        records = [r for tp in sorted(got, key=lambda t: (t.topic, t.partition)) for r in got[tp]]
        if not records:
            return records
        deadline = time.monotonic() + settings.CONSUMER_BATCH_MAX_WAIT_MS / 1000
        while len(records) < settings.CONSUMER_BATCH_SIZE:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            more = await consumer.getmany(
                timeout_ms=max(1, int(min(LINGER_MS, remaining * 1000))),
                max_records=settings.CONSUMER_BATCH_SIZE - len(records),
            )
            if not more:
                break
            records.extend(r for tp in sorted(more, key=lambda t: (t.topic, t.partition)) for r in more[tp])
        return records

    async def _ensure_topics(self) -> None:
    
        from aiokafka.admin import AIOKafkaAdminClient, NewTopic

        admin = AIOKafkaAdminClient(**kafka_connection_kwargs())
        try:
            await admin.start()
            existing = set(await admin.list_topics())
            wanted = [t for t in (settings.KAFKA_USAGE_TOPIC, settings.KAFKA_DLQ_TOPIC) if t not in existing]
            if wanted:
                await admin.create_topics([
                    NewTopic(name=t, num_partitions=settings.KAFKA_TOPIC_PARTITIONS,
                             replication_factor=settings.KAFKA_TOPIC_REPLICATION)
                    for t in wanted
                ])
                logger.info("created topics: %s", wanted)
        except Exception as e:
            logger.warning("could not check or create topics (%s: %s), continuing", type(e).__name__, e)
        finally:
            try:
                await admin.close()
            except Exception:
                pass

    async def _consume_until_failure(self) -> None:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
        from aiokafka.errors import CommitFailedError

        await self._ensure_topics()
        consumer = AIOKafkaConsumer(
            settings.KAFKA_USAGE_TOPIC,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            enable_auto_commit=False,        
            auto_offset_reset="earliest",
            **kafka_connection_kwargs(),
        )
        dlq = AIOKafkaProducer(**kafka_connection_kwargs(), acks="all", enable_idempotence=True)
        await consumer.start()
        try:
            await dlq.start()
            self._consumer = consumer
            self.status = "running"
            self.last_error = None
            logger.info("consuming %s as group %s", settings.KAFKA_USAGE_TOPIC, settings.KAFKA_CONSUMER_GROUP)
            while not self._stopping:
                self.last_activity = time.monotonic()
                records = await self._collect(consumer)
                if not records:
                    continue
                await self._process_with_retry(records, dlq)
                try:
                    await consumer.commit()
                except CommitFailedError:
                
                    logger.warning("offset commit refused after a rebalance, the batch may be read again")
                self.stats["batches"] += 1
                self.stats["events"] += len(records)
                self.last_batch_at = datetime.now(timezone.utc)
        finally:
            self._consumer = None
            for client in (dlq, consumer):
                try:
                    await client.stop()
                except Exception:
                    pass

    async def run(self) -> None:

        delay = RETRY_START
        while not self._stopping:
            try:
                await self._consume_until_failure()
                delay = RETRY_START
            except asyncio.CancelledError:
                self.status = "stopped"
                raise
            except Exception as e:
                self.status = "degraded"
                self.last_error = f"{type(e).__name__}: {e}"[:300]
                logger.warning("consumer stopped, restarting in %.0fs: %s", delay, self.last_error)
                waited = 0.0
                while waited < delay and not self._stopping:
                    self.last_activity = time.monotonic()
                    await asyncio.sleep(min(1.0, delay - waited))
                    waited += 1.0
                delay = min(delay * 2, RETRY_MAX)
        self.status = "stopped"

    def request_stop(self) -> None:
        self._stopping = True

    async def lag(self) -> dict | None:
    
        consumer = self._consumer
        if consumer is None:
            return None
        try:
            partitions = {}
            for tp in consumer.assignment():
                highwater = consumer.highwater(tp)
                if highwater is None:
                    continue
                partitions[str(tp.partition)] = max(0, highwater - await consumer.position(tp))
            return {"total": sum(partitions.values()), "partitions": partitions}
        except Exception:
            return None
