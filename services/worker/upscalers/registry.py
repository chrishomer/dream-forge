from __future__ import annotations

import os
from typing import Any

from PIL import Image

from .base import Upscaler
from .pillow_fallback import PillowUpscaler


def _default_impl_for(scale: int) -> str:
    # Auto policy: 2x -> GAN, 4x -> Diffusion (subject to availability)
    return "gan" if int(scale) == 2 else "diffusion"


def get_upscaler(impl: str | None, *, scale: int) -> Upscaler:
    impl_eff = (impl or os.getenv("DF_UPSCALE_IMPL_DEFAULT", "auto")).lower()
    if impl_eff == "auto":
        impl_eff = _default_impl_for(scale)

    # Lazy imports to keep optional deps light
    if impl_eff == "diffusion":
        try:
            from .sdx4 import SDX4Upscaler  # type: ignore

            return SDX4Upscaler()
        except Exception:
            return PillowUpscaler()
    if impl_eff == "gan":
        try:
            from .realesrgan import RealESRGANUpscaler  # type: ignore

            return RealESRGANUpscaler(scale=scale)
        except Exception:
            return PillowUpscaler()
    # Fallback
    return PillowUpscaler()

