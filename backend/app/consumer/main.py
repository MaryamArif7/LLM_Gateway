
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from app.config import settings
from app.consumer.worker import UsageConsumer

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = UsageConsumer()
    app.state.worker = worker
    app.state.task = asyncio.create_task(worker.run())
    yield
    worker.request_stop()
    app.state.task.cancel()
    await asyncio.gather(app.state.task, return_exceptions=True)


app = FastAPI(title="Usage consumer", lifespan=lifespan)


@app.get("/consumer/health")
async def health(response: Response):

    worker: UsageConsumer = app.state.worker
    task: asyncio.Task = app.state.task
    idle = time.monotonic() - worker.last_activity

    problem = None
    if task.done():
        problem = "the consumer loop has stopped"
    elif idle > settings.CONSUMER_HEALTH_STALE_SECONDS:
        problem = f"the consumer loop has shown no activity for {int(idle)} seconds"
    if problem:
        response.status_code = 503

    return {
        "status": "unhealthy" if problem else worker.status,
        "problem": problem,
        "last_error": worker.last_error,
        "last_batch_at": worker.last_batch_at.isoformat() if worker.last_batch_at else None,
        "seconds_since_activity": round(idle, 1),
        "totals": worker.stats,
        "lag": await worker.lag(),
        "topic": settings.KAFKA_USAGE_TOPIC,
        "group": settings.KAFKA_CONSUMER_GROUP,
    }
