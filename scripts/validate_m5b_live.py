#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Tuple


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001/v1")
TIMEOUT_S = int(os.getenv("LIVE_TIMEOUT_S", "1200"))
POLL_INTERVAL_S = float(os.getenv("LIVE_POLL_INTERVAL_S", "2.0"))


def _join_url(base: str, *parts: str) -> str:
    return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)


def _http(method: str, url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 60) -> Tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - local validation tool
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


def wait_status(job_id: str) -> dict[str, Any]:
    url = _join_url(API_BASE, "jobs", job_id)
    deadline = time.time() + TIMEOUT_S
    last = None
    while time.time() < deadline:
        st, body = _http_json("GET", url)
        if st != 200:
            raise RuntimeError(f"GET {url} -> {st} body={body}")
        cur = body.get("status")
        if cur != last:
            print(f"job {job_id} -> {cur}")
            last = cur
        if cur in {"succeeded", "failed"}:
            return body
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


def create_job(payload: dict[str, Any]) -> str:
    st, body = _http_json("POST", _join_url(API_BASE, "jobs"), body=payload, timeout=60)
    if st not in (200, 202):
        raise RuntimeError(f"Create failed: {st} {body}")
    return body["job"]["id"]


def fetch_artifacts(job_id: str) -> list[dict[str, Any]]:
    st, body = _http_json("GET", _join_url(API_BASE, "jobs", job_id, "artifacts"))
    if st != 200:
        raise RuntimeError(f"Artifacts failed: HTTP {st} body={body}")
    return body.get("artifacts", [])


def scenario_diffusion_x4():
    print("\nScenario A: Diffusion 4× (SD x4 upscaler)")
    payload = {
        "type": "generate",
        "prompt": "castle on a hill, sunrise",
        "width": 64,
        "height": 64,
        "steps": 2,
        "count": 1,
        "chain": {"upscale": {"scale": 4, "impl": "diffusion"}},
    }
    job_id = create_job(payload)
    body = wait_status(job_id)
    assert body.get("status") == "succeeded", body
    arts = fetch_artifacts(job_id)
    keys = [a["s3_key"] for a in arts]
    assert any("/upscale/" in k for k in keys)
    print("Diffusion 4× ok (artifacts present)")


def scenario_gan_x2():
    print("\nScenario B: GAN 2× (Real-ESRGAN)")
    payload = {
        "type": "generate",
        "prompt": "portrait photo",
        "width": 64,
        "height": 64,
        "steps": 2,
        "count": 1,
        "chain": {"upscale": {"scale": 2, "impl": "gan"}},
    }
    job_id = create_job(payload)
    body = wait_status(job_id)
    assert body.get("status") == "succeeded", body
    arts = fetch_artifacts(job_id)
    keys = [a["s3_key"] for a in arts]
    assert any("/upscale/" in k for k in keys)
    print("GAN 2× ok (artifacts present)")


def main() -> int:
    print(f"API_BASE={API_BASE}")
    scenario_diffusion_x4()
    scenario_gan_x2()
    print("\nM5.B Live validation scenarios passed")
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

