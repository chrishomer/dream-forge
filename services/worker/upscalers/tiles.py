from __future__ import annotations

import math
from typing import Iterable, Tuple

import numpy as np
from PIL import Image


def feather_alpha(w: int, h: int, overlap_out: int) -> np.ndarray:
    """Cosine-squared feather alpha mask sized to the upscaled tile (out space)."""
    ramp_x = np.ones(w, dtype=np.float32)
    ramp_y = np.ones(h, dtype=np.float32)
    if overlap_out > 0:
        o = int(overlap_out)
        t = np.linspace(0, math.pi / 2, o, dtype=np.float32)
        edge = (np.sin(t)) ** 2
        ramp_x[:o] = edge
        ramp_x[-o:] = edge[::-1]
        ramp_y[:o] = edge
        ramp_y[-o:] = edge[::-1]
    alpha = np.outer(ramp_y, ramp_x)
    return alpha[..., None]  # H, W, 1


def tile_boxes(w: int, h: int, tile_in: int, overlap_in: int) -> Iterable[Tuple[int, int, int, int]]:
    tile_in = int(tile_in)
    overlap_in = int(overlap_in)
    xs = list(range(0, max(1, w - tile_in) + 1, tile_in - overlap_in))
    ys = list(range(0, max(1, h - tile_in) + 1, tile_in - overlap_in))
    if xs[-1] != w - tile_in:
        xs[-1] = max(0, w - tile_in)
    if ys[-1] != h - tile_in:
        ys[-1] = max(0, h - tile_in)
    for y in ys:
        for x in xs:
            yield x, y, tile_in, tile_in


def composite_tiled(
    image: Image.Image,
    *,
    scale: int,
    tile_in: int = 256,
    overlap_in: int = 32,
    run_tile,
):
    """Run an upscaler on overlapped tiles and alpha-blend into a seamless output."""
    w, h = image.size
    out_w, out_h = w * scale, h * scale
    canvas = np.zeros((out_h, out_w, 3), dtype=np.float32)
    alpha_acc = np.zeros((out_h, out_w, 1), dtype=np.float32)
    alpha = feather_alpha(tile_in * scale, tile_in * scale, overlap_in * scale)

    for x, y, tw, th in tile_boxes(w, h, tile_in, overlap_in):
        crop = image.crop((x, y, x + tw, y + th))
        up = run_tile(crop)
        up_np = np.asarray(up, dtype=np.float32) / 255.0
        X, Y = x * scale, y * scale
        H, W = th * scale, tw * scale
        canvas[Y:Y + H, X:X + W, :] += up_np * alpha
        alpha_acc[Y:Y + H, X:X + W, :] += alpha

    eps = 1e-6
    canvas /= np.clip(alpha_acc, eps, None)
    canvas = np.clip(canvas, 0.0, 1.0)
    return Image.fromarray((canvas * 255).astype(np.uint8))

