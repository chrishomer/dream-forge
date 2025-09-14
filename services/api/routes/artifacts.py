from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from modules.persistence.db import get_session
from modules.persistence import repos
from modules.storage import s3 as s3mod
from services.api.schemas.artifacts import ArtifactListResponse, ArtifactOut
from services.api.schemas.jobs import ErrorResponse


router = APIRouter(prefix="", tags=["artifacts"])


def _presign_expires_s() -> int:
    try:
        val = int(os.getenv("DF_PRESIGN_EXPIRES_S", "3600"))
    except Exception:
        val = 3600
    return max(300, min(val, 86400))


@router.get(
    "/jobs/{job_id}/artifacts",
    response_model=ArtifactListResponse,
    responses={404: {"model": ErrorResponse}},
)
def list_artifacts(job_id: str) -> ArtifactListResponse:
    with get_session() as session:
        job = repos.get_job(session, job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "job not found"})

        arts = repos.list_artifacts_by_job(session, job_id)

    if not arts:
        return ArtifactListResponse(artifacts=[])

    cfg = s3mod.from_env()
    ttl = _presign_expires_s()
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl)
    out: list[ArtifactOut] = []
    for a in arts:
        url = s3mod.presign_get(cfg, a.s3_key, expires=timedelta(seconds=ttl))
        out.append(
            ArtifactOut(
                id=str(a.id),
                format=a.format,
                width=a.width,
                height=a.height,
                seed=a.seed,
                item_index=a.item_index,
                s3_key=a.s3_key,
                url=url,
                expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            )
        )
    return ArtifactListResponse(artifacts=out)

