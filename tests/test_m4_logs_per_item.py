import os
from pathlib import Path
import json

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


def test_logs_include_artifact_written_per_item():
    client = TestClient(app)
    r = client.post("/v1/jobs", json={"type": "generate", "prompt": "log batch", "width": 64, "height": 64, "steps": 2, "count": 4})
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    txt = client.get(f"/v1/jobs/{job_id}/logs", params={"tail": 200}).text
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    arts = [e for e in events if e.get("code") == "artifact.written"]
    assert len(arts) == 4
    indices = {e.get("item_index") for e in arts}
    assert indices == {0, 1, 2, 3}

