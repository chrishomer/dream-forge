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
    # Retain generic stages for single-step jobs; for chained jobs we will include two stages with equal weights.
    return [
        {"name": "queued_to_start", "weight": 0.1},
        {"name": "sampling", "weight": 0.8},
        {"name": "finalize", "weight": 0.1},
    ]


def _combined_progress_for_job(job) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:  # type: ignore[no-untyped-def]
    """Compute combined progress across steps if upscale step exists.

    Returns (aggregate_progress, items_for_terminal_step, stages_list)
    """
    with get_session() as session:
        # Count artifacts per step
        arts = repos.list_artifacts_by_job(session, job.id)
        steps = repos.get_job_with_steps(session, job.id)[1]
        step_names = [s.name for s in steps]
        has_upscale = "upscale" in step_names
        try:
            count = int(job.params_json.get("count", 1)) if isinstance(job.params_json, dict) else 1
        except Exception:
            count = 1
        count = max(1, min(count, 100))

        def _progress_for(name: str) -> float:
            if name not in step_names:
                return 0.0
            step_id = next(s.id for s in steps if s.name == name)
            completed = sum(1 for a in arts if str(a.step_id) == str(step_id))
            return min(1.0, max(0.0, completed / float(count)))

        if has_upscale:
            p_gen = _progress_for("generate")
            p_up = _progress_for("upscale")
            agg = (p_gen + p_up) / 2.0
            # Items reflect terminal step (upscale)
            up_id = next(s.id for s in steps if s.name == "upscale")
            items = [{"item_index": a.item_index, "progress": 1.0} for a in arts if str(a.step_id) == str(up_id)]
            stages = [{"name": "generate", "weight": 0.5}, {"name": "upscale", "weight": 0.5}]
            return agg, items, stages
        else:
            # Fall back to M4 behavior
            completed = len(arts)
            agg = min(1.0, max(0.0, completed / float(count)))
            items = [{"item_index": a.item_index, "progress": 1.0} for a in arts]
            return agg, items, _static_stages()


@router.get(
    "/jobs/{job_id}/progress",
    response_model=ProgressResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "batchProgress": {
                            "summary": "Aggregate + per-item snapshot",
                            "value": {
                                "progress": 0.6,
                                "items": [
                                    {"item_index": 0, "progress": 1.0},
                                    {"item_index": 1, "progress": 1.0},
                                    {"item_index": 2, "progress": 0.0}
                                ],
                                "stages": [
                                    {"name": "queued_to_start", "weight": 0.1},
                                    {"name": "sampling", "weight": 0.8},
                                    {"name": "finalize", "weight": 0.1}
                                ]
                            },
                        }
                    }
                }
            }
        },
        404: {"model": ErrorResponse},
    },
)
def get_progress(job_id: str) -> ProgressResponse:
    with get_session() as session:
        job = repos.get_job(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})
    agg, items, stages = _combined_progress_for_job(job)
    return ProgressResponse(progress=agg, items=items, stages=stages)


@router.get(
    "/jobs/{job_id}/progress/stream",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "examples": {
                        "sseExample": {
                            "summary": "SSE progress and artifact events",
                            "value": "event: progress\ndata: {\"progress\":0.4,\"items\":[{\"item_index\":0,\"progress\":1.0},{\"item_index\":1,\"progress\":0.0}]}\n\n"
                                     "event: artifact\ndata: {\"item_index\":0,\"s3_key\":\"dreamforge/..._0_64x64_123456.png\",\"format\":\"png\",\"width\":64,\"height\":64,\"seed\":123456}\n\n"
                        }
                    }
                }
            }
        },
        404: {"model": ErrorResponse}
    },
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
        cursor = since_dt
        # Emit snapshot events first then optionally poll until terminal
        while True:
            with get_session() as session:
                status_job = repos.get_job(session, job_id)
                events = repos.iter_events(session, job_id, since_ts=cursor, tail=None)
                agg, items, stages = _combined_progress_for_job(status_job) if status_job else (0.0, [], _static_stages())

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
                cursor = e.ts

            # Emit progress (aggregate + minimal items)
            yield sse_event("progress", {"progress": agg, "items": items, "stages": stages})

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
