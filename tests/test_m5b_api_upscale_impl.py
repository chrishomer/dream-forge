import os
import pytest
from fastapi.testclient import TestClient

from services.api.app import app


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_FAKE_RUNNER", "1")
    # Avoid real S3
    monkeypatch.setenv("DF_MINIO_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("DF_MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("DF_MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("DF_MINIO_BUCKET", "dreamforge")
    # Monkeypatch S3 to local filesystem for uploads/presign
    import modules.storage.s3 as s3mod
    from pathlib import Path

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


def test_reject_diffusion_scale2_when_strict_true():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "test",
        "width": 16,
        "height": 16,
        "steps": 1,
        "count": 1,
        "chain": {"upscale": {"scale": 2, "impl": "diffusion", "strict_scale": True}},
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code == 422
    body = r.json()
    # Error envelope is returned under FastAPI's {detail: {...}}
    assert body.get("detail", {}).get("code") == "invalid_input"


def test_accept_auto_defaults():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "ok",
        "width": 16,
        "height": 16,
        "steps": 1,
        "count": 1,
        "chain": {"upscale": {"scale": 2}},
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)


def test_invalid_impl_rejected():
    client = TestClient(app)
    payload = {
        "type": "generate",
        "prompt": "bad",
        "width": 16,
        "height": 16,
        "steps": 1,
        "count": 1,
        "chain": {"upscale": {"scale": 2, "impl": "unknown"}},
    }
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code == 422
