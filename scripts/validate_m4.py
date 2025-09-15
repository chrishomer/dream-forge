from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app import app


def main() -> None:
    # Env for eager execution and fake runner
    os.environ.setdefault("DF_CELERY_EAGER", "true")
    os.environ.setdefault("DF_FAKE_RUNNER", "1")
    os.environ.pop("DF_DB_URL", None)
    os.environ.setdefault("DF_MINIO_ENDPOINT", "http://example.invalid")
    os.environ.setdefault("DF_MINIO_ACCESS_KEY", "x")
    os.environ.setdefault("DF_MINIO_SECRET_KEY", "y")
    os.environ.setdefault("DF_MINIO_BUCKET", "dreamforge")

    # Monkeypatch S3 to local FS
    import modules.storage.s3 as s3mod

    root = Path(tempfile.mkdtemp(prefix="df_m4_"))
    outdir = root / "s3"
    outdir.mkdir(parents=True, exist_ok=True)

    def _upload_bytes(cfg, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:  # noqa: ARG001
        p = outdir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def _presign_get(cfg, key: str, expires=None):  # noqa: ARG001
        return f"http://signed.local/{key}"

    s3mod.upload_bytes = _upload_bytes  # type: ignore[assignment]
    s3mod.presign_get = _presign_get  # type: ignore[assignment]

    client = TestClient(app)

    # 1) Create batch job
    req = {"type": "generate", "prompt": "m4 validate", "width": 64, "height": 64, "steps": 2, "count": 5}
    r = client.post("/v1/jobs", json=req)
    assert r.status_code in (200, 202), r.text
    job_id = r.json()["job"]["id"]
    print("job:", job_id)

    # 2) Status summary
    st = client.get(f"/v1/jobs/{job_id}").json()
    print("status:", json.dumps(st["summary"]))

    # 3) Artifacts
    arts = client.get(f"/v1/jobs/{job_id}/artifacts").json()["artifacts"]
    print("artifacts_count:", len(arts))
    print("artifact_indices:", sorted(a["item_index"] for a in arts))
    seeds = [a.get("seed") for a in arts]
    print("seeds:", seeds)

    # 4) Logs (tail)
    logs_text = client.get(f"/v1/jobs/{job_id}/logs", params={"tail": 200}).text
    lines = [json.loads(ln) for ln in logs_text.splitlines() if ln.strip()]
    aw = [e for e in lines if e.get("code") == "artifact.written"]
    print("logs_artifact_written:", len(aw))
    print("logs_indices:", sorted(e.get("item_index") for e in aw))

    # 5) Progress JSON
    prog = client.get(f"/v1/jobs/{job_id}/progress").json()
    print("progress:", prog.get("progress"))
    print("progress_items:", sorted(it["item_index"] for it in prog.get("items", [])))

    # 6) Count validation sample
    bad_low = client.post("/v1/jobs", json={**req, "count": 0})
    bad_high = client.post("/v1/jobs", json={**req, "count": 101})
    print("count_validation_0:", bad_low.status_code)
    print("count_validation_101:", bad_high.status_code)


if __name__ == "__main__":
    main()

