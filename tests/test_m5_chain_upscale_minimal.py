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

    # Monkeypatch S3 to local filesystem
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


def test_chain_upscale_artifacts_and_progress():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "m5 chain",
        "width": 32,
        "height": 32,
        "steps": 1,
        "count": 2,
        "chain": {"upscale": {"scale": 2}},
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    # Status should list two steps
    st = client.get(f"/v1/jobs/{job_id}").json()
    names = [s["name"] for s in st.get("steps", [])]
    assert names == ["generate", "upscale"]

    # Artifacts should include both prefixes
    arts = client.get(f"/v1/jobs/{job_id}/artifacts").json().get("artifacts", [])
    keys = [a["s3_key"] for a in arts]
    assert any("/generate/" in k for k in keys)
    assert any("/upscale/" in k for k in keys)

    # Progress aggregate should be 1.0 at terminal (eager mode)
    prog = client.get(f"/v1/jobs/{job_id}/progress").json()
    assert prog.get("progress") in (1.0, 1)
    # Items should reflect terminal step (upscale) with count entries
    assert len(prog.get("items", [])) == 2

    # SSE should include progress and at least one log line with step.start
    sse = client.get(f"/v1/jobs/{job_id}/progress/stream")
    assert sse.status_code == 200
    text = sse.text
    assert "event: progress" in text

