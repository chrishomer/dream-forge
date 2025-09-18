from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional

from .base import Engine, apply_common_memory_toggles, env_truthy


@dataclass
class _FluxState:
    pipe: Optional[object] = None
    loaded_variant: str | None = None  # e.g., "srpo-bf16"


class FluxSrpoEngine(Engine):
    """FLUX.1-dev with SRPO transformer replacement.

    Notes:
    - Requires HF token for gated base model (set HUGGINGFACE_HUB_TOKEN or HF_TOKEN).
    - Expects SRPO transformer safetensors file installed via registry (kind=flux-transformer),
      or a direct path in DF_FLUX_SRPO_TRANSFORMER_PATH.
    """

    def __init__(self) -> None:
        self._state = _FluxState()

    def _resolve_paths(self) -> tuple[str, str]:
        base_repo = os.getenv("DF_FLUX_BASE_REPO", "black-forest-labs/FLUX.1-dev")
        base_rev = os.getenv("DF_FLUX_BASE_REV", "main")
        # SRPO transformer path: prefer explicit env; registry resolution happens in caller to pass model_id (future)
        srpo_path = os.getenv("DF_FLUX_SRPO_TRANSFORMER_PATH", "")
        if not srpo_path:
            # Fallback conventional location under DF_MODELS_ROOT if operator followed manifest naming
            models_root = os.getenv("DF_MODELS_ROOT", "/models")
            cand = os.path.join(models_root, "flux-transformer", "flux.1-dev-SRPO@bf16", "flux.1-dev-SRPO-bf16.safetensors")
            srpo_path = cand
        return f"{base_repo}@{base_rev}", srpo_path

    def load(self) -> None:  # pragma: no cover - heavy runtime path
        if self._state.pipe is not None:
            return
        # Lazy imports
        import torch  # type: ignore
        from safetensors.torch import load_file as st_load_file  # type: ignore
        from huggingface_hub import login as hf_login  # type: ignore
        # Diffusers FLUX pipeline import path (0.31+):
        try:
            from diffusers import FluxPipeline  # type: ignore
        except Exception:  # fallback older alias if needed
            from diffusers import DiffusionPipeline as FluxPipeline  # type: ignore

        # Auth (best-effort): prefer HUGGINGFACE_HUB_TOKEN, fallback HF_TOKEN
        token = os.getenv("HUGGINGFACE_HUB_TOKEN") or os.getenv("HF_TOKEN")
        if token:
            try:
                hf_login(token=token)
            except Exception:
                pass

        base_ref, srpo_path = self._resolve_paths()
        base_repo, base_rev = base_ref.split("@", 1)

        # Respect HF_HOME for caching
        if not os.getenv("HF_HOME"):
            os.environ["HF_HOME"] = os.path.join(os.getenv("DF_MODELS_ROOT", "/models"), "hf-cache")

        # dtype: prefer bf16 when supported
        dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else (
            torch.float16 if torch.cuda.is_available() else torch.float32
        )

        pipe = FluxPipeline.from_pretrained(base_repo, revision=base_rev, torch_dtype=dtype)

        # VAE precision override
        vae_prec = (os.getenv("DF_VAE_PRECISION", "auto").lower())
        try:
            if vae_prec == "fp32":
                pipe.vae.to(dtype=torch.float32)
        except Exception:
            pass

        # Memory/offload toggles before weight swap
        apply_common_memory_toggles(pipe, width=1024, height=1024)  # defaults; actual dims don't affect enabling

        # Placement: prefer model CPU offload to fit on modest VRAM
        has_cuda = torch.cuda.is_available()
        if has_cuda:
            try:
                if env_truthy("DF_MODEL_CPU_OFFLOAD", "1"):
                    pipe.enable_model_cpu_offload()
                elif env_truthy("DF_SEQUENTIAL_CPU_OFFLOAD", "0"):
                    pipe.enable_sequential_cpu_offload()
                else:
                    pipe.to("cuda")
            except Exception:
                try:
                    pipe.to("cuda")
                except Exception:
                    pipe.to("cpu")
        else:
            pipe.to("cpu")

        # Load SRPO transformer state and apply
        if not os.path.exists(srpo_path):
            raise FileNotFoundError(f"SRPO transformer not found: {srpo_path}")
        sd = st_load_file(srpo_path, device="cpu")
        try:
            pipe.transformer.load_state_dict(sd, strict=False)
        except Exception as e:
            # Some diffusers builds require .unet/.transformer key mapping; surface a clear error
            raise RuntimeError(f"Failed to load SRPO weights into FLUX transformer: {e}")

        # Warm-up with a tiny step to trigger kernels (best-effort)
        try:
            gen = torch.Generator(device=("cuda" if has_cuda else "cpu")).manual_seed(1)
            _ = pipe(
                prompt="warmup",
                width=256,
                height=256,
                num_inference_steps=1,
                guidance_scale=0.0,
                generator=gen,
            )
        except Exception:
            pass

        self._state.pipe = pipe
        self._state.loaded_variant = "srpo-bf16" if dtype == torch.bfloat16 else ("srpo-fp16" if dtype == torch.float16 else "srpo-fp32")

    def generate_one(
        self,
        *,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        steps: int,
        guidance: float,
        seed: int,
    ) -> bytes:  # pragma: no cover - runtime path
        import torch  # type: ignore

        if self._state.pipe is None:
            self.load()
        assert self._state.pipe is not None
        pipe = self._state.pipe

        # Apply toggles that depend on size right before run
        try:
            apply_common_memory_toggles(pipe, width=width, height=height)
        except Exception:
            pass

        # Use SDPA config if requested (already set in load())
        gen = torch.Generator(device=("cuda" if torch.cuda.is_available() else "cpu")).manual_seed(seed)

        # Prepare call kwargs based on pipeline signature (Flux may not support negative_prompt)
        import inspect as _inspect  # local import to avoid global dependency
        sig = _inspect.signature(pipe.__call__)
        def _supports(name: str) -> bool:
            return name in sig.parameters

        base_kwargs = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "generator": gen,
        }
        if negative_prompt and _supports("negative_prompt"):
            base_kwargs["negative_prompt"] = negative_prompt or None

        # OOM-resilient attempt: normal → seq offload & reduce steps
        for attempt in (1, 2):
            try:
                with torch.inference_mode():
                    images = pipe(**base_kwargs).images
                img = images[0]
                bio = io.BytesIO()
                img.save(bio, format="PNG")
                return bio.getvalue()
            except RuntimeError as e:
                # Simple OOM heuristic
                if "CUDA out of memory" in str(e) and attempt == 1:
                    try:
                        if hasattr(pipe, "enable_sequential_cpu_offload"):
                            pipe.enable_sequential_cpu_offload()
                    except Exception:
                        pass
                    steps = max(1, int(steps * 0.8))
                    base_kwargs["num_inference_steps"] = steps
                    continue
                raise
            finally:
                try:
                    del images, img  # type: ignore[name-defined]
                except Exception:
                    pass
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.ipc_collect()
                except Exception:
                    pass

        raise RuntimeError("generation failed after retries")

    def shutdown(self) -> None:  # pragma: no cover - runtime cleanup
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
        self._state.pipe = None
        self._state.loaded_variant = None
