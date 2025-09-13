# M1 — E2E Generate v0 (Happy Path)

Last updated: 2025-09-13

Status: Proposed plan (awaiting sign‑off)

Owners: Engineering (Delivery), DX (Contracts), Product (Scope)

Related Masters: 08-roadmap (M1), 03-requirements, 04-architecture, 05-systems, 06-data-model, 07-interfaces, 10-openapi-makefile-cli

---

## 1) Executive Summary

Deliver a thin, end‑to‑end “generate one image” workflow fully inside containers with GPU access via NVIDIA Container Toolkit + CDI. The API accepts a generate job, the worker runs an SDXL (EpicRealism‑XL) runner on GPU, produces one artifact to MinIO, and job status becomes `succeeded`. This slice favors containerized execution over host‑run to exercise operational posture early.

Key emphasis per feedback:
- Prefer container GPU using CDI (not host execution), with helper scripts to generate CDI spec and to inspect environment.
- Borrow patterns from the local working example at `/home/chrishomer/projects/personal/example` (for CDI generation and env inspection) and integrate equivalent helpers (`make inspect-env`, `make gpu-cdi-generate`).

Out of scope for M1: artifacts listing, logs endpoint, progress polling/SSE, batch (`count > 1`), downloader and model registry APIs, retries/DLQ, and full GPU hygiene enforcement (all planned for M2–M5 per roadmap 08).

---

## 2) Scope and Deliverables

### 2.1 API (v1 subset)
- `POST /v1/jobs` (type=generate): validate body; create Job with `status=queued`; create Step `generate`; enqueue Celery task; return 202 Accepted.
- `GET /v1/jobs/{id}`: return job, step status, and summary (count=1, completed=0|1).
- Standard error envelope from Masters 07 §6 for validation/infra errors.
- OpenAPI regenerated and committed (docs/openapi/openapi.v1.json) with examples.

### 2.2 Worker & Runner
- Celery task `jobs.generate(job_id)` supervises lifecycle (queued→running→succeeded/failed), runs one image generation in a subprocess runner, persists one Artifact row, uploads artifact to MinIO, and closes out Job/Step states.
- Real runner: SDXL (EpicRealism‑XL) via Diffusers + PyTorch CUDA on GPU.
- Fake runner: Pillow‑based image for CI/non‑GPU environments (guarded by `DF_FAKE_RUNNER=1`).

### 2.3 Storage & Artifacts
- Upload to MinIO (private bucket) with keying: `dreamforge/default/jobs/{job_id}/generate/{ts}_0_{w}x{h}_{seed}.{ext}`.
- Persist corresponding `artifacts` row with `item_index=0`, `seed`, `width`, `height`, `format`, `s3_key`.

### 2.4 Container GPU via CDI (Primary Path)
- Expect NVIDIA drivers + NVIDIA Container Toolkit installed on the host; use CDI for device injection.
- Provide helpers to generate CDI spec (`make gpu-cdi-generate`) and inspect environment (`make inspect-env`).
- Compose targets container GPU by default for the worker; host‑run worker is a fallback only for troubleshooting.

### 2.5 DevEx
- `make` targets: `inspect-env`, `gpu-cdi-generate`, `up`, `down`, `logs`, `status`.
- DEV.md gains a concise “Container GPU via CDI” runbook and a smoke‑test section.

---

## 3) Acceptance Criteria

Functional
- A valid `POST /v1/jobs` with `type=generate` returns `202` and enqueues a job.
- The worker (in a container with GPU via CDI) generates exactly one image artifact using SDXL; MinIO contains the artifact with documented keying; DB has a matching `artifacts` row.
- `GET /v1/jobs/{id}` transitions through `queued`/`running` to `succeeded` for the happy path.

Contracts & Docs
- Error responses use the standardized envelope.
- `docs/openapi/openapi.v1.json` includes POST/GET endpoints with minimal examples; CI spec diff passes.
- DEV.md includes “Container GPU via CDI” steps and a smoke test; `make inspect-env` prints host/container GPU context.

Non‑Goals (explicit deferrals)
- No `/artifacts`, `/logs`, `/progress` or `/progress/stream` in M1 (M2).
- No batch (`count > 1`) (M4).
- No downloader/registry APIs (M3–M4). Default model is a local path.
- No idempotency enforcement or retries/DLQ (M5). We only accept and store `Idempotency-Key`.
- No GPU hygiene enforcement/metrics beyond best‑effort cleanup (M5).

---

## 4) Container GPU via CDI — Design & Runbook

### 4.1 Host prerequisites
- NVIDIA drivers present (verify with `nvidia-smi`).
- NVIDIA Container Toolkit installed (`nvidia-ctk --version`).
- Docker Engine ≥ 24 with Compose v2.

### 4.2 CDI device spec generation
- Use `nvidia-ctk cdi generate --output-file /etc/cdi/nvidia.yaml` (requires sudo) to write a CDI spec for GPUs.
- Optional: set runtime to prefer CDI mode `nvidia-ctk config --in-place --set nvidia-container-runtime.mode=cdi` then `systemctl restart docker`.
- Provide `make gpu-cdi-generate` to automate.
- Reference the working example at `/home/chrishomer/projects/personal/example` and mirror its behavior (names, device labels) where possible to avoid surprises.

### 4.3 Compose integration (worker)
- Worker runs in a CUDA‑enabled image; request GPU using CDI. Two patterns will be supported:
  - Primary: NVIDIA runtime in CDI mode with `NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility`.
  - Alternative: `gpus: all` (device requests) if your Docker/Compose prefers that style; we’ll choose one based on your local example and document the other as fallback.
- Mount a `models` volume at `/models` and set `DF_MODELS_ROOT=/models`.

### 4.4 Environment inspection
- `make inspect-env` prints: OS/kernel, Docker versions, Docker runtimes, NVIDIA drivers, `nvidia-ctk` info, CDI specs under `/etc/cdi`, group membership, and DF/NVIDIA env.
- We will compare its output to `/home/chrishomer/projects/personal/example`’s environment script and harmonize field names for easier cross‑checking.

---

## 5) Runner & Image Strategy

### 5.1 Real runner (SDXL, EpicRealism‑XL)
- Framework: PyTorch + Diffusers running in FP16 on CUDA.
- Image base: CUDA/PyTorch runtime image (e.g., `pytorch/pytorch:2.3.x-cuda12.1-cudnn8-runtime`) to avoid compiling CUDA.
- Dependencies: diffusers, transformers, accelerate, safetensors, Pillow, torchvision; keep extras minimal to respect image size.
- Model path: resolved from `DF_GENERATE_MODEL_PATH` or `DF_MODELS_ROOT` + `DF_DEFAULT_MODEL_DIR` (e.g., `/models/sdxl/EpicRealism-XL@<ver>`). M1 expects the model to be preinstalled on the host volume (downloader arrives M3–M4).
- Seed: if provided, use it; else pick random immediately before sampling.

### 5.2 Fake runner (CI)
- Pillow‑generated image; same artifact path/metadata; toggled by `DF_FAKE_RUNNER=1`.
- Used in unit/integration tests and GitHub Actions; real GPU smoke is manual/local.

---

## 6) Implementation Plan (Tickets)

API & Contracts
- E1‑1 Schemas: Pydantic models for JobCreateRequest/JobCreatedResponse/JobStatusResponse; error envelope middleware.
- E1‑2 Endpoints: `POST /v1/jobs`, `GET /v1/jobs/{id}`; validation; idempotency key acceptance (store hash only).
- E1‑3 OpenAPI: regenerate and commit; add minimal examples; CI spec diff.

Persistence & Queue
- E1‑4 Repositories: jobs/steps/events/artifacts minimal DAO.
- E1‑5 Enqueue: Redis/Celery publisher with correlation id propagation.

Worker & Runner
- E1‑6 Task: `jobs.generate` lifecycle handling and error mapping.
- E1‑7 Fake runner: Pillow implementation + toggle.
- E1‑8 Real runner: SDXL integration on CUDA; configurable model path.
- E1‑9 S3 writer: MinIO upload + artifact row; keying per spec.

Container GPU via CDI
- E1‑10 CDI helpers: `make inspect-env` (env snapshot) and `make gpu-cdi-generate` (CDI spec generation); verify parity with `/home/chrishomer/projects/personal/example`.
- E1‑11 Worker image: switch to CUDA/PyTorch runtime; ensure `nvidia-smi` works in container; document two patterns (CDI runtime env vs `gpus: all`).
- E1‑12 Compose: mount `/models`; set DF_MODELS_ROOT; add GPU env; choose the GPU request style based on your local example.

DevEx & Docs
- E1‑13 DEV.md: “Container GPU via CDI” instructions + smoke test steps.
- E1‑14 Mini integration guide: curl examples for M1, artifact verification, troubleshooting.
- E1‑15 Masters sync: minor note in 10‑openapi milestone coverage to match 08‑roadmap (GPU hygiene/idempotency in M5).

Testing
- E1‑16 Unit: API validation, error envelope shape, enqueue calls.
- E1‑17 Integration (fake): full happy path using `DF_FAKE_RUNNER=1` → artifact row + status succeeded.
- E1‑18 Manual GPU smoke: container GPU run on your machine per “Smoke Test” section; keep a checklist and paste logs into PR.

---

## 7) Smoke Test (Container GPU via CDI)

1) Inspect environment: `make inspect-env` (confirm drivers, nvidia-ctk, CDI spec presence).
2) Generate CDI spec if missing: `make gpu-cdi-generate` (will write `/etc/cdi/nvidia.yaml`).
3) Place EpicRealism‑XL under the mounted models root (`/models/...`) with expected filenames for Diffusers.
4) Start stack: `make up`.
5) Confirm GPU visibility: `docker compose exec worker nvidia-smi` (should list GPUs).
6) POST job:
   ```
   curl -sS http://127.0.0.1:8001/v1/jobs \
     -H 'Content-Type: application/json' \
     -d '{"type":"generate","prompt":"an old-growth forest at dawn","width":1024,"height":1024,"steps":24,"guidance":7.0,"format":"png"}'
   ```
7) Poll status until `succeeded`: `curl -sS http://127.0.0.1:8001/v1/jobs/<id>`.
8) Verify artifact: check MinIO bucket `dreamforge` for the expected key; confirm one `artifacts` row in DB.

---

## 8) Risks & Mitigations

- Driver/runtime mismatch: use `make inspect-env` to surface versions and CDI presence; document expected versions; include common fixes.
- CUDA/PyTorch image size: choose runtime image (not devel); keep dependencies lean.
- Model path drift: standardize via `DF_MODELS_ROOT` + `DF_DEFAULT_MODEL_DIR` until registry arrives (M3–M4).
- CDI vs `gpus: all` variations: codify one primary path based on your local example; document the alternative succinctly.

---

## 9) Timeline & Sequencing (suggested)

1) Contracts: schemas + endpoints + OpenAPI (E1‑1..E1‑3)
2) Repos + enqueue (E1‑4..E1‑5)
3) Fake runner + artifact write (E1‑6..E1‑9 using DF_FAKE_RUNNER=1) → green integration test
4) Container GPU enablement: CDI helpers + worker image + Compose (E1‑10..E1‑12)
5) Real runner integration (E1‑8) + manual smoke
6) Docs + guides (E1‑13..E1‑15)
7) Final validation and sign‑off

---

## 10) Decisions Incorporated (from owner feedback)

- CDI pattern: Follow your example repo’s CDI devices pattern — Compose `devices: [{ driver: cdi, device_ids: ["nvidia.com/gpu=all"] }]`. No `runtime: nvidia` or `gpus: all` fallback unless needed.
- Env inspection: Keep our `scripts/inspect_env.sh` but align content with your example’s inspection (GPU list, Docker runtimes, CDI devices). Output already shows CDI devices and versions.
- Default model path: `${HOME}/.cache/dream-forge/civitai/epicrealismXL_working.safetensors`. We will load SDXL via Diffusers `StableDiffusionXLPipeline.from_single_file()` using this checkpoint.
- Smoke defaults: 256x256, 10 steps, FP16. Runtime defaults remain 1024x1024, 30 steps.
- Runner base image: Use best judgement; we’ll use `pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime` for broad compatibility and smaller size, then install Diffusers stack.
- Idempotency: Keep simple in M1 — accept/store header only; full behavior deferred to M5.
- Metrics: Minimal (job counts/status) in M1; richer metrics/logs/SSE deferred to M2+.

---

## 11) Sign‑off Checklist

- [x] CDI approach chosen and documented (matches local example)
- [x] Environment inspection output matches expectations
- [x] Default model path confirmed
- [x] Runner base image chosen (pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime)
- [x] M1 defaults (size/steps/precision) agreed
- [x] Idempotency scope confirmed
