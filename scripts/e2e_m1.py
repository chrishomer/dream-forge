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


API_BASE = os.getenv("API_BASE", "http://localhost:8001/v1")
TIMEOUT_S = int(os.getenv("E2E_TIMEOUT_S", "480"))
POLL_INTERVAL_S = float(os.getenv("E2E_POLL_INTERVAL_S", "2.0"))


def _join_url(base: str, *parts: str) -> str:
    return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec - local test tool
            status = resp.getcode()
            text = resp.read().decode("utf-8")
            return status, json.loads(text) if text else {}
    except urllib.error.HTTPError as e:  # surface JSON error bodies if present
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {"message": str(e)}
        return e.code, payload


def create_job(prompt: str, *, width: int, height: int, steps: int, seed: int | None = None) -> str:
    url = _join_url(API_BASE, "jobs")
    payload: dict[str, Any] = {
        "type": "generate",
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "steps": int(steps),
    }
    if seed is not None:
        payload["seed"] = int(seed)
    status, body = _http_json("POST", url, body=payload)
    if status != 200 or "job" not in body:
        raise RuntimeError(f"Create job failed: HTTP {status} body={body}")
    job_id = body["job"]["id"]
    return job_id


def poll_job(job_id: str, *, timeout_s: int = TIMEOUT_S, interval_s: float = POLL_INTERVAL_S) -> dict[str, Any]:
    url = _join_url(API_BASE, "jobs", job_id)
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        status, body = _http_json("GET", url)
        if status != 200:
            raise RuntimeError(f"Get job failed: HTTP {status} body={body}")
        cur = body.get("status")
        if cur != last_status:
            print(f"job {job_id} status -> {cur}")
            last_status = cur
        if cur in {"succeeded", "failed", "cancelled"}:
            return body
        time.sleep(interval_s)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


def run_two_smoke_jobs() -> None:
    print(f"Using API_BASE={API_BASE}")
    # Use small sizes for smoke stability
    w = int(os.getenv("E2E_WIDTH", "256"))
    h = int(os.getenv("E2E_HEIGHT", "256"))
    steps = int(os.getenv("E2E_STEPS", "10"))

    j1 = create_job("a small red car, studio lighting", width=w, height=h, steps=steps, seed=123456)
    print(f"created job1: {j1}")
    r1 = poll_job(j1)
    if r1.get("status") != "succeeded":
        code = r1.get("error_code")
        msg = r1.get("error_message")
        raise RuntimeError(f"job1 did not succeed: status={r1.get('status')} error_code={code} error_message={msg}")

    j2 = create_job("a medieval castle on a hill", width=w, height=h, steps=steps, seed=654321)
    print(f"created job2: {j2}")
    r2 = poll_job(j2)
    if r2.get("status") != "succeeded":
        code = r2.get("error_code")
        msg = r2.get("error_message")
        raise RuntimeError(f"job2 did not succeed: status={r2.get('status')} error_code={code} error_message={msg}")

    print("\nE2E M1 passed: two sequential jobs succeeded.")
    print("Artifacts S3 prefixes:")
    print(f" - dreamforge/default/jobs/{j1}/generate/")
    print(f" - dreamforge/default/jobs/{j2}/generate/")


def main() -> int:
    # Simple CLI: default runs two jobs sequentially. If ONE_SHOT_PROMPT is provided, run a single job.
    one_prompt = os.getenv("ONE_SHOT_PROMPT")
    if one_prompt:
        w = int(os.getenv("ONE_SHOT_WIDTH", "1024"))
        h = int(os.getenv("ONE_SHOT_HEIGHT", "1024"))
        steps = int(os.getenv("ONE_SHOT_STEPS", "30"))
        seed_env = os.getenv("ONE_SHOT_SEED")
        seed = int(seed_env) if seed_env else None
        jid = create_job(one_prompt, width=w, height=h, steps=steps, seed=seed)
        print(f"created job: {jid}")
        body = poll_job(jid)
        print(json.dumps(body, indent=2))
        print(f"artifact prefix: dreamforge/default/jobs/{jid}/generate/")
        return 0 if body.get("status") == "succeeded" else 2

    run_two_smoke_jobs()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
