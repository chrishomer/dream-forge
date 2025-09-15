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

    # Monkeypatch upload to local filesystem
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


def test_batch_artifacts_and_keys_and_seeds():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "batch",
        "width": 64,
        "height": 64,
        "steps": 2,
        "guidance": 1.0,
        "format": "png",
        "count": 5,
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    r2 = client.get(f"/v1/jobs/{job_id}/artifacts")
    assert r2.status_code == 200
    arts = r2.json().get("artifacts", [])
    assert len(arts) == 5
    seeds = []
    found = set()
    for a in arts:
        key = a["s3_key"]
        idx = a["item_index"]
        found.add(idx)
        assert f"_{idx}_" in key
        seeds.append(a.get("seed"))
    assert found == {0, 1, 2, 3, 4}
    # At least two seeds differ (randomized per item)
    assert len(set(seeds)) >= 2

