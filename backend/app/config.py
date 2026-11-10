"""Application settings, loaded from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Real environment variables win; the .env files are a fallback for local runs
    # (repo-root .env when started from backend/, or a local one). Missing files are ignored.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "FraudMesh"
    log_level: str = "INFO"

    # Neo4j connection. No default password: it must come from the environment.
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(min_length=8)

    # Secret key for hashing card numbers, phone numbers and addresses (app/security/pii.py).
    # Changing it changes every hash, so it must stay the same once data is loaded.
    pii_hash_key: str = Field(min_length=16)

    # Comma-separated origins allowed by CORS (the dashboard).
    cors_origins: str = "http://localhost:5173"

    # Authentication. The JWT secret signs every token; keep it long and private.
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Password for the seeded admin/analyst/viewer users (`python -m app.seed`).
    default_admin_password: str = Field(default="ChangeMe123!", min_length=8)

    # PostgreSQL: relational baseline for the benchmark only.
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "fraudmesh"
    postgres_password: str = ""
    postgres_db: str = "fraudmesh"

    # Where ground truth, evaluation and benchmark results are written.
    data_dir: str = "data"
    # Run ring detection + propagation on a timer (interval is an admin setting).
    scheduler_enabled: bool = True

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
