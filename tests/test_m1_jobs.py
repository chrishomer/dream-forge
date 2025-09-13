import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app import app


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    # Force Celery eager and fake runner for test speed and determinism
    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_FAKE_RUNNER", "1")
    # Use SQLite fallback DB
    if os.getenv("DF_DB_URL"):
        monkeypatch.delenv("DF_DB_URL", raising=False)
    # Fake S3 by writing to a temp dir
    monkeypatch.setenv("DF_MINIO_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("DF_MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("DF_MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("DF_MINIO_BUCKET", "dreamforge")

    # Monkeypatch upload to local filesystem
    import modules.storage.s3 as s3mod

    outdir = tmp_path / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    monkeypatch.setattr(s3mod, "upload_bytes", _upload_bytes)

    yield


def test_create_and_status_happy_path():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "test image",
        "width": 64,
        "height": 64,
        "steps": 2,
        "guidance": 1.0,
        "format": "png",
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    # Status should be succeeded quickly since Celery eager executes inline
    r2 = client.get(f"/v1/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == job_id
    assert body["status"] in {"running", "succeeded"}

    # Allow small wait if status is not yet final in some environments
    if body["status"] != "succeeded":
        time.sleep(0.1)
        body = client.get(f"/v1/jobs/{job_id}").json()
    assert body["status"] == "succeeded"

