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


def test_progress_and_sse_for_batch():
    client = TestClient(app)
    payload = {"type": "generate", "prompt": "p", "width": 64, "height": 64, "steps": 2, "count": 3}
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    # JSON progress
    r2 = client.get(f"/v1/jobs/{job_id}/progress")
    assert r2.status_code == 200
    body = r2.json()
    assert body["progress"] in (1.0, 1)  # terminal in eager
    items = {it["item_index"] for it in body.get("items", [])}
    assert items == {0, 1, 2}

    # SSE progress should include at least one progress event and close
    r3 = client.get(f"/v1/jobs/{job_id}/progress/stream")
    assert r3.status_code == 200
    text = r3.text
    assert "event: progress" in text
    assert '"progress":1.0' in text or '"progress":1' in text

