# Dream Forge — Masters Document 4: Architecture Overview

Last updated: 2025-09-12

Status: Draft for review

Owners: Engineering (Architecture), Product (Scope), DX (API Contracts)

References: docs/masters/01-introduction-vision-goals.md, docs/masters/02-principles-of-system-design.md, docs/masters/03-requirements.md, docs/ideation/vision.md

---

## 1) Purpose

Provide a high-level view of Dream Forge’s system structure: core components, their responsibilities and contracts, runtime data flows, deployment topology, and scale/resilience considerations. This overview is the blueprint against which detailed component docs and implementation proceed.

Lean constraint: MVP ships with two core services — `api` and `worker` — plus infra dependencies (Redis, Postgres, MinIO). Any additional service needs an ADR.

---

## 2) High-Level Architecture

Components (MVP):

- API Service (FastAPI): Public HTTP endpoints (`/v1`) for jobs, artifacts, logs, progress, SSE streaming, and models listing. Aggregates progress from events. Maintains idempotent job creation.
- Worker Service (Celery): Consumes tasks from Redis; executes job steps via subprocess runners on GPU; persists steps/events/artifacts; enforces GPU cleanup (OR‑001).
- Redis (Broker): Celery task broker for enqueue/dispatch.
- Postgres (System of Record): Persists Jobs, Steps, Events, Artifacts, and Model registry metadata.
- Object Storage (MinIO dev / S3 compatible): Stores image artifacts; accessed via presigned URLs.

Text Diagram:

Client → API (`/v1/jobs`) → Postgres (Job) → enqueue → Redis → Worker → Runner (GPU)
Runner → Artifacts → MinIO  |  Runner → Events/Steps → Postgres
Client ← API (`/v1/jobs/{id}`/`/logs`/`/artifacts`/`/progress`) ← Postgres/MinIO
Client ← API SSE (`/progress/stream`) ← progress aggregator (DB-tailed)

---

## 3) Responsibilities & Contracts

API Service:

- Endpoints: `POST /v1/jobs`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/artifacts`, `GET /v1/jobs/{id}/logs`, `GET /v1/jobs/{id}/progress`, `GET /v1/jobs/{id}/progress/stream` (SSE), `GET /v1/models`, `GET /v1/models/{id}`.
- Idempotency: Accepts `Idempotency-Key` and deduplicates create requests.
- Progress aggregation: Computes numeric progress from Events with documented stage weights and batch aggregation; streams via SSE with per-item and aggregate updates.
- Error envelope: Standardized `code`, `message`, `details`, and correlation with `job_id` when applicable.

Worker Service:

- Task execution: One subprocess per step; supervises timeouts and exit status.
- Eventing: Emits structured Events (start, progress, artifact, error) and persists Steps/Events to Postgres.
- Artifact handling: Writes artifacts to MinIO/S3; records metadata and presigned-ready keys.
- GPU hygiene (OR‑001): Ensures cleanup on success/failure/timeout; emits `gpu_mem_used_before/after` and `peak_gpu_mem_used` metrics/events; distinct OOM classification.

Persistence:

- Postgres entities: Job, Step, Event, Artifact (normalized, FK-linked).
- Access patterns: API status/progress reads; Worker append-only Step/Event writes; Artifact metadata reads.

Storage:

- Keying convention: `dreamforge/{user}/jobs/{job_id}/{step}/{ts}_{index}_{w}x{h}_{seed}.{ext}` (`user=default` in MVP), where `index` is the 0-based batch item index.
- Metadata embedding: PNG tEXt / JPEG EXIF `UserComment` with prompt, negative_prompt, seed, scheduler, steps, guidance, checkpoint hash.

---

## 4) Data Model (Summary)

- Job: `id`, `type`, `status`, `created_at`, `updated_at`, `params_json` (includes `count`, optional `model_id`), `schema_version`, `idempotency_key_hash`.
- Step: `id`, `job_id`, `name` (e.g., `generate`), `status`, `started_at`, `finished_at`, `metadata_json`.
- Event: `id`, `job_id`, `step_id`, `ts`, `code`, `level`, `payload_json` (includes `item_index` for batch items, progress %, messages, GPU metrics).
- Artifact: `id`, `job_id`, `step_id`, `created_at`, `format`, `width`, `height`, `seed`, `item_index`, `s3_key`, `checksum`, `metadata_json`.
- Model: `id`, `name`, `kind`, `version`, `checkpoint_hash` (nullable), `source_uri`, `local_path` (nullable), `installed`, `enabled`, `parameters_schema` (JSON), `capabilities`, timestamps.

Indices: status, updated_at, job_id; event time-based partitioning optional later.

---

## 5) Runtime Flows

Job Create (Generate):

1. Client calls `POST /v1/jobs` with `type=generate`, params, optional `model_id`, and optional `count` (default 1, max 100); includes `Idempotency-Key` (recommended).
2. API validates, creates Job (status `queued`) and initial Step, stores `idempotency_key_hash`, enqueues Celery task to Redis.
3. API returns Job descriptor.

Execution:

4. Worker pulls task; records Step `running`; emits `start` Event with GPU memory snapshot.
5. Runner subprocess loads selected `model_id` (or default) and preset. For each item in the batch (sequentially by default):
   - Generate a random seed immediately before the item begins if no explicit seed is provided (not precomputed in advance).
   - Perform generation; emit per-item `progress`/`log` Events with `item_index` and stage-weighted progress.
   - Write artifact to MinIO; emit `artifact` Event and create Artifact row with `item_index`; embed per-item seed in the file.
6. On success, runner ensures GPU cleanup; emits final memory metrics; Step `succeeded`, Job `succeeded`.

SSE Progress:

8. Client subscribes to `GET /v1/jobs/{id}/progress/stream`.
9. API streams per-item Events and aggregated progress (mean over items) by polling new Events for `job_id` (DB-tailed, lightweight delta queries) and formatting as SSE. No extra infra beyond Postgres for MVP.

Failure & Retry:

10. On transient errors, Worker retries with exponential backoff, capped attempts; Events record attempt and last error.
11. On hard failure (including OOM), Step and Job mark `failed`; API surfaces error code and diagnostics. DLQ receives poisoned tasks.
12. Regardless of outcome, GPU cleanup executes (try/finally and timeout kill path) per OR‑001.

---

## 6) Technology Choices

- API: FastAPI (Python), Pydantic models, OpenAPI generation, Uvicorn server.
- Orchestration: Celery with Redis broker; Postgres as system of record (not Celery result backend).
- Persistence: Postgres with Alembic migrations.
- Storage: MinIO (dev)/S3; presigned URL access; private buckets by default.
- Runners: PyTorch-based SDXL (EpicRealism‑XL) runner, subprocess per step; presets for VRAM/quality.
- GPU in containers (optional mode): NVIDIA Container Toolkit with CDI (Container Device Interface) for device injection in Docker/Compose and K8s/K3S.
- Downloader: `dreamforge model` CLI with unified source adapters (Hugging Face, CivitAI) and a pluggable interface for future sources.

Optional background download flow (future):

- Expose an admin-triggered endpoint that enqueues a `model_download` task to a dedicated Celery IO queue. The Worker executes the same downloader library (no GPU), writes files to the models root, verifies checksums, and upserts the Model registry. This keeps two services while allowing background execution.

---

## 7) Deployment View

Docker Compose (MVP/Dev):

- Services: `api`, `worker`, `redis`, `postgres`, `minio`.
- GPU access: host setup with NVIDIA drivers; container mode (if enabled) uses NVIDIA Container Toolkit + CDI; Compose uses `device_requests`/`--gpus`.
- Networking: Bind API to localhost; predictable 8xxx port.

K3S Single‑Node (Beta):

- Manifests for API and Worker; Redis/Postgres/MinIO as pods or managed externally.
- GPU: NVIDIA device plugin + CDI installed; requests for GPUs via standard resources/CDI annotations.
- Secrets: K8s Secrets; Config via env.

Image policy: Multi-stage builds; pinned CUDA/PyTorch; minimal runtime layers.

---

## 8) Scalability & Performance

- Horizontal scale: Multiple `worker` replicas; concurrency tuned to VRAM presets; single `api` replica is fine initially; add replicas with sticky SSE by job if needed.
- Queue tuning: Celery prefetch limits and acks-late; bounded retries; DLQ for poisoned tasks.
- Progress computation: O(Δevents) per tick per SSE client; configurable poll interval; backoff under load.
- Artifact throughput: S3 uploads sized to artifact count; enable streaming uploads if needed later.
- GPU utilization: Track `gpu_mem_used_before/after` and `peak_gpu_mem_used`; use presets and headroom checks to reduce OOMs.

---

## 9) Observability & Operations

- Logs: Structured NDJSON per job/step; include `job_id`, `step_id`, `event_id`, codes.
- Metrics (Prometheus): job counts by status, latencies, error rates, queue depth, GPU memory metrics.
- Health/Readiness: `/healthz` and `/readyz` for API and Worker; DB/object-store checks.
- Tracing: Optional OpenTelemetry hooks with conservative sampling.

---

## 10) Security & Compliance (MVP posture)

- Dev: No auth; bind API to localhost; private buckets with presigned URLs (TTL).
- Prod-ready (Beta/V1): API keys; stricter CORS; secrets via orchestrator; artifact retention policy configurable.
- Input validation: Strict parameter validation; reject unsafe inputs.

---

## 11) Failure Modes & Recovery

- Redis outage: API still accepts jobs (optional), or returns 503 depending on configuration; retries on enqueue; alerts.
- Postgres outage: API returns 503; no stateful operations; fail fast.
- MinIO outage: Worker retries artifact writes; on final failure, Job fails with clear diagnostics.
- GPU OOM: Job fails with `oom` code; cleanup enforced; suggestions surfaced.
- Stuck runners: Timeout → SIGTERM → SIGKILL; parent verifies memory reclamation; Step/Job terminal state recorded.

---

## 12) Interfaces (Summary)

- Public API: `/v1` endpoints per FR‑001 and FR‑088..089; standardized errors; OpenAPI published.
- Internal queue contract: Task payload includes `job_id`, `step`, `params`, `preset`, and correlation info; results/events written to DB.
- Runner protocol (Python): Minimal interface to implement `prepare()`, `run_step()`, `emit_event()`, `cleanup()`; subprocess wrapper enforces timeouts and cleanup.

Model descriptor (JSON):

- Fields: `id`, `name`, `kind`, `version`, `installed`, `enabled`, `checkpoint_hash` (nullable), `capabilities` (supported job types), `parameters_schema` (JSON Schema for request parameters), `metadata`.
- The `parameters_schema` describes required/optional parameters, value ranges, enums (e.g., schedulers), and defaults that UIs can render.

Downloader adapter interface (conceptual):

- `resolve(ref)` → source descriptor (e.g., concrete URLs, revision IDs)
- `fetch(descriptor, dest)` → downloaded files (supports resume, concurrency)
- `verify(files)` → checksums (SHA256) and size validation
- `to_model_descriptor(ref, meta, checksums)` → normalized Model registry payload

Downloader flow:

1) User runs `dreamforge model download <ref>` where `<ref>` is `hf:` or `civitai:`.
2) Adapter resolves and fetches files to `<models_root>/<kind>/<name>@<version>/...` with progress and resume.
3) Files are verified; a descriptor JSON is written; the Model registry is upserted (`installed=true`).
4) API/Worker read registry on startup; `model_id` in job params selects the model.

---

## 13) Versioning & Evolution

- API versioning: Path‑based (`/v1`).
- Schema versioning: `schema_version` fields on Job/Step/Event/Artifact.
- Presets/providers: Versioned for compatibility; runner contract is additive and backwards-compatible.

---

## 14) Out of Scope (MVP)

- Heavy workflow UI/graph editors; marketplaces; advanced governance/quotas/RBAC; multi-tenant auth.
- Event streaming infra beyond DB-tailed SSE (e.g., Kafka) — revisit if needed.

---

## 15) Open Questions

- SSE scaling thresholds: When to introduce Redis pub/sub or a lightweight event cache to reduce DB polling under many concurrent clients?
- Checkpoint management: How to distribute/check/verify large model files across nodes; scope of `dreamforge model download`.

---

## 16) Change Log & Links

- 2025‑09‑12: Initial draft aligned to Vision, Principles, and Requirements; includes CDI guidance for GPU containers. Updated with batch generation, model registry overview, and unified downloader.

Related:

- Masters Doc 1: docs/masters/01-introduction-vision-goals.md
- Masters Doc 2: docs/masters/02-principles-of-system-design.md
- Masters Doc 3: docs/masters/03-requirements.md
- Ideation Vision: docs/ideation/vision.md
