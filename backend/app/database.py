from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

connect_args = {"ssl": "require"} if "supabase" in settings.DATABASE_URL else {}

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session



_MIGRATIONS = [
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS feature_tag VARCHAR(50)",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_user_id ON request_logs (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_feature_tag ON request_logs (feature_tag)",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_user_created ON request_logs (user_id, created_at)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS experiment_id UUID REFERENCES experiments(id)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS variant VARCHAR(50)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS prompt_name VARCHAR(64)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS prompt_version INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_request_logs_experiment_id ON request_logs (experiment_id)",
    "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ",
    "ALTER TABLE request_logs ALTER COLUMN ingested_at SET DEFAULT now()",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            for statement in _MIGRATIONS:
                await conn.execute(text(statement))
