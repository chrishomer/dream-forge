# Dream Forge — Masters Document 2: Principles of System Design

Last updated: 2025-09-12

Status: Draft for review

Owners: Engineering (Architecture), Product (Scope), DX (API Contracts)

References: docs/masters/01-introduction-vision-goals.md, docs/ideation/vision.md

---

## 1) Purpose & Scope

This document codifies the principles that govern system design and delivery. It translates the vision into actionable guardrails, informs trade-offs, and anchors decisions across API, orchestration, storage, runners, and operations. It emphasizes a lean, maintainable foundation that is simple to operate and extend.

---

## 2) Non‑Negotiable Principles

1) Simplicity‑first: Prefer the smallest viable mechanism that is observable and testable. Avoid premature generalization.

2) API‑first contracts: Define and evolve the REST API via OpenAPI. Stable path versioning (`/v1`), predictable error envelopes, and idempotency for create operations.

3) Modularity with clear seams: Keep API, queue/orchestration, runners, persistence, and storage logically separate with explicit, typed interfaces.

4) Observability by default: Structured logs/events, minimal metrics, and progress as first‑class. Every job is traceable end‑to‑end via `job_id`.

5) Reproducible‑enough: Persist inputs/params/seeds and model/checkpoint hashes. Embed metadata in artifacts by default.

6) Explicitness over magic: Opt‑in features, clear configuration, fail‑loudly on misconfiguration instead of silent fallback.

7) Resource safety (GPU hygiene): All runners must clean up any GPU memory they allocate. Cleanup is mandatory on normal completion, failure, and timeout/kill paths.

8) Minimal security posture (dev) → pragmatic prod: No auth in dev; private buckets + presigned URLs. Simple API‑key auth for prod when introduced. Strict input validation.

9) Compatibility & versioning: Path‑based API versions; schema versions on persisted entities and presets/providers to enable safe evolution.

10) Extensibility, not complexity: Provide a narrow plugin/adapter surface (provider adapters, job‑type runners). Container isolation optional later; don’t require a heavy workflow UI.

---

## 3) System‑Wide Policies

### 3.1 API & Protocols

- REST + JSON, documented via OpenAPI. Path versioning `/v1`.
- Endpoints: jobs create/status/artifacts/logs/progress and SSE progress stream.
- Idempotency keys on job create; standardized error envelope with codes.

### 3.2 Orchestration

- Use Celery with Redis broker for task dispatch; Postgres for persistence of jobs/steps/events/artifacts (not a Celery result backend).
- Timeouts, bounded retries with exponential backoff, and DLQ for poisoned tasks.
- Idempotent handlers for create and enqueue; deduplicate by idempotency key.

### 3.3 Persistence

- Postgres as the system of record with a normalized schema (Job, Step, Event, Artifact) and Alembic migrations.
- Indices on `status`, `updated_at`, `job_id` for operational queries; background retention for logs/events if needed.

### 3.4 Artifacts & Storage

- MinIO/S3 with private buckets; presigned URLs for access.
- Embedded metadata on by default (prompt, negative_prompt, seed, scheduler, steps, guidance, checkpoint hash).
- Consistent S3 keying under `dreamforge/{user}/jobs/{job_id}/{step}/...` (user=`default` until auth).

### 3.5 Runners & GPU Resource Hygiene

- In‑process worker spawns an isolated subprocess per job step to protect the worker and simplify cleanup.
- Concurrency & VRAM guards: Don’t start work if headroom is below configured preset for the job type; fail‑loudly instead of auto‑degrading.
- Mandatory GPU cleanup on all paths:
  - Release tensors/models/contexts and free memory before reporting completion/failure.
  - Use `try/finally` to ensure cleanup is executed; on PyTorch, delete references, call `torch.cuda.empty_cache()` and `gc.collect()`; reset autocast/cache as applicable.
  - On timeout/kill, send a termination signal to the subprocess and, if needed, a forced kill after grace period. The parent must verify GPU memory is reclaimed before acknowledging terminal state.
- Emit metrics and structured events for GPU memory at start/end (`gpu_mem_used_before/after`, `peak_gpu_mem_used`).
- OOM handling: Classify OOM separately, include VRAM diagnostics, and fail with a clear error code. No automatic resolution change; surface recommendations.
 - Container GPU support: Build on CUDA‑pinned base images and enable GPU access via NVIDIA Container Toolkit with CDI (Container Device Interface) for device injection.
   - Docker/Compose: require NVIDIA Container Toolkit; use `--gpus` or Compose `device_requests`; prefer CDI where available to avoid runtime‑specific flags.
   - Kubernetes/K3S: install NVIDIA device plugin and enable CDI; request GPUs via standard resources and/or CDI annotations for specific device selection.
 - Isolation modes: Default to subprocess isolation; containerized runners optional via the same runner interface (NVIDIA Container Toolkit + CDI).

### 3.6 Configuration & Secrets

- 12‑factor via environment using Pydantic Settings. `.env` for dev; Docker/K8s secrets for prod.
- Explicit presets for GPU classes (e.g., VRAM limits, schedulers, step counts) referenced by name in requests.

### 3.7 Observability & Telemetry

- Structured NDJSON logs per job/step, correlated by `job_id` and `step_id`.
- Minimal Prometheus metrics: job counts by status, latencies, error rates, GPU memory stats, queue depth.
- Optional OpenTelemetry hooks; sample sparingly.

### 3.8 Errors & Resilience

- Error taxonomy with stable codes; include machine‑parsable details for client actionability.
- Bounded retries with backoff; circuit breaking not required initially.
- Idempotent create; DLQ for non‑retryable or poisoned messages.

### 3.9 Data Model & Versioning

- Persist `schema_version` for Jobs/Steps/Events/Artifacts; version presets and provider adapters.
- Migrations are additive and backward‑compatible across a minor line.

### 3.10 Deployment & Packaging

 - Docker Compose (dev/staging) with pinned CUDA/PyTorch base images; enable NVIDIA Container Toolkit and CDI for GPU access; single‑node K3S manifests for beta.
 - Bind to localhost in dev; no auth; predictable ports in the 8xxx range.
 - K3S/K8s GPU setup: install NVIDIA drivers, device plugin, and CDI; prefer CDI‑based device discovery/injection to ensure portability across runtimes.

### 3.11 Lean Engineering Guardrails

- Keep deployables to two core services in MVP: `api` and `worker`. Adding a new service requires an ADR with clear value, owner, rollback plan, and ops impact.
- Endpoint budget: MVP exposes only the endpoints listed in FR‑001. Any new endpoints wait for Beta and require ADR + docs updates.
- Schema budget: MVP persists only `Job`, `Step`, `Event`, and `Artifact`. Additional tables/columns need a migration review and ADR.
- Dependencies policy: Allowed infra is Postgres, Redis, MinIO (S3‑compatible). Any new external service or heavyweight library needs ADR with “remove plan”.
- Feature flags are ephemeral: include an expiry (≤ two releases) and a removal task when adding a flag.
- Container images: use multi‑stage builds, pinned CUDA/PyTorch bases; avoid unnecessary tools in runtime images. Track image sizes in CI for awareness.
- Simplicity review: Every ADR and PR must answer: “What did we choose not to build? How does this add complexity at runtime and in ops?”

### 3.12 Model Assets & Unified Downloader

- Explicit downloads only: the running API/worker never auto-downloads models. All model assets are fetched via a unified CLI/tooling workflow.
- Unified adapters: a single downloader interface with source adapters (Hugging Face, CivitAI at MVP) and a pluggable path for others. Adapters normalize metadata into the Model registry.
- Integrity & provenance: verify checksums; record source URIs, revisions/versions, and checkpoint hashes. Fail‑loudly on mismatch.
- Deterministic layout: store models under a normalized root with stable paths; write a descriptor file per model and upsert registry entries.
- Security posture: no code execution during download; limit file types to expected formats; support authenticated sources via env‑based tokens.
 
Evolution path:

- Background tasks are allowed in future phases when explicitly triggered (admin/API), not automatically. These run on a dedicated IO queue in the Worker, separate from GPU job queues, and use the same unified downloader library and registry contracts.

---

## 4) Options & Considerations (Summary)

- Orchestration: Celery+Redis (chosen) vs Dramatiq/RQ (simpler, fewer features) vs Temporal/Argo (heavy). Celery offers mature retries/ETA and broad community.
- Persistence: Postgres (chosen) vs Redis‑only (volatile) vs event sourcing (premature). Postgres balances durability and simplicity.
- API: REST+JSON (chosen) vs gRPC (binary, later) vs GraphQL (not aligned). SSE for progress; WebSocket optional later.
- Storage: MinIO/S3 (chosen) vs local FS (fragile) vs GCS/Azure (adapters later). Presigned URL ergonomics drive S3 choice.
 - Runners: Subprocess isolation (chosen) vs per‑job Docker (more isolation, higher cost) vs in‑proc (unsafe). Use NVIDIA Container Toolkit + CDI for container GPU support. GPU cleanup policy is mandatory across all modes.
- Config: Env‑first Pydantic (chosen) vs YAML overlays (drift) vs config service (overkill).
- Observability: JSON/NDJSON logs + Prometheus (chosen) vs full ELK/Clickhouse (later). OTEL hooks optional.
- Security: No auth in dev; API keys later; presigned TTL. Avoid marketplace scope.
- Testing: Unit + compose integration + seeded golden images; GPU tests gated; CPU mocks for unit level.

---

## 5) Recommended Baseline (Lean & Maintainable)

- Orchestration: Celery with Redis broker; Postgres system of record; idempotent create; bounded retries/timeouts; DLQ.
- API: FastAPI + OpenAPI; REST `/v1`; SSE stream for progress; standardized errors; idempotency keys.
- Storage: MinIO/S3 private buckets; presigned URLs; embedded artifact metadata; stable S3 keying convention.
 - Runners: Subprocess per step; strict VRAM headroom checks; mandatory GPU cleanup with metrics; OOM classified distinctly; container mode pluggable later via NVIDIA Container Toolkit + CDI.
- Config: Pydantic Settings with env; `.env` for dev; documented presets per GPU class.
- Observability: NDJSON logs per job; Prometheus metrics (including GPU memory); optional OTEL hooks.
- Resilience: Fail‑loudly on misconfig/insufficient VRAM; no auto‑degrade; clear operator guidance in errors.
- Versioning: Path‑based `/v1`; schema_version fields; versioned presets/providers; migration playbook.
- Deployment: Docker Compose (single‑node) as default; K3S manifests as Beta milestone; pinned CUDA/PyTorch images; NVIDIA toolkit + CDI enabled for GPU workloads.

### 5.1 Change Control & Simplicity Reviews

- ADRs required for: new services, new external dependencies, new public endpoints, and schema additions.
- PR template includes a Simplicity Checklist: scope fit to MVP, avoids premature generalization, uses existing abstractions, defines removal plan for flags.
- Monthly “bloat review”: scan endpoints, services, dependencies, and image sizes against budgets; create cleanup tasks as needed.

---

## 6) Operational Requirement OR‑001 — GPU Memory Cleanup

Requirement: All runners must clean up GPU memory they use.

Acceptance criteria:

- AC‑1: On success, runner emits an end‑of‑step event with `gpu_mem_used_after <= gpu_mem_used_before + epsilon` and `peak_gpu_mem_used` recorded.
- AC‑2: On failure or timeout, cleanup logic executes (verified by events/metrics) and the process exits without residual allocations (as measured by NVML or framework APIs) within a configurable grace period.
- AC‑3: OOM errors are surfaced with a distinct error code and include VRAM diagnostics (requested preset, observed peak usage, available VRAM at start).
- AC‑4: Integration tests exercise cleanup by forcing early termination and OOM, asserting memory is reclaimed.

Implementation guidance (PyTorch‑based runners):

- Use `try/finally` to guarantee teardown; delete large tensors/models; call `torch.cuda.empty_cache()` and `gc.collect()`; reset autocast/cache.
- Maintain a per‑step device context; avoid global state. Close any CUDA streams/handles created.
- Run steps in subprocesses; on timeout, send SIGTERM then SIGKILL after a grace window; parent verifies memory reclamation before acking terminal state.
- Emit start/finish events with GPU memory readings captured via NVML or framework equivalents.

---

## 7) Change Log & Links

- 2025‑09‑12: Initial draft; establishes core principles, baseline, and OR‑001 (GPU Memory Cleanup).

Related:

- Masters Document 1: docs/masters/01-introduction-vision-goals.md
- Ideation Vision: docs/ideation/vision.md
