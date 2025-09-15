import os

import pytest
from fastapi.testclient import TestClient

from services.api.app import app


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_FAKE_RUNNER", "1")
    if os.getenv("DF_DB_URL"):
        monkeypatch.delenv("DF_DB_URL", raising=False)
    monkeypatch.setenv("DF_MINIO_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("DF_MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("DF_MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("DF_MINIO_BUCKET", "dreamforge")

    # Monkeypatch upload to local filesystem
    import modules.storage.s3 as s3mod

    outdir = tmp_path / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    monkeypatch.setattr(s3mod, "upload_bytes", _upload_bytes)


def test_count_validation_bounds():
    client = TestClient(app)
    base = {"type": "generate", "prompt": "x", "width": 64, "height": 64, "steps": 1}

    r_low = client.post("/v1/jobs", json={**base, "count": 0})
    assert r_low.status_code == 422

    r_high = client.post("/v1/jobs", json={**base, "count": 101})
    assert r_high.status_code == 422

    r_ok = client.post("/v1/jobs", json={**base, "count": 1})
    assert r_ok.status_code in (200, 202)
