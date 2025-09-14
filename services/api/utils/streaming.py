from __future__ import annotations

import json


def ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def sse_event(event: str, data: dict) -> bytes:
    # Minimal SSE formatter
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def sse_heartbeat() -> bytes:
    return b":\n\n"

