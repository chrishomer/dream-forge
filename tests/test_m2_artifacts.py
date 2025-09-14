import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app import app


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_FAKE_RUNNER", "1")
    # SQLite fallback
    if os.getenv("DF_DB_URL"):
        monkeypatch.delenv("DF_DB_URL", raising=False)
    # Fake S3
    monkeypatch.setenv("DF_MINIO_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("DF_MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("DF_MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("DF_MINIO_BUCKET", "dreamforge")

    # Monkeypatch upload to filesystem
    import modules.storage.s3 as s3mod

    outdir = tmp_path / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def _presign_get(cfg, key: str, expires=None):  # noqa: ARG001
        return f"http://signed.local/{key}"

    monkeypatch.setattr(s3mod, "upload_bytes", _upload_bytes)
    monkeypatch.setattr(s3mod, "presign_get", _presign_get)


def test_artifacts_list_with_presigned_urls():
    client = TestClient(app)

    # Create job
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

    # List artifacts
    r2 = client.get(f"/v1/jobs/{job_id}/artifacts")
    assert r2.status_code == 200
    body = r2.json()
    arts = body.get("artifacts", [])
    assert len(arts) == 1
    a0 = arts[0]
    assert a0["url"].startswith("http://signed.local/")
    assert a0["format"] == "png"
    assert a0["item_index"] == 0
    assert a0["s3_key"].startswith("dreamforge/")

