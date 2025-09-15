from __future__ import annotations

import os
from typing import Any

from PIL import Image

from .base import Upscaler, UpscaleError
from .tiles import composite_tiled


class SDX4Upscaler(Upscaler):
    def __init__(self) -> None:
        self.model_id = os.getenv("DF_UPSCALE_SDX4_ID", "stabilityai/stable-diffusion-x4-upscaler")

    def _load_pipeline(self):  # pragma: no cover
        import torch  # type: ignore
        from diffusers import StableDiffusionUpscalePipeline  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32
        pipe = StableDiffusionUpscalePipeline.from_pretrained(self.model_id, torch_dtype=dtype)

        # SDP backend optional
        sdp = os.getenv("DF_SDP_BACKEND", "auto")
        if device == "cuda" and sdp != "auto":
            try:
                torch.backends.cuda.sdp_kernel(
                    enable_flash=(sdp in {"flash", "all"}),
                    enable_mem_efficient=(sdp in {"mem", "all"}),
                    enable_math=(sdp in {"math", "all"}),
                    enable_cudnn=(sdp in {"cudnn", "all", "flash", "mem", "math"}),
                )
            except Exception:
                pass

        # Memory toggles
        if os.getenv("DF_ENABLE_XFORMERS", "0").lower() in {"1", "true", "yes"}:
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        if os.getenv("DF_ATTENTION_SLICING", "0").lower() in {"1", "true", "yes"}:
            try:
                pipe.enable_attention_slicing()
            except Exception:
                pass
        if os.getenv("DF_VAE_TILING", "1").lower() in {"1", "true", "yes"}:
            try:
                pipe.enable_vae_tiling()
            except Exception:
                pass

        # Placement
        if device == "cuda":
            if os.getenv("DF_MODEL_CPU_OFFLOAD", "1").lower() in {"1", "true", "yes"}:
                try:
                    pipe.enable_model_cpu_offload()
                except Exception:
                    pipe.to(device)
            elif os.getenv("DF_SEQUENTIAL_CPU_OFFLOAD", "0").lower() in {"1", "true", "yes"}:
                try:
                    pipe.enable_sequential_cpu_offload()
                except Exception:
                    pipe.to(device)
            else:
                pipe.to(device)
        else:
            pipe.to(device)
        return pipe

    def run(self, image: Image.Image, *, scale: int, params: dict[str, Any] | None = None) -> Image.Image:  # pragma: no cover
        """Run SD x4 upscaler. If scale==2, produce 4x then downsample to 2x.

        Params may include: prompt, negative_prompt, steps, guidance_scale, noise_level,
        tile (bool), tile_in (int), overlap_in (int), auto_tile (bool).
        """
        params = params or {}
        pipe = self._load_pipeline()
        try:
            prompt = params.get("prompt", "")
            negative_prompt = params.get("negative_prompt")
            steps = int(params.get("steps", os.getenv("DF_UPSCALE_SDX4_STEPS", 50)))
            guidance_scale = float(params.get("guidance_scale", os.getenv("DF_UPSCALE_SDX4_GUIDANCE", 0.0)))
            noise_level = int(params.get("noise_level", os.getenv("DF_UPSCALE_SDX4_NOISE_LEVEL", 20)))

            def direct(img: Image.Image) -> Image.Image:
                out = pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    image=img,
                    num_inference_steps=steps,
                    guidance_scale=guidance_scale,
                    noise_level=noise_level,
                )
                return out.images[0]

            w, h = image.size
            auto_tile = str(params.get("auto_tile", os.getenv("DF_UPSCALE_AUTO_TILE", "1"))).lower() in {"1", "true", "yes"}
            tile = bool(params.get("tile", False)) or (auto_tile and max(w, h) >= 1024)
            if tile:
                tile_in = int(params.get("tile_in", os.getenv("DF_UPSCALE_TILE_IN", 256)))
                overlap_in = int(params.get("overlap_in", os.getenv("DF_UPSCALE_OVERLAP_IN", 32)))
                up4 = composite_tiled(image, scale=4, tile_in=tile_in, overlap_in=overlap_in, run_tile=direct)
            else:
                up4 = direct(image)

            if int(scale) == 2:
                # Downsample 4x result to 2x as a pragmatic fallback when chosen
                target = (image.size[0] * 2, image.size[1] * 2)
                return up4.resize(target, resample=Image.LANCZOS)
            return up4
        except Exception as e:
            raise UpscaleError(str(e))
        finally:
            try:
                del pipe  # type: ignore
            except Exception:
                pass

