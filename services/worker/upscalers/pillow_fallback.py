from __future__ import annotations

from typing import Any
from PIL import Image


class PillowUpscaler:
    def run(self, image: Image.Image, *, scale: int, params: dict[str, Any] | None = None) -> Image.Image:
        scale = int(scale) if scale in (2, 4) else 2
        w2, h2 = image.size[0] * scale, image.size[1] * scale
        return image.resize((w2, h2), resample=Image.LANCZOS)

