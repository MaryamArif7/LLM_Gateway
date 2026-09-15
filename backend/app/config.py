from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Server-held provider keys — no longer used to serve requests once BYOK
    # is wired in, but harmless to leave as optional local-dev fallbacks
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # Secret used to encrypt/decrypt each user's own provider keys at rest.
    # Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = ""

    # Infra
    REDIS_URL: str = "redis://localhost:6379/0"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llmgateway"

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 20

    # Caching
    CACHE_TTL_SECONDS: int = 3600

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]


settings = Settings()
