# ADR: Choose SD x4 (Diffusion) and Real‑ESRGAN (GAN) for M5.B Upscale

Date: 2025-09-15
Status: Accepted

Context
- M5 shipped a placeholder upscale; M5.B must provide a high‑quality diffusion and a GAN upscaler with lean API changes.

Decision
- Diffusion: adopt Stable Diffusion x4 Upscaler via Diffusers `StableDiffusionUpscalePipeline` using the official `stabilityai/stable-diffusion-x4-upscaler` checkpoint. Rationale: first‑class upstream support, designed for 4× SR, documented parameters (`noise_level`, guidance) and prompt control. Sources: Hugging Face model card and Diffusers docs. 
- GAN: adopt Real‑ESRGAN using `RealESRGAN_x2plus` and `RealESRGAN_x4plus` weights with tiled inference. Rationale: mature, BSD‑3, robust on photographs/natural textures, standard tile/half options. Sources: Real‑ESRGAN GitHub.

API
- Extend `chain.upscale` with `impl: 'auto'|'diffusion'|'gan'` (default `auto`) and `strict_scale: boolean` (default `false`). No response/SSE changes.

Implementation
- Add upscaler adapter seam with `sdx4` and `realesrgan` backends. Shared tiling utility uses cosine‑squared feather blending to avoid seams. Heavy GPU runs execute in a spawned subprocess for GPU hygiene.

Consequences
- Scale=2 with `impl=diffusion` proceeds via 4× then downsample unless `strict_scale=true` (422). Defaults favor reliability; operators can enforce strictness via env.

References
- SD x4 model card (training 1.25M steps on 10M images; 4× SR; `noise_level`): Hugging Face. 
- Diffusers StableDiffusionUpscalePipeline usage: Diffusers docs. 
- Real‑ESRGAN repository: BSD‑3; tile/half options; x2/x4 weights.

