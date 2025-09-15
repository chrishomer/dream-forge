from __future__ import annotations

import os
from typing import Any

from PIL import Image

from .base import Upscaler, UpscaleError


class RealESRGANUpscaler(Upscaler):  # pragma: no cover
    def __init__(self, *, scale: int = 4) -> None:
        self.scale = 4 if int(scale) >= 4 else 2
        self.weights_dir = os.getenv("DF_UPSCALE_RE_WEIGHTS_DIR", "/models/realesrgan")
        self.half = os.getenv("DF_UPSCALE_RE_HALF", "1").lower() in {"1", "true", "yes"}
        self.tile = int(os.getenv("DF_UPSCALE_RE_TILE", 512))

    def _ensure_weights(self) -> str:
        filename = "RealESRGAN_x4plus.pth" if self.scale == 4 else "RealESRGAN_x2plus.pth"
        path = os.path.join(self.weights_dir, filename)
        if not os.path.exists(path):
            # Best-effort: leave helpful error; separate downloader can prefetch
            raise UpscaleError(f"Real-ESRGAN weights not found: {path}")
        return path

    def _load_engine(self):
        from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
        from realesrgan import RealESRGANer  # type: ignore

        if self.scale == 4:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        else:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)

        weights = self._ensure_weights()
        upsampler = RealESRGANer(
            scale=self.scale,
            model_path=weights,
            model=model,
            tile=self.tile,
            tile_pad=10,
            pre_pad=0,
            half=self.half,
        )
        return upsampler

    def run(self, image: Image.Image, *, scale: int, params: dict[str, Any] | None = None) -> Image.Image:
        try:
            upsampler = self._load_engine()
            img_np = np.array(image)
            output, _ = upsampler.enhance(img_np, outscale=self.scale)
            out = Image.fromarray(output)
            if int(scale) == 2 and self.scale == 4:
                # If caller asked for 2x but we used x4 weights, downsample
                target = (image.size[0] * 2, image.size[1] * 2)
                return out.resize(target, resample=Image.LANCZOS)
            return out
        except Exception as e:  # noqa: BLE001
            raise UpscaleError(str(e))


# Local import to avoid optional global dep at import time
import numpy as np  # type: ignore  # noqa: E402

