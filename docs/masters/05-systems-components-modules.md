# Dream Forge — Masters Document 5: Systems (Components and Modules)

Last updated: 2025-09-12

Status: Draft for review

Owners: Engineering (Architecture), Product (Scope), DX (API Contracts)

References: docs/masters/01-introduction-vision-goals.md, docs/masters/02-principles-of-system-design.md, docs/masters/03-requirements.md, docs/masters/04-architecture-overview.md

---

## 1) Purpose

Detail the concrete components, submodules, responsibilities, dependencies, and interfaces that implement the Architecture Overview. This document is the handoff blueprint for implementation and reviews.

Lean constraint: MVP ships with two core services — `api` and `worker` — plus infra (Redis, Postgres, MinIO). New services require an ADR (Doc 2 §3.11).

---

## 2) Component Map (MVP)

- API Service (FastAPI)
  - HTTP Layer (routers/controllers, OpenAPI, validation)
  - Job Service (create/status/artifacts/logs/progress, SSE)
  - Models Endpoints (list/detail from registry)
  - Progress Aggregator (DB-tailed)
  - Error Handling (standardized envelope)
  - Config/Secrets (Pydantic Settings)
  - Observability (NDJSON logs, Prometheus)
  - Dependencies: Postgres (read/write), Redis (publish), MinIO (read), Settings/Metrics

- Worker Service (Celery)
  - Task Runner (generate)
  - Step Executor (subprocess, timeouts)
  - Runner Manager (job-type runners; batch loop)
  - GPU Resource Monitor (NVML/framework stats)
  - Artifact Writer (to MinIO, metadata embed)
  - Event Writer (Steps/Events to Postgres)
  - Preset Manager (VRAM/quality settings)
  - Retry/Backoff, DLQ handling
  - Dependencies: Postgres (write), MinIO (write), Settings/Metrics

- Runners (Subsystem)
  - Runner Protocol (prepare/run_step/emit/cleanup)
  - Generate Runner (SDXL/EpicRealism‑XL)
  - Batch Support (count 1–100, per-item runtime seeds)
  - GPU Hygiene (OR‑001)
  - Optional Container Isolation (NVIDIA Toolkit + CDI)

- Model Registry (Subsystem)
  - Model DAO/Repository (CRUD)
  - Parameters Schema (JSON Schema)
  - Capabilities and status (installed/enabled)
  - API integration (list/detail)

- Unified Downloader (CLI)
  - Commands: download, verify, list
  - Source Adapters: huggingface, civitai (pluggable)
  - Descriptor Writer + Registry Upsert

- Persistence (Postgres)
  - Entities: Job, Step, Event, Artifact, Model
  - Repositories, Alembic migrations, indices

- Storage (MinIO/S3)
  - S3 client, keying convention with batch index
  - Presigned URLs, TTL, metadata embedding

---

## 3) API Service

Responsibilities:

- Expose `/v1` endpoints (FR‑001) and models listing (FR‑088..089).
- Validate requests and enforce constraints (batch count ≤ 100; seed semantics).
- Create Jobs (idempotent), enqueue tasks, and read Job/Step/Event/Artifact data.
- Aggregate progress (including batch average) and stream SSE.

Internal modules:

- `api.http.routes.jobs`: routers for create, status, artifacts, logs, progress, SSE.
- `api.http.routes.models`: routers for list/detail from Model registry.
- `api.schemas`: Pydantic models for requests/responses; OpenAPI generation.
- `api.services.jobs`: job service with idempotency, progress aggregation.
- `api.services.models`: model read service with schema exposure.
- `api.adapters.queue`: enqueue to Celery via Redis.
- `api.adapters.db`: repositories for Job/Step/Event/Artifact/Model.
- `api.adapters.s3`: presigned URLs and artifact listings.
- `api.telemetry`: logging (NDJSON), metrics (Prometheus), request IDs.
- `api.config`: Pydantic Settings; `.env` support.

Key interfaces:

- JobRepository: `create(job)`, `get(job_id)`, `get_with_steps(job_id)`
- EventRepository: `tail(job_id, since_ts, limit)`, `append(event)`
- ArtifactRepository: `list(job_id)`
- ModelRepository: `list(enabled_only=True)`, `get(model_id)`
- QueuePublisher: `enqueue_generate(job_id)`
- ProgressAggregator: `compute(job_id)` (uses recent Events + stage weights)

Error handling:

- Envelope `{code, message, details, correlation_id}` with stable codes.
- `422` for validation, `404` not found, `409` for idempotency conflicts, `503` for infra outages.

SSE implementation:

- DB-tailed polling with delta queries; emits per-item events (with `item_index`) and aggregate progress.

---

## 4) Worker Service

Responsibilities:

- Execute job steps under Celery with subprocess isolation and timeouts.
- Enforce presets and VRAM headroom; instrument GPU usage; cleanup (OR‑001).
- Emit Events, write Steps/Artifacts, handle retries/backoff and DLQ.

Internal modules:

- `worker.celery.app`: Celery app/config.
- `worker.tasks.generate`: task entrypoint for generate jobs.
- `worker.exec.supervisor`: subprocess wrapper (timeouts, signals, exit code mapping).
- `worker.runners.manager`: resolve `model_id` and job-type runner, prepare device/preset.
- `worker.runners.generate`: SDXL/EpicRealism‑XL runner implementation.
- `worker.gpu.monitor`: NVML/framework sampling (before/after/peak), VRAM headroom checks.
- `worker.artifacts.s3`: write artifacts (keying with `item_index`), embed metadata.
- `worker.events.writer`: Steps/Events persistence; progress event helpers.
- `worker.presets`: per-GPU-class presets (resolution, steps, scheduler, headroom).

Batch execution semantics (FR‑007, FR‑014, FR‑024, FR‑033, FR‑045):

- Default sequential processing of items within a step to respect VRAM.
- For each item: generate seed at runtime just before generation starts if `seed` not provided; emit per-item events with `item_index`; write per-item artifact with indexed key.
- Aggregate progress = mean(per-item progress); final Job succeeds only if all items succeed (MVP behavior).

GPU hygiene (OR‑001):

- `try/finally` cleanup; delete references; `torch.cuda.empty_cache()`, `gc.collect()`.
- Subprocess termination on timeout (SIGTERM→SIGKILL); parent verifies memory reclaimed.
- Emit `gpu_mem_used_before/after` and `peak_gpu_mem_used` metrics/events.

Retries & DLQ:

- Bounded retries with backoff for transient errors; classify `oom` separately (no auto-degrade).

Optional container mode:

- Use NVIDIA Container Toolkit + CDI for device injection in containers; same runner protocol.

---

## 5) Runners Subsystem

Runner protocol (Python):

- `prepare(context)`: load model, allocate resources, set precision/scheduler.
- `run_step(params, emit)`: execute step logic; support batch iteration; call `emit(event)` for progress/log/artifact; return result summary.
- `cleanup(context)`: free resources; emit final GPU metrics.

Generate runner specifics:

- Framework: PyTorch with SDXL (EpicRealism‑XL).
- Device: CUDA; precision/scheduler configured by preset.
- Seeds: per-item runtime seed when missing; persist seed in artifact metadata and Artifact row.
- Metadata embedding: PNG tEXt/JPEG EXIF `UserComment` fields.

Instrumentation:

- NVML-based metrics; stage-weighted progress events; per-item `item_index` tagging.

Isolation modes:

- Default subprocess wrapper; container isolation (NVIDIA Toolkit + CDI) optional.

---

## 6) Model Registry Subsystem

Data model:

- Model: `id`, `name`, `kind`, `version`, `checkpoint_hash` (nullable), `source_uri`, `local_path` (nullable), `installed` (bool), `enabled` (bool), `parameters_schema` (JSON Schema), `capabilities`, timestamps.

Operations:

- `register(model_descriptor)`: create or upsert registry entry (used by CLI after download/verify).
- `get(model_id)`: fetch model descriptor for API/Worker.
- `list(enabled_only=True)`: list models for UI/API; can filter by capability.
- `verify(model_id)`: re-hash local files and update checksums/status.

API integration:

- `GET /v1/models` lists enabled models (id, name, kind, version, installed, enabled, parameters_schema).
- `GET /v1/models/{id}` returns full descriptor including `parameters_schema` for UI forms.
- `POST /v1/jobs` accepts `model_id` to select model (defaults to EpicRealism‑XL).

Startup validation:

- API/Worker load registry into cache; warn on missing local files for `installed=true` entries.

---

## 7) Unified Downloader (CLI)

Commands:

- `dreamforge model download <ref>`: download and verify; write descriptor; upsert registry.
- `dreamforge model verify <model_id|ref>`: re-verify checksums; update registry status.
- `dreamforge model list`: list registry entries with install state.

Adapter interface:

- `resolve(ref)` → concrete descriptor (URLs, revision/version IDs)
- `fetch(descriptor, dest)` → files on disk (resume, limited concurrency)
- `verify(files)` → checksums (e.g., SHA256) and sizes
- `to_model_descriptor(ref, meta, checksums)` → normalized payload for registry

Supported refs (MVP):

- `hf:<repo_id>[@<revision>][#<filename|pattern>]`
- `civitai:<model_or_version_id_or_slug>[@<version_id>]`

Layout & safety:

- Install under `<models_root>/<kind>/<name>@<version>/...`; write a descriptor JSON; no code execution; restrict file types.

Auth:

- Tokens via env/config for private HF or CivitAI; never stored in descriptors.

---

## 7.1 Background Download Job (Future)

Overview:

- Job type: `model_download` (admin-triggered). Payload includes `ref` (e.g., `hf:`/`civitai:`), optional target `kind/name/version`, and flags (verify-only, overwrite policy).
- Queueing: Dedicated Celery IO queue with bounded concurrency and rate limiting; separate from GPU job queue.
- Execution: Worker invokes the same unified downloader adapters; writes into normalized layout; verifies checksums; upserts Model registry entry.
- Idempotency: Request key is the normalized ref; repeated requests reconcile registry state and skip already verified files.
- Telemetry: Emits progress/log events with correlation ID; metrics for bytes downloaded and durations.
- Security: Requires admin credentials/tokens supplied via env/secrets; never logs secrets or presigned URLs.

API surface (one of):

- `POST /v1/jobs` with `{ "type": "model_download", "ref": "hf:repo@rev#file" }` (reuses Job API), or
- `POST /v1/models:download` (admin-only) that internally enqueues the job.

MVP posture:

- Disabled by default; CLI remains the primary path. Enable behind a feature flag in Beta if needed.

---

## 8) Persistence Layer

Entities:

- Job, Step, Event, Artifact, Model (FR‑080..081).

Repositories:

- CRUD for each entity; tailing queries for Events; Artifact listings with presign-ready keys.

Migrations & indices:

- Alembic migrations; indices on `status`, `updated_at`, `job_id`; Event time indexes for tails; Artifact `job_id,item_index`.

Transactions:

- Unit-of-work per API request or per Worker step; avoid long transactions; idempotency-key guarded creates.

Retention:

- Dev defaults minimal; production configurable; logs/events prunable by age.

---

## 9) Object Storage & Artifacts

Keying convention:

- `dreamforge/{user}/jobs/{job_id}/{step}/{ts}_{index}_{w}x{h}_{seed}.{ext}` (`user=default` in MVP).

Presigned URLs:

- Private buckets; presigned with TTL; surfaced via `GET /artifacts`.

Metadata embedding:

- Embed prompt, negative_prompt, seed, scheduler, steps, guidance, checkpoint hash in PNG tEXt / JPEG EXIF `UserComment`.

Content & checksums:

- Store content-type and optional checksums for clients; expose in Artifact metadata.

---

## 10) Observability & Telemetry

Logging:

- NDJSON logs with `job_id`, `step_id`, `event_id`, `item_index` (if batch), event `code`, message.

Metrics (Prometheus):

- Job counts by status; latencies; error rates; queue depth; GPU memory (`before/after/peak`); batch item counts/latencies.

Tracing:

- Optional OpenTelemetry hooks; conservative sampling.

Health:

- `/healthz` and `/readyz` for API and Worker; include DB/object store checks.

---

## 11) Configuration & Presets

Settings:

- Pydantic Settings with env; `.env` for dev; secrets via Docker/K8s in staging/prod.

Presets:

- Per GPU class: resolution, steps, scheduler, VRAM headroom target; referenced by name in job params.

Progress stage weights:

- Document defaults and apply consistently in progress aggregation.

---

## 12) Deployment & Packaging

Docker Compose:

- Services: `api`, `worker`, `redis`, `postgres`, `minio`; bind API to localhost; predictable 8xxx port.
- GPU access: Host NVIDIA drivers; container mode uses NVIDIA Container Toolkit + CDI; Compose `device_requests`/`--gpus`.

K3S (single-node, Beta):

- API/Worker manifests; Redis/Postgres/MinIO pods or managed; NVIDIA device plugin + CDI for GPUs.

Images:

- Multi-stage builds; pinned CUDA/PyTorch; minimize runtime layers; track image sizes.

---

## 13) Security & Safety

- Strict input validation; standardized error codes.
- No auto-downloads in API/Worker; unified downloader only (Doc 2 §3.12).
- Private buckets; presigned TTL; secrets via env/orchestrator.
- Limit downloaded file types; no code execution in downloader.

---

## 14) Extension Points

- Provider Adapter (future): interface to add remote providers behind the same job semantics.
- Runner plugins: additional job types via the Runner protocol; container isolation optional.
- Downloader adapters: add new sources without changing core logic.
- Storage backends: S3-compatible by default; adapters for GCS/Azure later.

---

## 15) Risks & Constraints (Focused)

- GPU variance and OOM risk → mitigate with presets, headroom checks, and cleanup guarantees.
- SSE polling overhead → acceptable for MVP; add cache/pubsub if necessary later.
- Registry drift → startup validation and `verify` command; clear status fields.
- Batch large counts → enforce limits (`≤100`); document performance trade‑offs.

---

## 16) Change Log & Links

- 2025‑09‑12: Initial draft covering components, responsibilities, and interfaces for MVP.

Related:

- Masters Doc 1: docs/masters/01-introduction-vision-goals.md
- Masters Doc 2: docs/masters/02-principles-of-system-design.md
- Masters Doc 3: docs/masters/03-requirements.md
- Masters Doc 4: docs/masters/04-architecture-overview.md
