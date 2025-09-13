from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
    env: Literal["dev", "test", "staging", "prod"] = Field(
        default="dev", description="Deployment environment label"
    )

    # Readiness checks: comma-separated list of checks to perform: db,s3
    ready_checks: str = Field(default="", description="Comma-separated readiness checks: db,s3")

    # Database
    db_url: str | None = Field(default=None, description="Postgres URL, e.g., postgresql+psycopg://...")

    # Object storage (S3/MinIO)
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str | None = None
    s3_bucket: str | None = None

    # Metrics
    metrics_enabled: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Pydantic BaseModel reads from env via Field(default=...) + env parsing in callers
    # Keep simple: allow instantiation without env var binding (we'll pass os.environ manually where needed)
    return Settings()  # type: ignore[call-arg]

