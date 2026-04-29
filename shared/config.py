from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tracklink"
    postgres_user: str = "tracklink"
    postgres_password: str = ""

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Qdrant (shared with ContextOS â€” separate collections)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_persons: str = "tracklink_persons"
    qdrant_collection_startups: str = "tracklink_startups"

    # Ollama (Windows side, accessible from WSL2)
    ollama_base_url: str = "http://172.17.0.1:11434"
    ollama_model: str = "llama3.2"

    # Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # Scraper
    proxy_url: str = ""
    scraper_delay_min_ms: int = 800
    scraper_delay_max_ms: int = 3000

    # Observability
    otel_endpoint: str = "http://localhost:4317"
    prometheus_port: int = 9090

    class Config:
        env_file = ".env"

settings = Settings()
