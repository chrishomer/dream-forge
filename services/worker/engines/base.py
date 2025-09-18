from __future__ import annotations

import abc
import os
from typing import Protocol


class Engine(Protocol):
    """Interface for generation engines.

    Implementations should lazily import heavy deps inside methods, not at module import time.
    """

    def load(self) -> None:
        """Load or initialize the underlying pipeline(s) and apply memory settings.

        Idempotent: safe to call multiple times. Implementations should cache state on `self`.
        """

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
    ) -> bytes:
        """Run a single image generation and return PNG bytes."""

    def shutdown(self) -> None:
        """Optional cleanup hook."""


def env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").lower() in {"1", "true", "yes", "on"}


def apply_common_memory_toggles(pipe, *, width: int, height: int) -> None:  # pragma: no cover - runtime path
    import torch  # type: ignore

    has_cuda = torch.cuda.is_available()

    # Optional CUDA mem fraction cap
    try:
        mem_frac_env = os.getenv("DF_CUDA_MEM_FRAC", "0.95")
        if has_cuda and mem_frac_env:
            torch.cuda.set_per_process_memory_fraction(float(mem_frac_env), device=torch.cuda.current_device())
    except Exception:
        pass

    # Attention/Memory toggles
    if env_truthy("DF_ENABLE_XFORMERS", "0"):
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass
    if env_truthy("DF_ATTENTION_SLICING", "0"):
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
    if env_truthy("DF_VAE_SLICING", "1"):
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass
    if env_truthy("DF_VAE_TILING", "1") and max(width, height) >= 1024:
        try:
            pipe.enable_vae_tiling()
        except Exception:
            pass

    # SDP backend selection
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

