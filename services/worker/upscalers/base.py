from __future__ import annotations

from typing import Protocol, runtime_checkable, Any
from PIL import Image


@runtime_checkable
class Upscaler(Protocol):
    def run(self, image: Image.Image, *, scale: int, params: dict[str, Any] | None = None) -> Image.Image:
        ...


class UpscaleError(RuntimeError):
    pass

