from __future__ import annotations

import os
import time
import datetime as dt
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from modules.persistence.db import get_session
from modules.persistence import repos
from services.api.schemas.progress import ProgressResponse
from services.api.schemas.jobs import ErrorResponse
from services.api.utils.streaming import sse_event, sse_heartbeat


router = APIRouter(prefix="", tags=["progress"])


def _static_stages() -> list[dict[str, Any]]:
    return [
        {"name": "queued_to_start", "weight": 0.1},
        {"name": "sampling", "weight": 0.8},
        {"name": "finalize", "weight": 0.1},
    ]


@router.get("/jobs/{job_id}/progress", response_model=ProgressResponse, responses={404: {"model": ErrorResponse}})
def get_progress(job_id: str) -> ProgressResponse:
    with get_session() as session:
        job = repos.get_job(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})
        value = repos.progress_for_job(session, job_id)
    return ProgressResponse(progress=value, items=[], stages=_static_stages())


@router.get(
    "/jobs/{job_id}/progress/stream",
    responses={200: {"content": {"text/event-stream": {} }}, 404: {"model": ErrorResponse}},
)
def stream_progress(job_id: str, since_ts: str | None = None) -> StreamingResponse:
    # Validate job
    with get_session() as session:
        job = repos.get_job(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})

    poll_ms = int(os.getenv("DF_SSE_POLL_MS", "500"))
    heartbeat_s = int(os.getenv("DF_SSE_HEARTBEAT_S", "15"))

    def _parse_ts(v: str | None) -> dt.datetime | None:
        if not v:
            return None
        try:
            if v.endswith("Z"):
                return dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            return dt.datetime.fromisoformat(v)
        except Exception:
            return None

    since_dt = _parse_ts(since_ts)

    def _gen() -> Iterable[bytes]:
        last_hb = time.time()
        # Emit snapshot events first then optionally poll until terminal
        while True:
            with get_session() as session:
                status_job = repos.get_job(session, job_id)
                events = repos.iter_events(session, job_id, since_ts=since_dt, tail=None)
                progress = repos.progress_for_job(session, job_id)

            # Emit any events since cursor
            for e in events:
                etype = "log"
                if e.code == "artifact.written":
                    etype = "artifact"
                elif e.code in {"error"}:
                    etype = "error"
                yield sse_event(etype, {
                    "ts": e.ts.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "code": e.code,
                    "level": e.level,
                    "payload": e.payload_json,
                })
                since_dt = e.ts  # type: ignore[misc]

            # Emit progress
            yield sse_event("progress", {"progress": progress})

            # Heartbeat
            now = time.time()
            if now - last_hb >= heartbeat_s:
                yield sse_heartbeat()
                last_hb = now

            # Terminal -> close
            if status_job and status_job.status in {"succeeded", "failed"}:
                break

            time.sleep(poll_ms / 1000.0)

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store",
    })

