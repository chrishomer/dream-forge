#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8001/v1")
ENGINE = os.getenv("LIVE_ENGINE")  # optional: sdxl | flux-srpo
# Allow overriding the prompt via environment variable LIVE_PROMPT.
# Falls back to the original default text if not set.
PROMPT = os.getenv(
    "LIVE_PROMPT",
    (
        "A morning mountain scene, with mist hanging in the air and the beautiful "
        "sunrise peeking through."
    ),
)

# Allow overriding batch count via environment variable LIVE_COUNT.
# Falls back to 2 (two generations) if not set or invalid.
def _get_live_count() -> int:
    raw = os.getenv("LIVE_COUNT", "2")
    try:
        n = int(raw)
    except Exception:
        n = 2
    return max(1, min(n, 20))  # keep sane bounds for a live run


def _join(*parts: str) -> str:
    return API_BASE.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)


def _http(method: str, url: str, data: bytes | None = None, headers: Dict[str, str] | None = None, timeout: int = 60) -> Tuple[int, str, Dict[str, str]]:
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - local validation
            return resp.getcode(), resp.read().decode("utf-8", errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body, dict(e.headers)


def _http_json(method: str, url: str, body: Dict[str, Any] | None = None, timeout: int = 60) -> Tuple[int, Dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    st, text, _ = _http(method, url, data=data, headers=headers, timeout=timeout)
    try:
        js = json.loads(text) if text else {}
    except json.JSONDecodeError:
        js = {"raw": text}
    return st, js


def wait_ready() -> None:
    # /v1/../readyz -> /readyz
    url = urllib.parse.urljoin(API_BASE + "/", "../readyz")
    deadline = time.time() + 180
    while time.time() < deadline:
        st, text, _ = _http("GET", url, timeout=5)
        if st == 200 and '"ready"' in text:
            print("API ready")
            return
        time.sleep(2)
    raise TimeoutError("API not ready within timeout")


def list_models() -> List[Dict[str, Any]]:
    st, js = _http_json("GET", _join("models"))
    if st != 200:
        return []
    return js.get("models", [])


def create_job() -> str:
    payload: Dict[str, Any] = {
        "type": "generate",
        "prompt": PROMPT,
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "count": _get_live_count(),
        "chain": {"upscale": {"scale": 2}},
    }
    models = list_models()
    if models:
        payload["model_id"] = models[0]["id"]
        print(f"Using model_id={payload['model_id']}")
    else:
        print("NOTE: /v1/models empty; using DF_GENERATE_MODEL_PATH fallback inside worker")
    if ENGINE:
        payload["engine"] = ENGINE
        print(f"Using engine={ENGINE}")
    st, body = _http_json("POST", _join("jobs"), payload, timeout=60)
    if st not in (200, 202) or "job" not in body:
        raise RuntimeError(f"Create job failed: HTTP {st} body={body}")
    return body["job"]["id"]


def job_status(job_id: str) -> Dict[str, Any]:
    st, body = _http_json("GET", _join("jobs", job_id), timeout=30)
    if st != 200:
        raise RuntimeError(f"Get job failed: HTTP {st} body={body}")
    return body


def job_progress(job_id: str) -> Dict[str, Any]:
    st, body = _http_json("GET", _join("jobs", job_id, "progress"), timeout=30)
    if st != 200:
        raise RuntimeError(f"Progress failed: HTTP {st} body={body}")
    return body


def job_logs_tail(job_id: str, tail: int = 200) -> List[str]:
    st, text, _ = _http("GET", _join("jobs", job_id, "logs") + f"?tail={tail}")
    if st != 200:
        return []
    return [ln for ln in text.splitlines() if ln.strip()]


def job_artifacts(job_id: str) -> List[Dict[str, Any]]:
    st, body = _http_json("GET", _join("jobs", job_id, "artifacts"), timeout=60)
    if st != 200:
        raise RuntimeError(f"Artifacts failed: HTTP {st} body={body}")
    return body.get("artifacts", [])


def http_status(url: str, timeout: int = 120) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - local fetch
            return resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    print(f"API_BASE={API_BASE}")
    wait_ready()

    cnt = _get_live_count()
    print(f"\nCreate job: {cnt}× generate @1024 then upscale×2")
    print(f"Prompt: {PROMPT}")
    job_id = create_job()
    print(f"job_id={job_id}")

    start = time.time()
    seen_events: set[str] = set()
    seen_lines: set[str] = set()
    while True:
        st = job_status(job_id)
        phases = ",".join([f"{s['name']}:{s['status']}" for s in st.get("steps", [])])
        print(f"status={st['status']} steps=[{phases}] elapsed={int(time.time()-start)}s")

        prog = job_progress(job_id)
        pct = float(prog.get("progress", 0.0)) * 100.0
        items = prog.get("items", [])
        stages = ", ".join([f"{s['name']}({s['weight']})" for s in prog.get("stages", [])])
        print(f"progress={pct:.1f}% items_done={[it['item_index'] for it in items]} stages=[{stages}]")

        # Print new log lines (step transitions, artifacts)
        lines = job_logs_tail(job_id, tail=200)
        new = [ln for ln in lines if ln not in seen_lines]
        for ln in new[-10:]:  # limit per tick
            try:
                evt = json.loads(ln)
                code = evt.get("code")
                if code in {"step.start", "step.finish", "artifact.written", "error"}:
                    seed_info = f" seed={evt.get('seed')}" if 'seed' in evt else ""
                    print(
                        f"log: {evt['ts']} code={code} item={evt.get('item_index')} step={evt.get('step_id')}{seed_info}"
                    )
                else:
                    # Keep output tidy for other events
                    pass
            except Exception:
                pass
            seen_lines.add(ln)

        if st.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(5)

    end = time.time()
    print(f"\nTerminal status: {st['status']} runtime={int(end-start)}s")
    if st["status"] != "succeeded":
        print(f"error_code={st.get('error_code')} error_message={st.get('error_message')}")
        return 2

    arts = job_artifacts(job_id)
    print(f"artifacts_total={len(arts)}")
    gens = [a for a in arts if "/generate/" in a.get("s3_key", "")]
    ups = [a for a in arts if "/upscale/" in a.get("s3_key", "")]
    print(f"generate_artifacts={len(gens)} upscale_artifacts={len(ups)}")
    # Print seeds for each generated item
    if gens:
        print("seeds:")
        for a in sorted(gens, key=lambda x: x.get("item_index", 0)):
            print(f"  item={a.get('item_index')} seed={a.get('seed')}")
    assert len(gens) >= 2 and len(ups) >= 2, "expected at least 2 generate and 2 upscale artifacts"

    # Verify presigned URLs (sample)
    for label, sample in (("generate", gens[:1]), ("upscale", ups[:1])):
        if sample:
            code = http_status(sample[0]["url"], timeout=180)
            print(f"presign_{label}_status={code}")

    print("\nDONE: generate + upscale validated.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
