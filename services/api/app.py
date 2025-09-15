from __future__ import annotations

import os
import time
from typing import Any

import boto3
import psycopg
from sqlalchemy.engine import make_url
from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest

from .config import get_settings
from .routes import router as v1_router


_REGISTRY = CollectorRegistry()
_HEALTH_HITS = Counter("df_api_healthz_hits", "Health endpoint hits", registry=_REGISTRY)
_READY_GAUGE = Gauge("df_api_ready", "Readiness status (1=ready, 0=not)", registry=_REGISTRY)


def _normalize_conninfo(url: str) -> str:
    # Support SQLAlchemy-style URLs (e.g., postgresql+psycopg://) by normalizing to psycopg form.
    try:
        if "+" in url.split("://", 1)[0]:
            sa_url = make_url(url).set(drivername="postgresql")
            url = sa_url.render_as_string(hide_password=False)
    except Exception:
        pass
    return url


def _check_db(url: str, timeout_s: int = 1) -> None:
    url = _normalize_conninfo(url)
    with psycopg.connect(url, connect_timeout=timeout_s) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


def _check_s3(endpoint: str, access_key: str, secret_key: str, bucket: str, region: str | None) -> None:
    session = boto3.session.Session()
    client = session.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    client.head_bucket(Bucket=bucket)


def create_app() -> FastAPI:
    # Version aligned to M4 completion
    app = FastAPI(title="Dream Forge API", version="0.4.0-mvp", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        _HEALTH_HITS.inc()
        return {"status": "ok", "ts": int(time.time())}

    @app.get("/readyz")
    def readyz() -> Any:
        settings = get_settings()
        checks = {c.strip() for c in os.getenv("DF_READY_CHECKS", settings.ready_checks).split(",") if c.strip()}
        try:
            if "db" in checks:
                url = os.getenv("DF_DB_URL") or settings.db_url
                if not url:
                    raise RuntimeError("DB readiness requested but DF_DB_URL not set")
                _check_db(url)

            if "s3" in checks:
                endpoint = os.getenv("DF_MINIO_ENDPOINT") or os.getenv("DF_S3_ENDPOINT") or settings.s3_endpoint
                access_key = os.getenv("DF_MINIO_ACCESS_KEY") or os.getenv("DF_S3_ACCESS_KEY") or settings.s3_access_key
                secret_key = os.getenv("DF_MINIO_SECRET_KEY") or os.getenv("DF_S3_SECRET_KEY") or settings.s3_secret_key
                bucket = os.getenv("DF_MINIO_BUCKET") or os.getenv("DF_S3_BUCKET") or settings.s3_bucket
                region = os.getenv("DF_S3_REGION") or settings.s3_region
                if not all([endpoint, access_key, secret_key, bucket]):
                    raise RuntimeError("S3 readiness requested but one or more S3 env vars are missing")
                _check_s3(endpoint=str(endpoint), access_key=str(access_key), secret_key=str(secret_key), bucket=str(bucket), region=region)

            _READY_GAUGE.set(1)
            return {"status": "ready"}
        except Exception as exc:  # noqa: BLE001
            _READY_GAUGE.set(0)
            return Response(content=f"not ready: {exc}", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.get("/metrics")
    def metrics() -> Response:
        output = generate_latest(_REGISTRY)
        return Response(output, media_type=CONTENT_TYPE_LATEST)

    # Mount placeholder /v1 router so OpenAPI contains a versioned root
    app.include_router(v1_router)

    return app


app = create_app()
