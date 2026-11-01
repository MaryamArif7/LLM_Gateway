from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    ENCRYPTION_KEY: str = ""
    REDIS_URL: str = ""
    UPSTASH_REDIS_REST_URL: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/llmgateway"
    RATE_LIMIT_PER_MINUTE: int = 20
    CACHE_TTL_SECONDS: int = 3600
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    METRICS_TOKEN: str = ""
    BREAKER_FAILURE_THRESHOLD: int = 5
    BREAKER_FAILURE_RATIO: float = 0.5
    BREAKER_WINDOW_SECONDS: int = 60
    BREAKER_COOLDOWN_SECONDS: float = 30
    BREAKER_MAX_COOLDOWN_SECONDS: float = 300
    HEALTH_WINDOW_SECONDS: int = 300
    KAFKA_BOOTSTRAP_SERVERS: str = ""        
    KAFKA_USAGE_TOPIC: str = "usage-events"
    KAFKA_DLQ_TOPIC: str = "usage-events-dlq" 
    KAFKA_CONSUMER_GROUP: str = "usage-consumer"
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT" 
    KAFKA_SASL_MECHANISM: str = ""             
    KAFKA_SASL_USERNAME: str = ""
    KAFKA_SASL_PASSWORD: str = ""
    KAFKA_PUBLISH_TIMEOUT_SECONDS: float = 3.0
    KAFKA_RECONNECT_SECONDS: float = 10.0
    KAFKA_TOPIC_PARTITIONS: int = 3
    KAFKA_TOPIC_REPLICATION: int = 1
    CONSUMER_BATCH_SIZE: int = 500
    CONSUMER_BATCH_MAX_WAIT_MS: int = 1000
    CONSUMER_HEALTH_STALE_SECONDS: int = 60

settings = Settings()
