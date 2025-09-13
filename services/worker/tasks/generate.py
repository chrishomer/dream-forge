from __future__ import annotations

import io
import os
import random
import time
import uuid as _uuid
from datetime import datetime
from typing import Any

from celery import shared_task
from PIL import Image

from modules.persistence.db import get_session
from modules.persistence.models import Step
from modules.persistence import repos
from modules.storage import s3 as s3mod


def _find_generate_step(session, job_id: _uuid.UUID) -> Step:
    job, steps = repos.get_job_with_steps(session, job_id)
    if not job or not steps:
        raise RuntimeError("job/step not found")
    for s in steps:
        if s.name == "generate":
            return s
    raise RuntimeError("generate step missing")


def _now_ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%S")


def _run_fake(prompt: str, width: int, height: int, seed: int) -> bytes:
    random.seed(seed)
    # Produce a solid color image derived from the seed for determinism
    color = (seed % 256, (seed // 3) % 256, (seed // 7) % 256)
    img = Image.new("RGB", (width, height), color)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def _run_real(model_path: str, prompt: str, negative_prompt: str | None, width: int, height: int, steps: int, guidance: float, seed: int) -> bytes:
    import torch  # type: ignore
    from diffusers import StableDiffusionXLPipeline  # type: ignore

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    pipe = StableDiffusionXLPipeline.from_single_file(model_path, torch_dtype=dtype)
    pipe = pipe.to(device)
    generator = torch.Generator(device=device).manual_seed(seed)
    with torch.autocast(device):
        images = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=generator,
        ).images
    img = images[0]
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


@shared_task(name="jobs.generate")
def generate(*, job_id: str) -> dict[str, Any]:
    job_uuid = _uuid.UUID(job_id)
    with get_session() as session:
        step = _find_generate_step(session, job_uuid)
        repos.mark_step_running(session, step.id)
        repos.mark_job_status(session, job_uuid, "running")
        repos.append_event(session, job_id=job_uuid, step_id=step.id, code="step.start", payload={"name": "generate"})

    # Read params
    with get_session() as session:
        job, _ = repos.get_job_with_steps(session, job_uuid)
        assert job is not None
        params = job.params_json

    prompt: str = params.get("prompt", "")
    negative: str | None = params.get("negative_prompt")
    width: int = int(params.get("width", 1024))
    height: int = int(params.get("height", 1024))
    steps: int = int(params.get("steps", 30))
    guidance: float = float(params.get("guidance", 7.0))
    seed: int = int(params.get("seed") or random.randint(1, 2**31 - 1))

    # For M1 smoke, allow smaller defaults via env toggles
    if os.getenv("DF_SMOKE", "0") in {"1", "true"}:
        width = 256
        height = 256
        steps = 10

    fake = os.getenv("DF_FAKE_RUNNER", "0").lower() in {"1", "true"}
    try:
        if fake:
            data = _run_fake(prompt, width, height, seed)
        else:
            model_path = os.getenv(
                "DF_GENERATE_MODEL_PATH",
                "/models/civitai/epicrealismXL_working.safetensors",
            )
            data = _run_real(model_path, prompt, negative, width, height, steps, guidance, seed)
        fmt = "png"
        ts = _now_ts()
        key = f"dreamforge/default/jobs/{job_id}/generate/{ts}_0_{width}x{height}_{seed}.{fmt}"

        cfg = s3mod.from_env()
        s3mod.upload_bytes(cfg, key, data, content_type="image/png")

        with get_session() as session:
            repos.insert_artifact(
                session,
                job_id=job_uuid,
                step_id=step.id,
                format=fmt,
                width=width,
                height=height,
                seed=seed,
                item_index=0,
                s3_key=key,
                checksum=None,
                metadata_json={"prompt": prompt, "negative_prompt": negative, "seed": seed},
            )
            repos.append_event(session, job_id=job_uuid, step_id=step.id, code="artifact.written", payload={"s3_key": key, "seed": seed, "item_index": 0})
            repos.mark_step_finished(session, step.id, "succeeded")
            repos.mark_job_status(session, job_uuid, "succeeded")
            repos.append_event(session, job_id=job_uuid, step_id=step.id, code="step.finish")
            repos.append_event(session, job_id=job_uuid, step_id=None, code="job.finish")
        return {"status": "ok", "artifact_key": key}
    except Exception as exc:  # noqa: BLE001
        with get_session() as session:
            repos.mark_step_finished(session, step.id, "failed")
            repos.mark_job_status(session, job_uuid, "failed", error={"code": "internal", "message": str(exc)})
            repos.append_event(session, job_id=job_uuid, step_id=step.id, code="error", level="error", payload={"message": str(exc)})
        raise
