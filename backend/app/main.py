from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.middleware import MetricsMiddleware
from app.usage_events import publisher
from app.routes import auth, chat, compare, experiments, health, keys, metrics, models, prompts, provider_keys, usage


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
 
    publisher.kick()
    yield
    await publisher.stop()


app = FastAPI(title="LLM Gateway", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],

    expose_headers=["X-Gateway-Decision"],
)

app.add_middleware(MetricsMiddleware)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(provider_keys.router)
app.include_router(chat.router)
app.include_router(compare.router)
app.include_router(usage.router)
app.include_router(prompts.router)
app.include_router(experiments.router)
app.include_router(models.router)
