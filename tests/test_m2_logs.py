import os
from pathlib import Path

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

    import modules.storage.s3 as s3mod

    outdir = tmp_path / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    monkeypatch.setattr(s3mod, "upload_bytes", _upload_bytes)


def test_logs_ndjson_tail_and_shape():
    client = TestClient(app)
    r = client.post("/v1/jobs", json={"type": "generate", "prompt": "log test", "width": 64, "height": 64, "steps": 2})
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    # Full logs
    r2 = client.get(f"/v1/jobs/{job_id}/logs")
    assert r2.status_code == 200
    assert r2.headers.get("content-type", "").startswith("application/x-ndjson")
    lines = [ln for ln in r2.text.splitlines() if ln.strip()]
    assert any('"code":"step.start"' in ln for ln in lines)
    assert any('"code":"artifact.written"' in ln for ln in lines)
    assert any('"code":"job.finish"' in ln for ln in lines)

    # Tail=1 should end with job.finish
    r3 = client.get(f"/v1/jobs/{job_id}/logs?tail=1")
    assert r3.status_code == 200
    last = [ln for ln in r3.text.splitlines() if ln.strip()][-1]
    assert '"code":"job.finish"' in last

