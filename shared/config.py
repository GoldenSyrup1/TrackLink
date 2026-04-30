from functools import lru_cache
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tracklink"
    postgres_user: str = "tracklink"
    postgres_password: str = ""
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    # Consumer group config
    redis_consumer_block_ms: int = 5000
    redis_consumer_batch_size: int = 10
    redis_stream_maxlen: int = 100_000

    # Qdrant (shared with ContextOS — separate collections)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_persons: str = "tracklink_persons"
    qdrant_collection_startups: str = "tracklink_startups"
    qdrant_vector_size: int = 4096  # llama3.2 embedding dim

    # Ollama (Windows side, accessible from WSL2)
    ollama_base_url: str = "http://172.17.0.1:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_s: int = 120

    # Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # Scraper / opsec
    # Comma-separated list of proxy URLs; empty = no proxy
    proxy_url: str = ""
    scraper_delay_min_ms: int = 800
    scraper_delay_max_ms: int = 3000
    scraper_max_retries: int = 3
    # Rotate browser context after this many requests (0 = never)
    scraper_context_rotate_after: int = 20

    # mTLS (internal service-to-service)
    mtls_ca_cert: str = "/etc/tracklink/certs/ca.crt"
    mtls_client_cert: str = "/etc/tracklink/certs/client.crt"
    mtls_client_key: str = "/etc/tracklink/certs/client.key"

    # Observability
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "tracklink"
    prometheus_port: int = 9090

    @computed_field
    @property
    def postgres_dsn(self) -> str:
        pw = f":{self.postgres_password}" if self.postgres_password else ""
        return (
            f"postgresql+asyncpg://{self.postgres_user}{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def postgres_sync_dsn(self) -> str:
        """Sync DSN for Alembic migrations."""
        pw = f":{self.postgres_password}" if self.postgres_password else ""
        return (
            f"postgresql+psycopg2://{self.postgres_user}{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        pw = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{pw}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
