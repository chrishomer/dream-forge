# Dream Forge — Masters Document 8: Roadmap (Milestones & Epics)

Last updated: 2025-09-12

Status: Draft for review

Owners: Product (Roadmap), Engineering (Delivery), DX (Docs)

References: docs/masters/design-phases.md, docs/masters/01..07

---

## 1) Purpose

Define an execution roadmap aligned with Vision, Principles, Requirements, Architecture, Systems, Data Model, and Interfaces. Emphasize thin, end-to-end functional slices that deliver user-visible value quickly while keeping the system lean and maintainable.

---

## 2) Structuring Options

- Thin functional slices (recommended): End-to-end increments that cut through API → worker → runner → artifacts → progress, each slice productionizes what it touches. Pros: fastest feedback, de-risks integration, keeps scope honest. Cons: requires discipline to avoid partial implementations.
- Layered platform-first: Infra and foundations first (queue, DB, storage), then API, then runners. Pros: tidy layers. Cons: delays user value, higher integration risk later.
- Capability waves: Thematic waves (e.g., Observability, Extensibility, Storage). Pros: focus on one concern. Cons: cross-cutting without user value, churn when integrating.
- Persona journey: Sequence slices by JTBD milestones for the primary persona. Pros: user-centric and similar to thin slices; can be combined with the recommended approach.

Recommendation: Thin functional slices anchored in the App Creator persona’s jobs-to-be-done, with explicit quality gates and simplicity guardrails (Doc 2 §3.11).

---

## 3) Milestones (Thin Functional Slices)

Note: Each milestone is definition-of-done (DoD) oriented with clear acceptance criteria (AC). MVP spans M0–M5; Beta spans M6–M9 (optional flags); V1 spans M10–M12.

M0 — Epic 0 Bootstrap (Foundation)

- Outcome: Repo scaffolding, Compose stack (api, worker, redis, postgres, minio), lint/type/test scaffolds, CI basics, PR template with simplicity checklist.
- AC: `docker compose up` starts infra + placeholder services; health endpoints respond; CI runs lint/tests.

M1 — E2E Generate v0 (Happy Path)

- Outcome: Single image generation via local GPU SDXL runner (EpicRealism‑XL), simple `POST /v1/jobs` → artifact in MinIO, `GET /v1/jobs/{id}` shows `succeeded`.
- AC: One request produces one image; artifact keying present; minimal logs; manual seed possible.

M2 — Artifacts, Logs, Progress (SSE)

- Outcome: First-class artifact listing with presigned URLs; NDJSON logs with tail/since; `/progress` + `/progress/stream` with basic stage weights.
- AC: `GET /artifacts` returns metadata + presigned URLs; SSE shows progress/log events during run.

M3 — Unified Downloader + Model Registry (Read APIs)

- Outcome: `dreamforge model` CLI (download/verify/list) with HF + CivitAI adapters; registry persisted; API exposes `GET /v1/models` and `GET /v1/models/{id}`; job accepts `model_id`.
- AC: Download model from HF and CivitAI; both appear in registry and API; jobs run against selected `model_id`.

M4 — Batch Generation (1–100) + Per-Item Seeds

- Outcome: `count` param (default 1, max 100); per-item runtime seed; per-item events (`item_index`), aggregated progress; artifact keying includes index.
- AC: `count=5` yields 5 artifacts with distinct seeds (when seed omitted); SSE shows per-item and aggregate progress.

M5 — GPU Hygiene & Resilience

- Outcome: OR‑001 enforced; VRAM headroom checks; OOM classification; standardized error envelope; idempotency keys; retries/backoff + DLQ.
- AC: Forced failure/timeout leaves GPU clean; OOM surfaces with diagnostics; duplicate create is idempotent.

M6 — Staging Deploy (K3S Single-Node + CDI)

- Outcome: K3S manifests for `api` and `worker`; NVIDIA device plugin + CDI; pinned CUDA/PyTorch images; staging environment.
- AC: End-to-end run on K3S; GPU access via CDI; secrets via K8s; basic runbooks.

M7 — Minimal Chaining (V2: generate → upscale)

- Outcome: Multi-step job with `generate` then `upscale`; steps/events persisted; aggregated progress across steps; artifacts per step.
- AC: API accepts a simple sequence; SSE shows step transitions and combined progress; outputs include both generate and upscale artifacts.

M8 — Provider Adapter (Optional)

- Outcome: Provider adapter interface and one remote adapter behind a feature flag; parity with local job semantics; artifacts/metadata consistent.
- AC: A small job runs via remote provider; API responses unchanged; presets clearly documented.

M9 — Background Downloader (Optional, Admin)

- Outcome: Admin-triggered `model_download` job on IO queue; uses unified downloader; upserts registry.
- AC: Admin endpoint enqueues download; task runs without affecting GPU queue; registry updated with checksums/provenance.

M10 — V1 Packaging & Access

- Outcome: API keys; improved reproducibility receipts (checkpoint hashes in artifacts); optional CLI conveniences; retention configuration.
- AC: API-key auth toggled on; receipts verified; docs updated for production posture.

M11 — Hardening & DX (Stabilization Pass)

- Outcome: Prometheus metrics, golden-seed tests, improved docs/examples; error taxonomy tightened; API and worker stability; image sizes tracked; lean guardrails enforced.
- AC: Time-to-first-render p50 documented; >95% success on default preset in dev; docs enable an external adopter to integrate.

M12 — Toward Full Vision

- Outcome: Additional job types (enhance), preset/version governance light, optional second remote provider, stronger receipts; evaluate quotas.
- AC: Demonstrate thin chained flows and extensibility without expanding the service count; maintain lean posture.

---

## 4) Quality Gates & Simplicity Guardrails

- Every milestone ships: OpenAPI examples, error codes, SSE event samples, and a short integration guide.
- Lean budgets honored: endpoints, services, schema additions require ADRs (Doc 2 §3.11).
- GPU hygiene verified in CI (mocked) and nightly on hardware; image sizes and dependencies reported.

---

## 5) Risks & Pivots

- SSE scaling stress → pivot to pub/sub cache; keep API surface stable.
- Model size/throughput pain → prioritize background downloader (M10) earlier.
- GPU OOM rates high → optimize presets and progress expectations; document supported GPU classes.

---

## 6) End State (Vision Alignment)

- API-first render fabric with small, stable surface; simple sequencing; strong artifacts/logs/progress; model registry with unified downloader; optional container isolation (CDI) and remote adapters; reproducible‑enough outputs with embedded metadata and receipts.
