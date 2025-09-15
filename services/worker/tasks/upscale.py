from __future__ import annotations

import io
import os
import uuid as _uuid
from typing import Any, Callable

from celery import shared_task
from PIL import Image

from modules.persistence.db import get_session
from modules.persistence import repos
from modules.storage import s3 as s3mod
from multiprocessing import get_context
from services.worker.upscalers.registry import get_upscaler
from services.worker.upscalers.base import UpscaleError


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
    impl = None
    strict_scale = False
    with get_session() as session:
        step_meta = repos.get_step_by_name(session, job_id=job_uuid, name="upscale")
        if step_meta and isinstance(step_meta.metadata_json, dict):
            impl = step_meta.metadata_json.get("impl")
            strict_scale = bool(step_meta.metadata_json.get("strict_scale", False))

    try:
        with get_session() as session:
            artifacts = repos.list_artifacts_by_job(session, job_uuid)
        # Filter only generate step artifacts
        if gen_step is not None:
            artifacts = [a for a in artifacts if str(a.step_id) == str(gen_step.id)]

        # Read job params for diffusion guidance (optional)
        with get_session() as session:
            job, _ = repos.get_job_with_steps(session, job_uuid)
            job_params = job.params_json if job else {}

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
                # Real path: fetch source image and invoke selected upscaler (subprocess by default)
                s3 = s3mod.client(cfg)
                obj = s3.get_object(Bucket=cfg.bucket, Key=a.s3_key)
                data = obj["Body"].read()
                out_bytes = _run_upscale_bytes(
                    source_png=data,
                    scale=scale,
                    impl=impl,
                    strict_scale=strict_scale,
                    job_params=job_params,
                )
                img2 = Image.open(io.BytesIO(out_bytes))
                w2, h2 = img2.size

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
                    metadata_json={"scale": scale, "impl": impl or "auto", "strict_scale": strict_scale},
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


def _child_upscale_bytes(source_png: bytes, *, scale: int, impl: str | None, strict_scale: bool, job_params: dict) -> bytes:
    from io import BytesIO
    from PIL import Image
    from services.worker.upscalers.registry import get_upscaler

    img = Image.open(BytesIO(source_png)).convert("RGB")

    params = {
        "prompt": job_params.get("prompt", ""),
        "negative_prompt": job_params.get("negative_prompt"),
        "steps": int(job_params.get("steps", 30)),
        "guidance_scale": float(job_params.get("guidance", 0.0)),
        "noise_level": int(os.getenv("DF_UPSCALE_SDX4_NOISE_LEVEL", 20)),
        "auto_tile": os.getenv("DF_UPSCALE_AUTO_TILE", "1"),
        "tile_in": os.getenv("DF_UPSCALE_TILE_IN", 256),
        "overlap_in": os.getenv("DF_UPSCALE_OVERLAP_IN", 32),
    }

    def try_impl(which: str | None) -> Image.Image:
        upscaler = get_upscaler(which, scale=scale)
        return upscaler.run(img, scale=scale, params=params)

    if strict_scale and (impl or "auto") == "diffusion" and int(scale) == 2:
        raise UpscaleError("strict_scale=true and impl=diffusion cannot realize 2x")

    try:
        result = try_impl(impl)
    except Exception as e:
        if strict_scale:
            raise
        try:
            fallback_impl = "gan" if (impl or "auto") == "diffusion" else None
            result = try_impl(fallback_impl)
        except Exception:
            raise e

    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue()


def _run_upscale_bytes(*, source_png: bytes, scale: int, impl: str | None, strict_scale: bool, job_params: dict) -> bytes:
    use_subproc = os.getenv("DF_UPSCALE_SUBPROCESS", "1").lower() in {"1", "true", "yes"}
    if not use_subproc:
        return _child_upscale_bytes(source_png, scale=scale, impl=impl, strict_scale=strict_scale, job_params=job_params)

    mp = get_context("spawn")
    parent_conn, child_conn = mp.Pipe(False)
    p = mp.Process(target=_child_upscale_entry, args=(child_conn, source_png, scale, impl, strict_scale, job_params), daemon=True)
    p.start()
    child_conn.close()
    data = parent_conn.recv_bytes()
    p.join(timeout=5)
    try:
        parent_conn.close()
    except Exception:
        pass
    return data


def _child_upscale_entry(conn, source_png: bytes, scale: int, impl: str | None, strict_scale: bool, job_params: dict):
    try:
        data = _child_upscale_bytes(source_png, scale=scale, impl=impl, strict_scale=strict_scale, job_params=job_params)
        conn.send_bytes(data)
    finally:
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
