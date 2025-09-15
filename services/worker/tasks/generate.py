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

import gc
from multiprocessing import get_context
import contextlib


def _env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").lower() in {"1", "true", "yes", "on"}


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


def _child_generate(model_path: str, prompt: str, negative_prompt: str | None, width: int, height: int, steps: int, guidance: float, seed: int, conn) -> None:  # pragma: no cover
    try:
        import torch  # type: ignore
        from diffusers import StableDiffusionXLPipeline, AutoencoderKL  # type: ignore

        torch.backends.cudnn.benchmark = False
        has_cuda = torch.cuda.is_available()
        device = torch.device("cuda") if has_cuda else torch.device("cpu")
        dtype = torch.float16 if has_cuda else torch.float32

        # Optional CUDA mem fraction cap
        mem_frac_env = os.getenv("DF_CUDA_MEM_FRAC", "0.95")
        try:
            if has_cuda and mem_frac_env:
                torch.cuda.set_per_process_memory_fraction(float(mem_frac_env), device=torch.cuda.current_device())
        except Exception:
            pass

        # Optional SDP backend selection
        sdp = os.getenv("DF_SDP_BACKEND", "auto")
        if has_cuda:
            try:
                if sdp and sdp != "auto":
                    torch.backends.cuda.sdp_kernel(
                        enable_flash=(sdp in {"flash", "all"}),
                        enable_mem_efficient=(sdp in {"mem", "all"}),
                        enable_math=(sdp in {"math", "all"}),
                        enable_cudnn=(sdp in {"cudnn", "all", "flash", "mem", "math"}),
                    )
            except Exception:
                pass

        # Load pipeline
        pipe = StableDiffusionXLPipeline.from_single_file(
            model_path,
            torch_dtype=dtype,
            use_safetensors=True,
        )

        # Optionally replace VAE with fp16-safe SDXL VAE
        if _env_truthy("DF_USE_SDXL_VAE_FP16_FIX", "1"):
            try:
                vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16 if has_cuda else torch.float32)
                pipe.vae = vae
            except Exception:
                pass

        # VAE precision override
        vae_prec = os.getenv("DF_VAE_PRECISION", "fp16").lower()
        try:
            if vae_prec == "fp32":
                pipe.vae.to(dtype=torch.float32)
        except Exception:
            pass

        # Attention/Memory toggles
        if _env_truthy("DF_ENABLE_XFORMERS", "0"):
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        if _env_truthy("DF_ATTENTION_SLICING", "0"):
            try:
                pipe.enable_attention_slicing()
            except Exception:
                pass
        if _env_truthy("DF_VAE_SLICING", "1"):
            try:
                pipe.enable_vae_slicing()
            except Exception:
                pass
        if _env_truthy("DF_VAE_TILING", "1") and max(width, height) >= 1024:
            try:
                pipe.enable_vae_tiling()
            except Exception:
                pass

        # Placement: choose exactly one path
        if has_cuda:
            if _env_truthy("DF_MODEL_CPU_OFFLOAD", "1"):
                try:
                    pipe.enable_model_cpu_offload()
                except Exception:
                    pipe.to(device)
            elif _env_truthy("DF_SEQUENTIAL_CPU_OFFLOAD", "0"):
                try:
                    pipe.enable_sequential_cpu_offload()
                except Exception:
                    pipe.to(device)
            else:
                pipe.to(device)
        else:
            pipe.to(device)

        # Informational log of chosen config
        try:
            print(
                f"runner cfg: cuda={has_cuda} dtype={dtype} vae_prec={vae_prec} "
                f"offload(model={_env_truthy('DF_MODEL_CPU_OFFLOAD','1')}, seq={_env_truthy('DF_SEQUENTIAL_CPU_OFFLOAD','0')}) "
                f"tiling={_env_truthy('DF_VAE_TILING','1')} slicing(attn={_env_truthy('DF_ATTENTION_SLICING','0')},vae={_env_truthy('DF_VAE_SLICING','1')}) sdp={sdp}"
            )
        except Exception:
            pass

        generator = torch.Generator(device=str(device)).manual_seed(seed)
        with torch.inference_mode():
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
        conn.send_bytes(bio.getvalue())
    finally:
        try:
            # Aggressive cleanup to release GPU VRAM
            try:
                del img, images, pipe  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                import torch  # type: ignore

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except Exception:
                pass
            gc.collect()
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _run_real(model_path: str, prompt: str, negative_prompt: str | None, width: int, height: int, steps: int, guidance: float, seed: int) -> bytes:
    # Execute the diffusion run in a spawned subprocess to guarantee GPU memory cleanup on exit.
    mp = get_context("spawn")
    parent_conn, child_conn = mp.Pipe(False)
    p = mp.Process(
        target=_child_generate,
        args=(model_path, prompt, negative_prompt, width, height, steps, guidance, seed, child_conn),
        daemon=True,
    )
    p.start()
    child_conn.close()
    data = parent_conn.recv_bytes()  # may block until child finishes
    p.join(timeout=5)
    try:
        parent_conn.close()
    except Exception:
        pass
    # Parent-side GC and CUDA cache clear (in case any context leaked into parent)
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    gc.collect()
    return data


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

    # Resolve model path: prefer registry by model_id, else default registry model, else env fallback
    selected_model_path = None
    model_source = "env_fallback"
    model_id_param = params.get("model_id")
    with get_session() as session:
        if model_id_param:
            m = repos.get_model(session, model_id_param)
            if m and m.installed and m.enabled and m.local_path:
                selected_model_path = m.local_path
                model_source = "registry"
            else:
                # explicit selection but unavailable
                selected_model_path = None
        if not selected_model_path:
            mdef = repos.get_default_model(session, kind="sdxl-checkpoint")
            if mdef and mdef.installed and mdef.enabled and mdef.local_path:
                selected_model_path = mdef.local_path
                model_source = "registry"

    env_model_path = os.getenv(
        "DF_GENERATE_MODEL_PATH",
        "/models/civitai/epicrealismXL_working.safetensors",
    )
    model_path = selected_model_path or env_model_path

    # Log selected model
    try:
        with get_session() as session:
            repos.append_event(
                session,
                job_id=job_uuid,
                step_id=step.id,
                code="model.selected",
                payload={"model_id": model_id_param, "local_path": model_path, "source": model_source},
            )
    except Exception:
        pass

    fake = os.getenv("DF_FAKE_RUNNER", "0").lower() in {"1", "true"}
    try:
        if fake:
            data = _run_fake(prompt, width, height, seed)
        else:
            data = _run_real(model_path, prompt, negative, width, height, steps, guidance, seed)
        # Optional black-frame sanity check (pixel variance). If image appears blank, raise to surface error in logs.
        try:
            img = Image.open(io.BytesIO(data))
            extrema = img.convert("L").getextrema()
            if extrema and extrema[0] == extrema[1]:
                # Completely flat image (all pixels same). Treat as failure for now.
                raise RuntimeError(f"generated image appears blank (grayscale extrema={extrema})")
        except Exception:
            # If PIL cannot open, let upload proceed; S3 will store bytes for post-mortem.
            pass
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
    finally:
        # Parent-side final cleanup to reduce VRAM fragmentation across tasks
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        gc.collect()
