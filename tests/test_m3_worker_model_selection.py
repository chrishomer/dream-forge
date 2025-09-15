from __future__ import annotations

import os
import time
from fastapi.testclient import TestClient

from services.api.app import app
from modules.persistence.db import get_session
from modules.persistence import repos


def test_job_with_model_id_logs_selected_model(tmp_path, monkeypatch):
    # Seed a registry model
    with get_session() as session:
        m = repos.upsert_model(
            session,
            name="sel-model",
            kind="sdxl-checkpoint",
            version="1.0",
            source_uri="dummy:sel",
        )
        local = tmp_path / "models" / "sdxl-checkpoint" / "sel-model@1.0"
        local.mkdir(parents=True, exist_ok=True)
        repos.mark_model_installed(session, model_id=m.id, local_path=str(local), files_json=[], installed=True)
        mid = str(m.id)

    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_FAKE_RUNNER", "1")
    # Ensure env fallback differs so we can assert registry selection
    monkeypatch.setenv("DF_GENERATE_MODEL_PATH", "/not/used/by/test")
    # Fake S3 envs for artifacts code path
    monkeypatch.setenv("DF_MINIO_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("DF_MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("DF_MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("DF_MINIO_BUCKET", "dreamforge")

    # Monkeypatch S3 upload to local FS
    import modules.storage.s3 as s3mod

    outdir = tmp_path / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    monkeypatch.setattr(s3mod, "upload_bytes", _upload_bytes)

    client = TestClient(app)
    payload = {"type": "generate", "prompt": "x", "width": 64, "height": 64, "steps": 2, "guidance": 1.0, "model_id": mid}
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202)
    job_id = r.json()["job"]["id"]

    # Poll logs and find model.selected event line via NDJSON
    time.sleep(0.05)
    txt = client.get(f"/v1/jobs/{job_id}/logs", params={"tail": 200}).text
    lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
    import json
    events = [json.loads(ln) for ln in lines]
    selected = [e for e in events if e.get("code") == "model.selected"]
    assert selected, f"no model.selected event in logs: {lines}"
