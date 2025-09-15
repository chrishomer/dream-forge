#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Tuple


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001/v1")
TIMEOUT_S = int(os.getenv("LIVE_TIMEOUT_S", "900"))  # 15 minutes budget
POLL_INTERVAL_S = float(os.getenv("LIVE_POLL_INTERVAL_S", "2.0"))


def _join_url(base: str, *parts: str) -> str:
    return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)


def _http(method: str, url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> Tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - local validation
            return resp.getcode(), resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return e.code, body, dict(e.headers)


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> Tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    h = {"Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    status, text, _ = _http(method, url, data=data, headers=h, timeout=timeout)
    try:
        js = json.loads(text) if text else {}
    except json.JSONDecodeError:
        js = {"raw": text}
    return status, js


def wait_ready() -> None:
    url = _join_url(API_BASE, "..", "readyz")  # /v1/../readyz -> /readyz
    url = urllib.parse.urljoin(API_BASE + "/", "../readyz")
    deadline = time.time() + 120
    while time.time() < deadline:
        code, text, _ = _http("GET", url, timeout=5)
        if code == 200 and '"ready"' in text:
            return
        time.sleep(2)
    raise TimeoutError("API not ready: GET /readyz did not return 200 in time")


def list_models() -> list[dict[str, Any]]:
    status, body = _http_json("GET", _join_url(API_BASE, "models"))
    if status != 200:
        return []
    return body.get("models", [])


def create_job(payload: dict[str, Any]) -> str:
    status, body = _http_json("POST", _join_url(API_BASE, "jobs"), body=payload, timeout=60)
    if status not in (200, 202):
        raise RuntimeError(f"Create job failed: HTTP {status} {body}")
    return body["job"]["id"]


def poll_job(job_id: str, timeout_s: int = TIMEOUT_S, interval_s: float = POLL_INTERVAL_S) -> dict[str, Any]:
    url = _join_url(API_BASE, "jobs", job_id)
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        st, body = _http_json("GET", url, timeout=30)
        if st != 200:
            raise RuntimeError(f"Get job failed: HTTP {st} body={body}")
        cur = body.get("status")
        if cur != last:
            print(f"job {job_id} -> {cur}")
            last = cur
        if cur in {"succeeded", "failed"}:
            return body
        time.sleep(interval_s)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


def fetch_artifacts(job_id: str) -> list[dict[str, Any]]:
    st, body = _http_json("GET", _join_url(API_BASE, "jobs", job_id, "artifacts"))
    if st != 200:
        raise RuntimeError(f"Artifacts failed: HTTP {st} body={body}")
    return body.get("artifacts", [])


def check_url_ok(url: str) -> int:
    # Do not decode binary content; just return HTTP status
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # nosec - local validation
            return resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code


def get_logs_tail(job_id: str, tail: int = 200) -> list[str]:
    url = _join_url(API_BASE, "jobs", job_id, "logs") + f"?tail={tail}"
    code, text, _ = _http("GET", url, timeout=60)
    if code != 200:
        return []
    return [ln for ln in text.splitlines() if ln.strip()]


def get_progress(job_id: str) -> dict[str, Any]:
    st, body = _http_json("GET", _join_url(API_BASE, "jobs", job_id, "progress"), timeout=60)
    if st != 200:
        raise RuntimeError(f"Progress failed: HTTP {st} body={body}")
    return body


def stream_sse(job_id: str) -> str:
    url = _join_url(API_BASE, "jobs", job_id, "progress", "stream")
    code, text, _ = _http("GET", url, timeout=300)
    if code != 200:
        raise RuntimeError(f"SSE failed: HTTP {code}")
    return text


def run_m1(models: list[dict[str, Any]]) -> None:
    print("\n== M1: single generate ==")
    payload = {"type": "generate", "prompt": "m1 live", "width": 64, "height": 64, "steps": 2}
    if models:
        payload["model_id"] = models[0]["id"]
    job_id = create_job(payload)
    body = poll_job(job_id)
    assert body.get("status") == "succeeded", body
    arts = fetch_artifacts(job_id)
    assert len(arts) >= 1
    # Fetch the first presigned URL
    code = check_url_ok(arts[0]["url"])
    assert code == 200
    print(f"M1 ok: artifacts={len(arts)} url_code={code}")


def run_m4(models: list[dict[str, Any]]) -> None:
    print("\n== M4: batch + seeds ==")
    payload = {"type": "generate", "prompt": "m4 live", "width": 64, "height": 64, "steps": 2, "count": 3}
    if models:
        payload["model_id"] = models[0]["id"]
    job_id = create_job(payload)
    body = poll_job(job_id)
    assert body.get("status") == "succeeded", body
    arts = fetch_artifacts(job_id)
    assert len(arts) == 3
    seeds = [a.get("seed") for a in arts]
    assert len(set(seeds)) >= 2
    prog = get_progress(job_id)
    assert prog.get("progress") in (1.0, 1)
    sse = stream_sse(job_id)
    assert "event: progress" in sse
    logs = get_logs_tail(job_id)
    assert any('"artifact.written"' in ln or 'artifact.written' in ln for ln in logs)
    print("M4 ok: artifacts=3, progress=1.0, SSE/Logs validated")


def run_m5(models: list[dict[str, Any]]) -> None:
    print("\n== M5: chain generate → upscale ==")
    payload = {
        "type": "generate",
        "prompt": "m5 live",
        "width": 32,
        "height": 32,
        "steps": 1,
        "count": 2,
        "chain": {"upscale": {"scale": 2}},
    }
    if models:
        payload["model_id"] = models[0]["id"]
    job_id = create_job(payload)
    body = poll_job(job_id, timeout_s=TIMEOUT_S)
    assert body.get("status") == "succeeded", body
    steps = [s["name"] for s in body.get("steps", [])]
    assert steps == ["generate", "upscale"], steps
    arts = fetch_artifacts(job_id)
    keys = [a["s3_key"] for a in arts]
    assert any("/generate/" in k for k in keys)
    assert any("/upscale/" in k for k in keys)
    # Check one presigned URL from upscale set
    up0 = next(a for a in arts if "/upscale/" in a["s3_key"])  # raises if not present
    code = check_url_ok(up0["url"])
    assert code == 200
    prog = get_progress(job_id)
    assert any(s.get("name") == "upscale" for s in prog.get("stages", []))
    sse = stream_sse(job_id)
    assert "event: progress" in sse
    print("M5 ok: chain complete; upscale URL fetched; SSE validated")


def main() -> int:
    print(f"Using API_BASE={API_BASE}")
    wait_ready()
    print("API ready")
    models = list_models()
    if not models:
        print("NOTE: /v1/models returned empty; proceeding without model_id (requires default env model path to be valid)")
    run_m1(models)
    run_m4(models)
    run_m5(models)
    print("\nAll LIVE validations (M1..M5) passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"ASSERTION FAILED: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
