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


def test_progress_json_and_sse_terminate():
    client = TestClient(app)
    r = client.post("/v1/jobs", json={"type": "generate", "prompt": "progress test", "width": 64, "height": 64, "steps": 2})
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    r2 = client.get(f"/v1/jobs/{job_id}/progress")
    assert r2.status_code == 200
    # Likely already succeeded in eager mode; accept >= 0.5
    assert r2.json()["progress"] >= 0.5

    # SSE should include a progress event and then close (job terminal in eager mode)
    r3 = client.get(f"/v1/jobs/{job_id}/progress/stream")
    assert r3.status_code == 200
    text = r3.text
    assert "event: progress" in text
    # last progress should be 1.0 or close
    assert '"progress":1.0' in text or '"progress":1' in text

