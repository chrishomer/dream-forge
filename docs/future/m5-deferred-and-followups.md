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

