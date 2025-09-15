# M5 Deferred Items and Follow‑ups

Status: Backlog candidates (defer until after M5 unless required)

- General pipeline grammar (arbitrary arrays/graphs of steps). M5 fixes a single chain (`generate → upscale`) via `chain.upscale.scale` to keep API simple.
- Per‑step progress in API responses (e.g., `per_step` object) — keep aggregate only in M5.
- New SSE event kind for step transitions. M5 uses existing `event: log` with `code=step.start|step.finish`.
- Tunable step weights via `DF_PROGRESS_WEIGHTS`. M5 uses fixed 0.5/0.5.
- Upscale parameters beyond `scale` (e.g., mode, format, target size). M5 supports only `scale` (2 or 4).
- Advanced SR models and GPU‑accelerated upscale. M5 uses image‑space resize (CPU) in fake/minimal real path.
- Background chaining or cross‑job chaining. Out of scope for M5.
- Rich model capabilities taxonomy (e.g., models advertising `upscale`). For now, upscale operates generically on artifacts.

---

M5.B specific deferrals (post‑M5.B unless required)

- End‑to‑end GPU hygiene metrics for upscalers (emit `gpu_mem_used_before/after`, `peak_gpu_mem_used`) and VRAM headroom preflight — planned but not required to ship M5.B.
- Models registry entries for upscalers (diffusion/GAN) with checksum provenance and `capabilities: ['upscale']` — optional in M5.B.
- NCNN/Vulkan or TensorRT backends for Real‑ESRGAN to improve portability/perf.
- Additional upscalers: SwinIR, BSRGAN variants, 4x‑UltraSharp ESRGAN — add via adapter pattern after M5.B stabilizes.
- Determinism controls for diffusion upscaler (seeded guidance, low‑noise policies) and quality presets.
- Operator policy defaults: `DF_UPSCALE_STRICT_SCALE` fleet‑wide default and per‑request override reconciliation.
- CLI `dreamforge upscaler` helpers to prefetch weights/snapshots and run quick local validations.
- Enhanced seam tests: automated image‑space assertions for tiled mode across diverse content (beyond basic MAD epsilon).
