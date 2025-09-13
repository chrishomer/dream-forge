# Dream Forge — Masters Document 3: Requirements

Last updated: 2025-09-12

Status: Draft for review

Owners: Product (Requirements), Engineering (Validation), DX (API Contracts)

References: docs/masters/01-introduction-vision-goals.md, docs/masters/02-principles-of-system-design.md, docs/ideation/vision.md

Note: Per design-phases, "Requirements" follows Personas/Use Cases. By request, this is the third masters doc.

---

## 1) Purpose & Scope

Define functional and non-functional requirements for the MVP → Beta trajectory of Dream Forge. Requirements are prioritized using MoSCoW (Must/Should/Could/Won’t for MVP), include acceptance criteria where possible, and trace to the vision and principles.

---

## 2) Functional Requirements (FR)

### API & Contracts

- FR-001 (MUST): Provide REST endpoints under `/v1` documented by OpenAPI.
  - POST `/v1/jobs` (create)
  - GET `/v1/jobs/{id}` (status)
  - GET `/v1/jobs/{id}/artifacts`
  - GET `/v1/jobs/{id}/logs`
  - GET `/v1/jobs/{id}/progress`
  - GET `/v1/jobs/{id}/progress/stream` (SSE)

- FR-002 (MUST): Job creation accepts `type="generate"`, `provider="local-sdxl-epicrealism"` (default), and parameters including `prompt` (required), `negative_prompt` (optional), `seed` (optional), image sizing, `steps`, `guidance`, `scheduler`, `format=png|jpg`, `embed_metadata=true|false`.

- FR-003 (MUST): Idempotency for job creation via `Idempotency-Key` header; duplicate requests within the key’s window return the original job.

- FR-004 (MUST): Standardized error envelope with `code`, `message`, `details`, and a correlation identifier tied to `job_id` when applicable.

- FR-005 (SHOULD): Serve OpenAPI JSON and human-readable docs; include example requests/responses.

- FR-006 (MUST): Public endpoints for MVP are limited to jobs (FR-001) and models listing (FR-088..089). Any other new endpoints require ADR and Beta milestone.

- FR-007 (MUST): Support batch generation via `count` parameter (default `1`, min `1`, max `100`) on `POST /v1/jobs`.

- FR-008 (MUST): Seed semantics for batches: if `seed` is omitted, each item in the batch must get a fresh random seed generated immediately before its generation begins (not precomputed in advance). If `seed` is provided and `count>1`, the MVP behavior is to ignore the provided `seed` and still randomize per item (a future `seed_strategy` may enable fixed/derived behavior).

### Job Lifecycle & Events

- FR-010 (MUST): Job states include `queued`, `running`, `succeeded`, `failed`; transitions are persisted with timestamps.

- FR-011 (MUST): Persist Steps and Events for each job (e.g., `step=generate`), including progress and artifact events.

- FR-012 (MUST): Retries with bounded attempts and exponential backoff for transient failures; record attempt count and last error.

- FR-013 (SHOULD): Distinguish error classes (e.g., `oom`, `invalid_input`, `provider_error`) in events and errors.

- FR-014 (MUST): Batch-aware events: include `item_index` (0-based) for per-item progress/log/artifact events within a batch; aggregate job progress reflects batch item completion weighted evenly across items.

### Artifacts & Storage

- FR-020 (MUST): Persist artifacts to S3-compatible storage (MinIO dev default) under keying: `dreamforge/{user}/jobs/{job_id}/{step}/{ts}_{w}x{h}_{seed}.{ext}` with `user=default` until auth exists.

- FR-021 (MUST): Return artifact metadata and presigned URLs from `GET /artifacts` with configurable TTL.

- FR-022 (MUST): Embed metadata by default into PNG tEXt / JPEG EXIF `UserComment`: prompt, negative_prompt, seed, scheduler, steps, guidance, checkpoint hash.

- FR-023 (SHOULD): Support selection of output format `png|jpg` per request (`png` default).

- FR-024 (MUST): Batch artifact keying: include `item_index` in object keys, e.g., `.../{step}/{ts}_{index}_{w}x{h}_{seed}.{ext}`; persist `item_index` on Artifact rows.

### Logs & Progress

- FR-030 (MUST): `GET /logs` returns structured NDJSON with event timestamps, codes, and message fields; supports `?tail=N` and `?since_ts=<ISO8601>`.

- FR-031 (MUST): `GET /progress` returns aggregated numeric progress with stage summaries; `GET /progress/stream` streams SSE events for progress/logs.

- FR-032 (SHOULD): Document default stage weights for progress computation per job type.

- FR-033 (MUST): Aggregated batch progress: job progress is computed as the mean of per-item progress; SSE includes per-item events with `item_index` and overall aggregate.

### Runners & Execution

- FR-040 (MUST): Provide a local GPU runner for SDXL using the EpicRealism‑XL checkpoint.

- FR-041 (MUST): Enforce GPU resource safety per OR‑001 (GPU memory cleanup on success, failure, and timeout; VRAM metrics emitted; OOM distinctly classified).

- FR-042 (MUST): Execute each step in a subprocess with configurable timeouts; parent process supervises and records terminal state.

- FR-043 (SHOULD): Presets define memory/quality parameters (e.g., resolution, steps, scheduler) per GPU class; job requests can reference presets by name.

- FR-044 (COULD): Optional containerized runner mode using NVIDIA Container Toolkit + CDI for device injection (keeping the same runner interface).

- FR-045 (MUST): Batch execution model: process batch items sequentially by default within the step to respect VRAM constraints; future parallelism may be added behind a configuration.

### Configuration & Packaging

- FR-050 (MUST): 12‑factor configuration via environment using Pydantic Settings; `.env` for dev.

- FR-051 (MUST): Provide Docker Compose for dev/staging (API, worker, Redis, Postgres, MinIO) with pinned CUDA/PyTorch images where GPU is required.

- FR-052 (SHOULD): Provide single-node K3S manifests for staging with GPU scheduling (NVIDIA device plugin + CDI).

- FR-053 (MUST): Supply a unified `dreamforge model download` utility with a pluggable source adapter interface to fetch and verify models from multiple sources (no implicit auto-download in the running service).
  - Supports at least `huggingface` and `civitai` sources at MVP.
  - Verifies file integrity (e.g., SHA256) and records provenance (source URI, revision, version IDs) in the registry.
  - Writes a local model descriptor file and registers/upserts into the Model registry on successful download.

- FR-054 (MUST): Keep deployables to two core services (API and worker) in MVP; Redis, Postgres, and MinIO are the only infra dependencies.

### Model Registry, Descriptors, and Unified Downloader

- FR-080 (MUST): Persist a Model registry in Postgres with fields: `id`, `name`, `kind` (e.g., `sdxl-checkpoint`, `remote-api`), `version`, `checkpoint_hash` (when applicable), `source_uri`, `local_path` (nullable), `installed` (bool), `enabled` (bool), `parameters_schema` (JSON Schema), `capabilities` (e.g., supported job types), `created_at`, `updated_at`.

- FR-081 (MUST): `POST /v1/jobs` accepts `model_id` referencing a registered model; default to the installed SDXL EpicRealism‑XL model if omitted.

- FR-088 (MUST): `GET /v1/models` lists registered models (enabled only by default) including `id`, `name`, `kind`, `version`, `installed`, `enabled`, and a `parameters_schema` (or `$ref` to it).

- FR-089 (MUST): `GET /v1/models/{id}` returns the full descriptor including `parameters_schema` for UI to build forms and validations.

- FR-090 (SHOULD): The `dreamforge model download` utility registers models in the registry upon successful download/verify; the service validates registry entries on startup.

- FR-091 (MUST): Unified downloader source adapters provide a common interface: `resolve(ref) → source-specific descriptor`, `fetch(descriptor) → files`, `verify(files) → checksums`, `to_model_descriptor(...) → registry payload`.

- FR-092 (MUST): Support model references:
  - `hf:<repo_id>[@<revision>][#<filename|pattern>]` (Hugging Face). Default revision = `main`; allow snapshot pinning.
  - `civitai:<model_or_version_id_or_slug>[@<version_id>]` (CivitAI). Resolve to a concrete download URL and metadata.

- FR-093 (MUST): Downloader is idempotent and resumable: skip already verified files; resume partial downloads; concurrency‑limited; human‑readable progress.

- FR-094 (MUST): Normalize installation layout under a configurable models root, e.g., `<root>/<kind>/<name>@<version>/...`, and store absolute `local_path` in the registry.

- FR-095 (SHOULD): Adapter plug‑in mechanism allows adding new sources without changing core downloader logic.

- FR-096 (MUST): `dreamforge model verify` command validates local files against recorded checksums and updates registry status.

- FR-097 (MUST): `dreamforge model list` shows registry entries with `installed/enabled` state and key metadata.

- FR-098 (SHOULD, Beta): Support an admin-triggered background download via API: either `POST /v1/jobs` with `type="model_download"` and `ref` or an admin endpoint (e.g., `POST /v1/models:download`). This enqueues a download task on a dedicated IO queue, uses the unified downloader library, and upserts the registry.

### Security & Access

- FR-060 (MUST): Private storage buckets by default; external access via presigned URLs.

- FR-061 (MUST): Strict input validation for job parameters; clear error messages for invalid inputs.

- FR-062 (SHOULD): API-key authentication available for non-dev deployments (dev remains unauthenticated, bound to localhost).

### Operations & DX

- FR-070 (MUST): Health/readiness endpoints and basic metrics endpoint (Prometheus exposition) for API and worker.

- FR-071 (SHOULD): Example scripts or snippets for common client integrations; curl examples in docs.

- FR-072 (COULD): Minimal CLI for local convenience; not required for MVP.

---

## 3) Non‑Functional Requirements (NFR)

### Performance & Capacity

- NFR-001 (MUST): Report time-to-first-render guidance; enable seeded “golden” runs to benchmark regressions. Target a consistent baseline on a supported GPU; publish reference metrics.

- NFR-002 (SHOULD): For default preset, maintain high success rate and reasonable latency; track p50/p95 job durations and queueing delay.
 
- NFR-003 (MUST): Batch limit of `count <= 100`; enforce server-side validation; document performance implications of large batches.

### Reliability & Resilience

- NFR-010 (MUST): Bounded retries with exponential backoff; DLQ for poisoned tasks; no infinite retry loops.

- NFR-011 (MUST): Idempotent job creation; safe to retry client submissions using the same Idempotency-Key.

- NFR-012 (SHOULD): Hard timeouts per step; cancellation on timeout with mandatory cleanup.
 
- NFR-013 (MUST): Batch failure semantics for MVP: if any item fails, the step and job fail; partial artifacts may exist for completed items and are retrievable.

### Observability

- NFR-020 (MUST): Structured logs (NDJSON) and progress events correlated by `job_id` and `step_id`.

- NFR-021 (MUST): Prometheus metrics for job counts by status, latencies, error rates, queue depth, and GPU memory usage statistics.

- NFR-022 (COULD): OpenTelemetry traces hooks with conservative sampling.
 
- NFR-023 (SHOULD): Emit per-item metrics (counts, latencies) and expose aggregated batch metrics.

### Security & Privacy

- NFR-030 (MUST): Private buckets; presigned URLs with TTL; minimal default retention in dev.

- NFR-031 (SHOULD): Secrets via environment or orchestrator secrets (Docker/K8s); no secrets committed to repo.

### Portability & Deployability

- NFR-040 (MUST): Reproducible dev environment via Docker Compose.

- NFR-041 (SHOULD): K3S single-node manifests for staging; GPU enablement via NVIDIA device plugin and CDI.

- NFR-042 (SHOULD): For containerized runners, use NVIDIA Container Toolkit + CDI to inject GPU devices in a runtime-agnostic way.

- NFR-043 (MUST): MVP deployables cap: two core services (API, worker). Compose services limited to API, worker, Redis, Postgres, MinIO.

### Maintainability & Extensibility

- NFR-050 (MUST): Narrow, typed interfaces for provider adapters and job-type runners; stable contracts.

- NFR-051 (SHOULD): Codebase typed and linted; tests cover core logic (unit) and integration (compose); seeded golden-image checks for drift.

- NFR-052 (MUST): Feature flags include an explicit expiry (≤ two releases) and a removal task; flags without owners are removed.

- NFR-053 (MUST): New external dependencies (services/libraries) require an ADR documenting value, ops cost, and a removal plan.

- NFR-054 (SHOULD): Runtime images use multi-stage builds; API image targets ≤ ~300MB; runner image based on pinned CUDA/PyTorch with minimal extras.

- NFR-055 (MUST): Core schema limited to `Job`, `Step`, `Event`, `Artifact` in MVP; schema expansions require ADR and migration plan.

- NFR-056 (SHOULD): Endpoint budget adhered to (FR-006); changes bundled with updated docs and examples.
 
- NFR-057 (MUST): Introduce `Model` table as part of MVP to enable registry (exception to schema budget justified by FR‑080..089).

### Downloader & Assets

- NFR-100 (MUST): Unified downloader is a CLI/tooling component, not a separate service; runs offline from the API/worker and integrates via the registry.

- NFR-101 (MUST): Integrity and provenance: record checksums, source identifiers (repo/version IDs), and checkpoint hashes; fail on mismatch.

- NFR-102 (SHOULD): Robustness: retry with backoff on transient network errors; support timeouts; configurable parallelism with sane defaults.

- NFR-103 (SHOULD): Safety: restrict downloaded file types to expected formats; no code execution during download; validate sizes against expectations if provided.

- NFR-104 (SHOULD): Compatibility: support authenticated sources via tokens in env/config; avoid embedding secrets in descriptors.
 
- NFR-105 (SHOULD): Background download jobs (when enabled) run on a dedicated Celery IO queue with bounded concurrency and rate limits; do not share a queue with GPU workloads.

### Reproducibility

- NFR-060 (MUST): Persist inputs/params/seeds and model/checkpoint hashes; embed artifact metadata by default.

### Resource Safety

- NFR-070 (MUST): OR‑001 — All runners clean up GPU memory they use (success, failure, timeout) and emit start/end/peak memory metrics. OOM classified distinctly.

### Versioning & Compatibility

- NFR-080 (MUST): Path-based API versioning (`/v1`); include `schema_version` fields on persisted entities; version presets and provider adapters.

### Data Retention

- NFR-090 (SHOULD): Dev defaults: MinIO bucket TTL ~24h; logs retained sufficiently for debugging; production retention configurable.

---

## 4) MoSCoW Prioritization Summary

 - MUST (MVP): FR-001..004,006..008,010..012,014,020..022,024,030..031,033,040..042,045,050..051,054,060..061,070,080..081,088..089; NFR-001,003,010..011,013,020..021,023,030,040,050,057,060,070,080

- SHOULD (Beta): FR-005,013,023,043,052..053,062,071; NFR-002,012,022,031,041,051,090

- COULD (V1+): FR-044,072; NFR-042

- WON’T (MVP): Marketplace, heavy workflow UI, multi-tenant auth/RBAC, advanced governance/cost controls.

---

## 5) Acceptance Criteria (MVP)

- AC-1: Create a generate job and retrieve status, logs, progress, and artifacts via documented `/v1` endpoints.
 - AC-2: Artifacts appear in MinIO with embedded metadata; `GET /artifacts` returns presigned URLs with TTL.
 - AC-3: NDJSON logs and SSE progress stream function during job execution; progress reflects stage weights and aggregated batch completion; per-item SSE events include `item_index`.
 - AC-4: Local SDXL runner produces images; GPU memory cleanup verified by metrics/events on success and simulated failure/timeout (OR‑001).
 - AC-5: Batch job with `count=5` completes with five artifacts, each carrying its own `seed` in metadata; seeds are generated per item at runtime when not provided.
 - AC-6: Retries and idempotent job creation verified; poisoned task moves to DLQ without infinite retries.
- AC-7: Docker Compose brings up API, worker, Redis, Postgres, MinIO; health/metrics endpoints respond.
- AC-8: `GET /v1/models` lists at least one installed model (EpicRealism‑XL) with parameters schema; `POST /v1/jobs` accepts `model_id` and runs with that model.
 - AC-9: Using the CLI, download a model from Hugging Face (`hf:` ref) and from CivitAI (`civitai:` ref); both register in the Model registry with checksums and provenance and appear in `GET /v1/models`.

---

## 6) Out of Scope (MVP)

- Multi-step chaining beyond generate → upscale (planned for Beta).
- Remote providers beyond local runner adapters (adapters can be added later).
- Advanced auth/quota/RBAC, marketplace features, and governance/compliance modules.

---

## 7) Assumptions & Dependencies

- Supported NVIDIA GPU with compatible drivers/CUDA for local runner; container mode uses NVIDIA Container Toolkit + CDI when enabled.
- MinIO available in dev via Compose; S3-compatible storage in staging/prod.
- Python environment for API/worker; Redis and Postgres reachable.

---

## 8) Change Log & Links

- 2025-09-12: Initial draft of requirements (MVP → Beta), aligned with Vision and Principles; codifies OR‑001 as NFR-070.

Related:

- Masters Doc 1: docs/masters/01-introduction-vision-goals.md
- Masters Doc 2: docs/masters/02-principles-of-system-design.md
- Ideation Vision: docs/ideation/vision.md
