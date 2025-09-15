from __future__ import annotations

import io
import os
import uuid as _uuid
from typing import Any

from celery import shared_task
from PIL import Image

from modules.persistence.db import get_session
from modules.persistence import repos
from modules.storage import s3 as s3mod


def _scale_factor(job_id: _uuid.UUID) -> int:
    with get_session() as session:
        step = repos.get_step_by_name(session, job_id=job_id, name="upscale")
        if step and isinstance(step.metadata_json, dict):
            try:
                s = int(step.metadata_json.get("scale", 2))
                return 4 if s >= 4 else 2
            except Exception:
                return 2
    return 2


@shared_task(name="jobs.upscale")
def upscale(*, job_id: str) -> dict[str, Any]:
    job_uuid = _uuid.UUID(job_id)
    # Locate steps
    with get_session() as session:
        gen_step = repos.get_step_by_name(session, job_id=job_uuid, name="generate")
        up_step = repos.get_step_by_name(session, job_id=job_uuid, name="upscale")
        if up_step is None:
            # Nothing to do (not a chained job)
            return {"status": "skipped"}
        repos.mark_step_running(session, up_step.id)
        repos.mark_job_status(session, job_uuid, "running")
        repos.append_event(session, job_id=job_uuid, step_id=up_step.id, code="step.start", payload={"name": "upscale"})

    scale = _scale_factor(job_uuid)
    cfg = s3mod.from_env()

    try:
        with get_session() as session:
            artifacts = repos.list_artifacts_by_job(session, job_uuid)
        # Filter only generate step artifacts
        if gen_step is not None:
            artifacts = [a for a in artifacts if str(a.step_id) == str(gen_step.id)]

        # Process each artifact in order
        for a in artifacts:
            # Fake path: synthesize a deterministic image based on seed and upscale dimensions.
            if (os.getenv("DF_FAKE_RUNNER", "0").lower() in {"1", "true"}):
                w2, h2 = int(a.width) * scale, int(a.height) * scale
                seed = int(a.seed or 1)
                color = (seed % 256, (seed // 3) % 256, (seed // 7) % 256)
                img2 = Image.new("RGB", (w2, h2), color)
                out = io.BytesIO()
                img2.save(out, format="PNG")
                out_bytes = out.getvalue()
            else:
                # Real/minimal path: fetch source image and resize
                s3 = s3mod.client(cfg)
                obj = s3.get_object(Bucket=cfg.bucket, Key=a.s3_key)
                data = obj["Body"].read()
                img = Image.open(io.BytesIO(data)).convert("RGB")
                w2, h2 = img.size[0] * scale, img.size[1] * scale
                img2 = img.resize((w2, h2), resample=Image.LANCZOS)
                out = io.BytesIO()
                img2.save(out, format="PNG")
                out_bytes = out.getvalue()

            # Write upscale artifact
            fmt = "png"
            key = a.s3_key.replace("/generate/", "/upscale/")
            # If original key did not contain generate/ (unexpected), fall back to new path
            if "/upscale/" not in key:
                key = f"dreamforge/default/jobs/{job_id}/upscale/{os.path.basename(a.s3_key)}"
            s3mod.upload_bytes(cfg, key, out_bytes, content_type="image/png")

            with get_session() as session:
                repos.insert_artifact(
                    session,
                    job_id=job_uuid,
                    step_id=up_step.id,
                    format=fmt,
                    width=w2,
                    height=h2,
                    seed=a.seed,
                    item_index=a.item_index,
                    s3_key=key,
                    checksum=None,
                    metadata_json={"scale": scale},
                )
                repos.append_event(
                    session,
                    job_id=job_uuid,
                    step_id=up_step.id,
                    code="artifact.written",
                    payload={"s3_key": key, "item_index": a.item_index, "scale": scale},
                )

        with get_session() as session:
            repos.mark_step_finished(session, up_step.id, "succeeded")
            repos.mark_job_status(session, job_uuid, "succeeded")
            repos.append_event(session, job_id=job_uuid, step_id=up_step.id, code="step.finish")
            repos.append_event(session, job_id=job_uuid, step_id=None, code="job.finish")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        with get_session() as session:
            if up_step is not None:
                repos.mark_step_finished(session, up_step.id, "failed")
            repos.mark_job_status(session, job_uuid, "failed", error={"code": "internal", "message": str(exc)})
            if up_step is not None:
                repos.append_event(session, job_id=job_uuid, step_id=up_step.id, code="error", level="error", payload={"message": str(exc)})
        raise
