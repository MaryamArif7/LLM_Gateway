from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    ENCRYPTION_KEY: str = ""
    UPSTASH_REDIS_REST_URL: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llmgateway"
    RATE_LIMIT_PER_MINUTE: int = 20
    CACHE_TTL_SECONDS: int = 3600
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]


settings = Settings()
