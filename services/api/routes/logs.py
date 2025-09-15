from __future__ import annotations

import datetime as dt
import json
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from modules.persistence.db import get_session
from modules.persistence import repos
from services.api.schemas.jobs import ErrorResponse
from services.api.utils.streaming import ndjson_line


router = APIRouter(prefix="", tags=["logs"])


def _parse_since_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    v = value.strip()
    # Accept both ISO with Z and without
    try:
        if v.endswith("Z"):
            return dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return dt.datetime.fromisoformat(v)
    except Exception:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": "invalid since_ts"})


def _event_to_logline(evt) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    msg = evt.payload_json.get("message") if isinstance(evt.payload_json, dict) else None
    out: dict[str, Any] = {
        "ts": evt.ts.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": evt.level,
        "code": evt.code,
        "message": msg or evt.code,
        "job_id": str(evt.job_id),
    }
    if evt.step_id:
        out["step_id"] = str(evt.step_id)
    if isinstance(evt.payload_json, dict) and "item_index" in evt.payload_json:
        out["item_index"] = evt.payload_json.get("item_index")
    return out


@router.get(
    "/jobs/{job_id}/logs",
    responses={
        200: {
            "content": {
                "application/x-ndjson": {
                    "examples": {
                        "ndjson": {
                            "summary": "Two log lines (step + artifact)",
                            "value": "{\"ts\":\"2025-09-12T21:20:00Z\",\"level\":\"info\",\"code\":\"step.start\",\"message\":\"step.start\",\"job_id\":\"<uuid>\",\"step_id\":\"<uuid>\"}\n{\"ts\":\"2025-09-12T21:20:01Z\",\"level\":\"info\",\"code\":\"artifact.written\",\"message\":\"artifact.written\",\"job_id\":\"<uuid>\",\"step_id\":\"<uuid>\",\"item_index\":0}\n"
                        }
                    }
                }
            }
        },
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse}
    },
)
def get_logs(job_id: str, tail: int | None = None, since_ts: str | None = None) -> StreamingResponse:
    # Validate job existence
    with get_session() as session:
        job = repos.get_job(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})

    # Validate tail bounds
    import os as _os
    tail_max = int((_os.getenv("DF_LOGS_TAIL_MAX", "2000")))
    if tail is None:
        tail = int((_os.getenv("DF_LOGS_TAIL_DEFAULT", "500")))
    if tail is not None:
        if tail <= 0 or tail > tail_max:
            raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": f"tail must be 1..{tail_max}"})

    since_dt = _parse_since_ts(since_ts)

    def _gen() -> Iterable[bytes]:
        with get_session() as session:
            events = repos.iter_events(session, job_id, since_ts=since_dt, tail=tail)
        for e in events:
            yield ndjson_line(_event_to_logline(e))

    return StreamingResponse(_gen(), media_type="application/x-ndjson", headers={
        "Cache-Control": "no-store",
    })
