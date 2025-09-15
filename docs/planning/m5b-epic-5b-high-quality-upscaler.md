# Milestone 5.B — Epic 5B: High‑Quality Upscaler (Diffusion + GAN)

Last updated: 2025-09-15

Status: Proposal for review (implementation to follow)

Owners: Engineering (Worker/Models/API), DX (Docs), Product (Scope)

References: 
- docs/masters/08-roadmap.md (M5)
- docs/planning/m5-epic-5-minimal-chaining-generate-upscale.md (baseline M5)
- docs/future/m5-deferred-and-followups.md (items we’re now addressing)
- docs/research/image-upsize-research.md (internal research)

---

## 1) Summary

M5 delivered a minimal `generate → upscale` chain with a placeholder upscaler (Pillow LANCZOS). M5.B upgrades the `upscale` step to support two real, high‑quality implementations:

- Diffusion: Stable Diffusion x4 Upscaler via `diffusers.StableDiffusionUpscalePipeline` using the official `stabilityai/stable-diffusion-x4-upscaler` checkpoint.
- GAN: Real‑ESRGAN (general) using `RealESRGAN_x4plus.pth` (and `RealESRGAN_x2plus.pth` for 2×), with tiled inference.

We keep the API surface lean: add an optional `impl` discriminator under `chain.upscale` with `auto` default, plus an optional `strict_scale` boolean to control fallback behavior. We preserve all existing response shapes, events, and simple combined progress. Heavy additions (new SSE types, pipeline grammar, per‑step progress) remain deferred.

---

## 2) Why these two first models

- Stable Diffusion x4 Upscaler is the canonical text‑guided latent upscaler trained for 1.25M steps on 10M high‑res images, and is exposed directly by the `StableDiffusionUpscalePipeline` in Diffusers; it performs a 4× image super‑resolution with optional low‑noise guidance and prompt control. [HF model card; Diffusers API]
- Real‑ESRGAN is a widely adopted, BSD‑licensed practical super‑resolution GAN with robust inference utilities, tiling, and multiple pretrained weights (x2/x4; anime/general). It’s a strong non‑diffusion baseline with good speed/quality trade‑offs and mature community support. [Upstream repo]

Citations:
- stabilityai/stable-diffusion-x4-upscaler model card and license (Open RAIL++). See Hugging Face.  
- Diffusers StableDiffusionUpscalePipeline docs (example usage and parameters).  
- Real‑ESRGAN official repository (BSD‑3‑Clause; inference options; tiling; x2/x4 weights).  

---

## 3) Scope and Non‑Goals

In Scope (M5.B):
- Add real upscalers behind the existing `upscale` step.
- Minimal API extension: `chain.upscale.impl?: 'auto' | 'diffusion' | 'gan'`.
- Model acquisition/caching; environment knobs strictly necessary for correctness/perf.
- Tiled inference (GAN) and memory‑aware settings (Diffusion) to avoid OOM.
- Persist per‑step metadata documenting algorithm/model/scale for receipts.
- Tests (fake and live with Compose) and a live script that exercises both impls.

Out of Scope (stay deferred):
- New SSE event kinds, new progress schema, or a general pipeline grammar.
- Face‑enhance passes (GFPGAN) or post‑filters.
- Provider adapters; background downloader jobs.

---

## 4) Contracts (Lean API Extension)

Request (POST `/v1/jobs`), unchanged defaults; new optional fields under the existing chain:

- Existing:
  - `chain.upscale.scale: 2 | 4` (default 2)
- New (optional):
  - `chain.upscale.impl: 'auto' | 'diffusion' | 'gan'` (default `'auto'`)
  - `chain.upscale.strict_scale: boolean` (default `false`) — when `true`, reject requests where the chosen `impl` cannot natively realize the requested `scale` (e.g., `diffusion` with `scale=2`).

Resolution policy:
- `impl=auto` (default):
  - `scale=2` → use GAN (Real‑ESRGAN x2plus)
  - `scale=4` → use Diffusion (SD x4 Upscaler)
- `impl=gan`: use Real‑ESRGAN (x2plus or x4plus by scale)
- `impl=diffusion`: use SD x4 upscaler; if `scale=2`, run x4 then downsample to 2× (documented quality note) or reject with `422` behind a feature flag (choose at implementation time; default: downsample).

Responses, logs, SSE: no changes.

Persistence: record `steps.metadata_json` for `upscale` with `{ impl, model, version, scale, params }`.

---

## 5) Architecture & Integration

### 5.1 Upscaler Adapter Interface

Add a small adapter layer so the worker’s `upscale` task can dispatch to a chosen implementation without branching explosion.

- New module: `services/worker/upscalers/` with:
  - `base.py` — `class Upscaler(Protocol): run(img: PIL.Image, scale: int, **kw) -> PIL.Image`
  - `realesrgan.py` — loads weights, supports `scale ∈ {2,4}`, tiles, half‑precision on CUDA.
  - `sdx4.py` — wraps Diffusers `StableDiffusionUpscalePipeline`; params: `prompt`, `negative_prompt`, `guidance_scale`, `noise_level`, `num_inference_steps`.
  - `registry.py` — `get_upscaler(impl: str) -> Upscaler` with env and per‑step metadata.

`services/worker/tasks/upscale.py` becomes a thin orchestrator:
- Read `impl` (defaulting to `auto`), map to concrete upscaler by rules in §4.
- Fetch previous step’s artifacts, stream per‑item processing and artifact writes as today.
 - Run heavy GPU work inside a child subprocess to satisfy OR‑001 (GPU memory cleanup) and isolate failures. The parent process only coordinates I/O and events.

### 5.2 Model management

- Diffusion (SD x4): rely on `diffusers` lazy model cache in `/root/.cache/huggingface` (or `$HF_HOME`). Allow optional model override via env (`DF_UPSCALE_SDX4_ID`, default `stabilityai/stable-diffusion-x4-upscaler`).
- GAN (Real‑ESRGAN): store weights under `/models/realesrgan/` by default. Accept env overrides and ensure idempotent downloader in code on first use. Weights:
  - `RealESRGAN_x4plus.pth` (general 4×)
  - `RealESRGAN_x2plus.pth` (general 2×)
  - Optionally expose `realesr-general-x4v3.pth` later for speed.
- Registry: optionally upsert these into `models` table (`kind: 'upscaler-gan' | 'upscaler-diffusion'`) with `source_uri`, `version`, `capabilities: ['upscale']` once downloaded; implementation may start with on‑demand download without an admin flow.

### 5.4 Tiled inference (shared utility)

Adopt the PoC’s overlap‑and‑feather tiling strategy for large inputs to control VRAM and avoid seams:

- Inputs are split into `tile_in × tile_in` regions with `overlap_in` pixels of overlap; outputs are alpha‑blended into a canvas using a cosine‑squared feather mask sized to the upscaled tile.
- Auto‑enable tiling when `max(W,H) ≥ 1024` (configurable) or when `W×H×scale²` exceeds a megapixel threshold.
- Expose minimal env knobs (worker): `DF_UPSCALE_TILE_IN` (default `256`), `DF_UPSCALE_OVERLAP_IN` (default `32`), `DF_UPSCALE_AUTO_TILE` (default `1`).
- Implement once in `services/worker/upscalers/tiles.py` to be shared by both SD x4 and Real‑ESRGAN backends.

### 5.3 Memory & Performance

- Diffusion (SD x4): enable fp16 on CUDA, attention slicing/tiling flags (reusing patterns from generate runner), and allow `DF_SDP_BACKEND`, `DF_ENABLE_XFORMERS`, `DF_MODEL_CPU_OFFLOAD` toggles. Provide `DF_UPSCALE_SDX4_STEPS` (default 50–75) and `DF_UPSCALE_SDX4_GUIDANCE` (default 7.5–9.0). See Diffusers docs for parameters and defaults.
- GAN (Real‑ESRGAN): default to tiled inference when the input×scale product exceeds a threshold (e.g., 8 MPx). Expose `DF_UPSCALE_RE_TILE` (size, default 256–512) and `DF_UPSCALE_RE_HALF` (fp16 on CUDA). Real‑ESRGAN code supports `--tile`, `--half`. We mirror those as function params.

---

## 6) Epics, ACs, and Tasks

### E5B‑1 — Model Selection, ADR, and Rationale
- Write a brief ADR (docs/adr/2025‑09‑m5b-upscalers.md) recording the choice of SD x4 (diffusion) and Real‑ESRGAN (GAN) with trade‑offs and constraints (VRAM, quality, speed). Include links to sources and internal research.
- AC: ADR merged; scope aligns with §4; risk notes captured.

### E5B‑2 — API Surface (Lean Extension)
- Schema: extend `services/api/schemas/jobs.py` `ChainUpscale` with optional `impl: Literal['auto','diffusion','gan']`, default `'auto'`.
- Also add optional `strict_scale: bool = False` to allow strict vs downgrade behavior.
- Route: accept and persist `impl` and `strict_scale` into `Step.metadata_json` for `upscale`.
- AC: Back‑compat confirmed; invalid `impl` → 422; omitting keeps old behavior; `strict_scale=true` causes `422 invalid_input` if the impl cannot natively realize the requested scale.

### E5B‑3 — Worker Adapter + Pluggable Implementations
- Create `services/worker/upscalers/{base,registry}.py`.
- Move current Pillow path into `services/worker/upscalers/pillow_fallback.py` (used only as last resort on fatal failures).
- AC: `get_upscaler('diffusion')` and `get_upscaler('gan')` return callables; `auto` resolves per §4.

### E5B‑4 — Real‑ESRGAN Integration (GAN)
- Add `services/worker/upscalers/realesrgan.py` using upstream model defs (RRDBNet) and the `RealESRGANer` inference helper; support x2/x4 and tiling.
- Add idempotent weight downloader to `/models/realesrgan` with hash checks.
- AC: Given a 1024×1024 input, x2 and x4 complete without OOM on a 12–24 GB GPU using tiling; artifacts saved under `/upscale/` with correct metadata.

### E5B‑5 — SD x4 Integration (Diffusion)
- Add `services/worker/upscalers/sdx4.py` built on `StableDiffusionUpscalePipeline.from_pretrained('stabilityai/stable-diffusion-x4-upscaler', variant='fp16')`; fp16 on CUDA; memory toggles.
- Integrate tiled path using the shared tiling util and feather blending. Defaults: enable tiling automatically for ≥1024 inputs.
- AC: Given a 512×512 input, x4 succeeds (→ 2048×2048) within acceptable VRAM on 12–24 GB GPUs; for 1024×1024, tiled mode succeeds (→ 4096×4096) on 12 GB GPUs; artifacts correct; prompt defaults to a conservative, content‑preserving string (e.g., `"high quality, detailed"`) unless provided.

### E5B‑6 — Orchestrator Wiring + Fallbacks
- Update `services/worker/tasks/upscale.py` to read `impl` and dispatch via the registry. If the chosen impl fails with a classifiable error (e.g., OOM), retry once with the GAN implementation (x2/x4) or Pillow, preserving failure events if terminal.
- Respect `strict_scale=true`: do not auto‑downgrade; return `422` from API preflight or fail the step with `error.code='invalid_scale'`.
- AC: Failure path produces clear error event and leaves generate artifacts intact; strict vs fallback honored.

### E5B‑7 — Persistence & Models Registry (Optional in M5.B)
- Upsert upscaler entries into `models` table (kinds: `upscaler-diffusion`, `upscaler-gan`), including `source_uri` and local file lists for GAN weights.
- AC: `GET /v1/models` lists installed upscalers when enabled; `capabilities` includes `upscale`.

### E5B‑8 — Tests & Validation
- Unit tests for adapter resolution, metadata persistence, and error mapping.
- Integration tests with `DF_CELERY_EAGER=true` using a small image and mocked diffusers/Real‑ESRGAN calls to keep CI light.
- Live validators:
  - `scripts/validate_m5b_live.py` runs two jobs: (a) generate 512 → upscale 4× with diffusion; (b) generate 1024 → upscale 2× with GAN; verifies artifacts and presigned URLs.
  - `scripts/run_live_generate2_upscale.py` extended with `impl` flag to exercise both paths.
- AC: CI green (fake/mocked); Live script verified on Compose stack with GPU.

Add tile‑specific checks:
- Assert no visible seam along tile boundaries by comparing overlapped regions’ mean absolute difference below a small epsilon.
- Verify feather alpha normalization (sum of mask weights ≥ 0.99 everywhere after compositing).

### E5B‑9 — Docs & DX
- Update Masters 10 with the `impl` field; add examples and parameter table for both implementations.
- Short HOWTO: "Choosing an Upscaler (auto/diffusion/gan)" under `docs/guides/` with VRAM guidance and caveats.

---

## 7) Configuration (Minimal, Explicit)

- `DF_UPSCALE_IMPL_DEFAULT` (api/worker): `'auto' | 'diffusion' | 'gan'` (default `'auto'`).
- Diffusion specific (worker): `DF_UPSCALE_SDX4_ID` (default `stabilityai/stable-diffusion-x4-upscaler`), `DF_UPSCALE_SDX4_STEPS` (default `50`), `DF_UPSCALE_SDX4_GUIDANCE` (default `7.5`), `DF_UPSCALE_SDX4_NOISE_LEVEL` (default `20`).
- GAN specific (worker): `DF_UPSCALE_RE_WEIGHTS_DIR` (default `/models/realesrgan`), `DF_UPSCALE_RE_HALF` (default `1`), `DF_UPSCALE_RE_TILE` (default `512`).

Scale policy & tiling:
- `DF_UPSCALE_STRICT_SCALE` (default `0`) — process fails if impl cannot natively realize requested scale.
- `DF_UPSCALE_TILE_IN` (default `256`), `DF_UPSCALE_OVERLAP_IN` (default `32`), `DF_UPSCALE_AUTO_TILE` (default `1`).

All knobs optional with safe defaults; absence keeps behavior compatible.

---

## 8) Risks & Mitigations

- VRAM spikes (Diffusion): mitigate with fp16, attention slicing, CPU offload, and recommend 12+ GB for 2048×2048 targets. Fall back to GAN if OOM persists.
- Packaging instability (GAN via pip): avoid fragile third‑party wrappers; integrate from official repo (BasicSR) and control weights explicitly. Optionally support NCNN/Vulkan path later.
- Throughput: SD x4 is slower than GAN; default `impl=auto` maps scale 4 to diffusion, but we can let operators flip default via env.
- Determinism: uphold seed in generate; upscale steps are not seeded today—document non‑determinism for diffusion upscaler.

---

## 9) How To Add More Upscalers Later (Adapter Path)

- Add a new file under `services/worker/upscalers/{name}.py` implementing `Upscaler`.
- Register it in `registry.py` (name → loader) and document any required weights/env.
- Extend `ChainUpscale.impl` with an enum value only after a brief ADR; otherwise expose it behind `'auto'` mapping.
- Candidate additions captured in research doc: SwinIR (Transformer), BSRGAN variants, 4x‑UltraSharp ESRGAN model for crisp edges.

---

## 10) Definition of Done (M5.B)

- API accepts and persists `chain.upscale.impl` (default `auto`); back‑compat intact.
- GAN and Diffusion implementations ship; default `auto` mapping works out of the box.
- Live validators succeed on Compose with GPU; artifacts have correct dimensions and metadata; combined progress untouched.
- Docs updated (Masters 10 examples + short HOWTO); ADR merged.

---

## 11) Appendix: Key Sources

- Stable Diffusion x4 Upscaler model card and license (Open RAIL++), training summary, and usage notes — Hugging Face `stabilityai/stable-diffusion-x4-upscaler`.
- Diffusers StableDiffusionUpscalePipeline documentation (class, parameters, example usage).
- Real‑ESRGAN official repository (BSD‑3‑Clause; tiling; x2/x4 models; python and NCNN inference options).

---

## Addendum A — Asset Storage and Prefetch Strategy (Registry + Cache)

Last updated: 2025-09-15

### A.1 Summary

We will treat model assets via two physical storage modes while unifying them under a single logical registry and loader precedence:

- Registry‑managed assets (deterministic, checksummed files under `DF_MODELS_ROOT`). Examples: SDXL checkpoints, Real‑ESRGAN x2/x4 weights, mirrored Diffusers repos.
- Runtime‑cached assets (library‑managed caches such as `HF_HOME`). Example: SD x4 upscaler pulled by Diffusers.

The registry remains the source of truth (provenance, capabilities, install status). Loaders follow a consistent precedence:

1) Explicit local mirror (when configured) → 2) registry `local_path` → 3) runtime cache → 4) remote fetch (off by default in prod; allowed by CLI prefetch tools).

This keeps operations simple, scales to “many models”, enables offline installs, and preserves fast library‑native experiences.

### A.2 Goals and Non‑Goals

Goals:
- Support “many models” with a generic manifest‑driven prefetch tool.
- Maintain reproducible‑enough receipts: sha256 for registry files; repo+revision for HF caches/mirrors.
- Keep loaders simple and deterministic when mirrors exist; otherwise fall back to cache.

Non‑Goals:
- No new public API endpoints for prefetch; this is CLI/ops‑facing.
- No DB migrations; use existing `models` table with `parameters_schema` to record `external_ref` metadata.

### A.3 Data Model Mapping (No Schema Change)

- Use `models.parameters_schema` to store external/cached origin for non‑registry assets:
  - Example for SD x4: `{ "external_ref": { "hf_repo": "stabilityai/stable-diffusion-x4-upscaler", "revision": "main" }, "mirror_path": null }`
  - Example for a mirrored repo: same `external_ref` plus a `mirror_path` pointing under `DF_MODELS_ROOT`.
- For registry‑managed files (e.g., Real‑ESRGAN), keep the current pattern: `local_path` + `files_json` (sha256). `capabilities` includes `upscale`.
- `installed=true` means “ready to use” regardless of mode. For cache‑only entries, `files_json` may be `[]` but `parameters_schema.external_ref` must be present.

### A.4 CLI Prefetch (Design)

- New module: `tools/dreamforge_cli/prefetch.py` and `assets` subcommand in the CLI.
- Commands:
  - `dreamforge assets prefetch --bundle upscalers [--models-root ...]` seeds SD x4 cache and Real‑ESRGAN x2/x4 weights.
  - `dreamforge assets prefetch --manifest docs/assets/prefetch.json` supports arbitrary assets.
  - `dreamforge assets verify --manifest ...` verifies registry items (sha256) and attempts local‑files‑only Diffusers load for mirrors/caches.
- Manifest (JSON) entries (examples):
  - Registry model via a direct URL with checksum:
    `{ "type": "registry_model", "kind": "upscaler-gan", "name": "realesrgan", "version": "x4plus", "source": { "adapter": "direct", "url": "https://.../RealESRGAN_x4plus.pth", "sha256": "..." } }`
  - Diffusers cache:
    `{ "type": "diffusers_cache", "repo": "stabilityai/stable-diffusion-x4-upscaler", "revision": "main" }`
  - Optional HF snapshot mirror (full repo to `DF_MODELS_ROOT`):
    `{ "type": "registry_model", "kind": "upscaler-diffusion", "name": "sdx4", "version": "<commit>", "source": { "adapter": "hf-snapshot", "repo": "stabilityai/stable-diffusion-x4-upscaler", "revision": "<commit>" } }`

Adapters:
- Reuse existing `downloader.download()` for any `registry_model` entry; add a small `direct` adapter (URL + sha256) and a `hf-snapshot` adapter (optional, later).
- For `diffusers_cache`, a helper imports Diffusers and runs `from_pretrained(..., local_files_only=False)` once to seed `HF_HOME` (settable to `DF_MODELS_ROOT/hf-cache`). Then upsert a registry record with `parameters_schema.external_ref` and `installed=true`.

### A.5 Loader Precedence Changes

- SD x4 loader (worker `sdx4.py`):
  - If `DF_UPSCALE_SDX4_DIR` points to a valid mirror, call `from_pretrained(DF_UPSCALE_SDX4_DIR, local_files_only=True)`.
  - Else use repo+revision (`parameters_schema.external_ref`) with `from_pretrained(model_id or repo)`, allowing cache usage.
  - Keep memory toggles unchanged.
- Real‑ESRGAN loader uses `local_path` only (registry‑managed weights).

### A.6 Make Targets (Generic)

- `assets-prefetch`:
  - Default bundle: upscalers.
  - Implementation: `uv run python -m tools.dreamforge_cli assets prefetch --bundle upscalers --models-root ${DF_MODELS_ROOT:-$HOME/.cache/dream-forge}`.
  - Optional manifest: `make assets-prefetch MANIFEST=docs/assets/prefetch.json`.
- `assets-verify`:
  - `uv run python -m tools.dreamforge_cli assets verify --manifest ${MANIFEST}`.
- These targets remain generic as we add models; the manifest drives scope.

### A.7 Epics and Tasks

E5B‑A1 — Registry Metadata & Receipts (no DB change)
- Record `external_ref` and optional `mirror_path` under `parameters_schema` when installing cache‑based or mirrored assets.
- AC: `GET /v1/models` returns entries with these fields in the `parameters_schema` blob when present; `installed=true` reflects ready‑to‑use state.

E5B‑A2 — CLI Prefetch (assets subcommand)
- Add `tools/dreamforge_cli/prefetch.py` with:
  - `prefetch_manifest(path)` that iterates assets and dispatches per type.
  - Direct adapter: verified download (URL + sha256) wiring into `downloader.download()`.
  - Diffusers cache seeding helper; optional HF snapshot mirroring.
- Extend `tools/dreamforge_cli/main.py` with `assets prefetch|verify` subcommands.
- AC: `assets prefetch --bundle upscalers` succeeds on a fresh machine (with network) and prints receipts (registry ids or cache commits).

E5B‑A3 — Loader Precedence & Env Knobs
- SD x4 loader supports `DF_UPSCALE_SDX4_DIR` and uses mirror when present; otherwise uses repo/cache.
- Prefer `HF_HOME=${DF_MODELS_ROOT}/hf-cache` to keep everything on one volume.
- AC: With mirror set, SD x4 loads offline; with only cache, loads online once then offline; with neither, raises a clear error.

E5B‑A4 — Make Targets
- Add `assets-prefetch` and `assets-verify` targets; wire to CLI as described.
- AC: `make assets-prefetch` seeds SD x4 cache and ESRGAN weights; `make assets-verify` reports OK.

E5B‑A5 — Tests & Validation
- Unit tests: manifest parsing, direct adapter (temp files), and registry upsert behavior.
- Integration (no network): fake adapters that write temp files; assert downloader receipts and registry state.
- Live (optional): run `assets prefetch` against real SD x4 + ESRGAN URLs; then run `scripts/validate_m5b_live.py`.
- AC: CI uses fake adapters; live docs include real steps.

### A.8 Risks & Mitigations

- Network volatility: direct adapter verifies sha256; retries optional.
- Cache drift: keep repo+revision in registry; encourage `HF_HOME` under `DF_MODELS_ROOT` to co‑locate caches with managed models for retention policies.
- Storage growth: document budgets and simple pruning (`hf-cache` TTL; `assets-clean` target optional later).

### A.9 Definition of Done (Addendum)

- CLI `assets prefetch` and `assets verify` shipped with manifest support and upscaler bundle.
- SD x4 loader honors `DF_UPSCALE_SDX4_DIR` for mirrors; otherwise uses repo/cache.
- Make targets available and generic; docs updated with manifest schema and examples.
