#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from typing import Any

from fastapi.testclient import TestClient
import tempfile
from pathlib import Path
import modules.storage.s3 as s3mod

from services.api.app import app


def _pp(label: str, obj: Any) -> None:
    print(f"\n=== {label} ===")
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2))
    else:
        print(str(obj))


def _env_setup() -> None:
    os.environ.setdefault("DF_CELERY_EAGER", "true")
    os.environ.setdefault("DF_FAKE_RUNNER", "1")
    os.environ.pop("DF_DB_URL", None)
    os.environ.setdefault("DF_MINIO_ENDPOINT", "http://example.invalid")
    os.environ.setdefault("DF_MINIO_ACCESS_KEY", "x")
    os.environ.setdefault("DF_MINIO_SECRET_KEY", "y")
    os.environ.setdefault("DF_MINIO_BUCKET", "dreamforge")
    # Monkeypatch S3 to local filesystem (no network)
    root = Path(tempfile.mkdtemp(prefix="df_m5_"))
    outdir = root / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def _presign_get(cfg, key: str, expires=None):  # noqa: ARG001
        return f"http://signed.local/{key}"

    s3mod.upload_bytes = _upload_bytes  # type: ignore[assignment]
    s3mod.presign_get = _presign_get  # type: ignore[assignment]


def validate_m1_single(client: TestClient) -> None:
    payload = {"type": "generate", "prompt": "m1", "width": 64, "height": 64, "steps": 2}
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202), r.text
    job_id = r.json()["job"]["id"]
    st = client.get(f"/v1/jobs/{job_id}").json()
    assert st["status"] in ("succeeded", "running", "queued")
    arts = client.get(f"/v1/jobs/{job_id}/artifacts").json().get("artifacts", [])
    assert len(arts) >= 1
    _pp("M1 artifacts", arts)


def validate_m4_batch(client: TestClient) -> None:
    payload = {"type": "generate", "prompt": "m4", "width": 64, "height": 64, "steps": 2, "count": 3}
    r = client.post("/v1/jobs", json=payload)
    assert r.status_code in (200, 202), r.text
    job_id = r.json()["job"]["id"]
    st = client.get(f"/v1/jobs/{job_id}").json()
    assert st.get("summary", {}).get("count") == 3
    arts = client.get(f"/v1/jobs/{job_id}/artifacts").json()["artifacts"]
    assert len(arts) == 3
    seeds = [a.get("seed") for a in arts]
    assert len(set(seeds)) >= 2
    prog = client.get(f"/v1/jobs/{job_id}/progress").json()
    assert prog.get("progress") in (1.0, 1)
    _pp("M4 progress", prog)
    logs_txt = client.get(f"/v1/jobs/{job_id}/logs", params={"tail": 200}).text
    _pp("M4 logs tail", logs_txt.splitlines()[-3:])


def validate_m5_chain(client: TestClient) -> None:
    # Valid chain
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
    assert r.status_code in (200, 202), r.text
    job_id = r.json()["job"]["id"]
    st = client.get(f"/v1/jobs/{job_id}").json()
    _pp("M5 status", st)
    names = [s["name"] for s in st.get("steps", [])]
    assert names == ["generate", "upscale"]

    arts = client.get(f"/v1/jobs/{job_id}/artifacts").json()["artifacts"]
    keys = [a["s3_key"] for a in arts]
    assert any("/generate/" in k for k in keys)
    assert any("/upscale/" in k for k in keys)
    _pp("M5 artifacts", arts)

    prog = client.get(f"/v1/jobs/{job_id}/progress").json()
    assert prog.get("progress") in (1.0, 1)
    assert len(prog.get("items", [])) == 2
    stages = prog.get("stages", [])
    assert any(s.get("name") == "upscale" for s in stages)
    _pp("M5 progress", prog)

    sse = client.get(f"/v1/jobs/{job_id}/progress/stream")
    assert sse.status_code == 200
    text = sse.text
    assert "event: progress" in text
    assert '"progress":1' in text or '"progress":1.0' in text
    _pp("M5 SSE tail", text.splitlines()[-6:])

    # Invalid chain scale
    bad = {**payload, "chain": {"upscale": {"scale": 3}}}
    r2 = client.post("/v1/jobs", json=bad)
    assert r2.status_code == 422
    _pp("M5 invalid scale error", r2.json())


def main() -> int:
    _env_setup()
    client = TestClient(app)

    print("Validating M1...")
    validate_m1_single(client)
    print("Validating M4...")
    validate_m4_batch(client)
    print("Validating M5...")
    validate_m5_chain(client)

    print("\nAll validations passed up through M5.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"VALIDATION FAILED: {e}", file=sys.stderr)
        raise
