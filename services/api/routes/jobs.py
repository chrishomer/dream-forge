from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status, Body

from modules.persistence.db import get_session
from modules.persistence import repos
from services.api.schemas.jobs import (
    ErrorResponse,
    JobCreated,
    JobCreatedResponse,
    JobCreateRequest,
    JobStatusResponse,
    StepSummary,
)


router = APIRouter(prefix="", tags=["jobs"])


def _celery() -> Celery:
    broker = os.getenv("DF_REDIS_URL", "redis://127.0.0.1:6379/0")
    app = Celery("df_api_producer", broker=broker)
    app.conf.update(
        broker_connection_retry_on_startup=True,
        task_always_eager=os.getenv("DF_CELERY_EAGER", "false").lower() in {"1", "true", "yes"},
    )
    return app


@router.post(
    "/jobs",
    response_model=JobCreatedResponse,
    responses={
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def create_job(
    req: JobCreateRequest = Body(
        examples={
            "single": {
                "summary": "Single image (default count=1)",
                "value": {
                    "type": "generate",
                    "prompt": "a tranquil lake at sunrise",
                    "width": 1024,
                    "height": 1024,
                    "steps": 30,
                    "format": "png"
                },
            },
            "batch": {
                "summary": "Batch of 5 with per-item seeds",
                "value": {
                    "type": "generate",
                    "prompt": "m4 demo",
                    "width": 64,
                    "height": 64,
                    "steps": 2,
                    "count": 5
                },
            },
        }
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobCreatedResponse:
    if req.type != "generate":
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": "Unsupported type", "details": {"type": req.type}})

    # Persist Job + Step
    with get_session() as session:
        job = repos.create_job_with_step(session, job_type=req.type, params=req.model_dump(), idempotency_key=idempotency_key)

    # Enqueue task (or inline if DF_CELERY_EAGER)
    if os.getenv("DF_CELERY_EAGER", "false").lower() in {"1", "true", "yes"}:
        try:
            from services.worker.tasks.generate import generate as task_generate  # local import to avoid cyclic issues

            task_generate(job_id=str(job.id))
        except Exception as exc:  # noqa: BLE001
            with get_session() as session:
                repos.mark_job_status(session, job.id, "failed", error={"code": "internal", "message": str(exc)})
            raise HTTPException(status_code=500, detail={"code": "internal", "message": "Inline execute failed"})
    else:
        try:
            _celery().send_task(
                "jobs.generate",
                kwargs={"job_id": str(job.id)},
                queue="gpu.default",
            )
        except Exception as exc:  # noqa: BLE001
            # Mark job as failed due to infra unavailability
            with get_session() as session:
                repos.mark_job_status(session, job.id, "failed", error={"code": "infra_unavailable", "message": str(exc)})
            raise HTTPException(status_code=503, detail={"code": "infra_unavailable", "message": "Failed to enqueue job"})

    created = JobCreated(id=str(job.id), status="queued", type=req.type, created_at=datetime.utcnow().isoformat())
    return JobCreatedResponse(job=created)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, responses={404: {"model": ErrorResponse}})
def get_job(job_id: str) -> JobStatusResponse:
    with get_session() as session:
        job, steps = repos.get_job_with_steps(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})

        # Batch-aware summary
        try:
            count = int(job.params_json.get("count", 1)) if isinstance(job.params_json, dict) else 1
        except Exception:
            count = 1
        count = max(1, min(count, 100))
        arts = repos.list_artifacts_by_job(session, job.id)
        completed = len(arts)

        return JobStatusResponse(
            id=str(job.id),
            type=job.type,
            status=job.status,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            steps=[StepSummary(name=s.name, status=s.status) for s in steps],
            summary={"count": count, "completed": completed},
            error_code=job.error_code,
            error_message=job.error_message,
        )
