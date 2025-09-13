# Dream Forge — Masters Document 1: Introduction, Vision, and Goals

Last updated: 2025-09-12

Status: Draft for review

Owners: Product (Vision), Eng (Feasibility), DX (API ergonomics)

References: docs/ideation/vision.md, docs/masters/design-phases.md

---

## 1) Purpose & Audience

This document sets the north star for Dream Forge and orients all subsequent design and delivery work. It defines the why (vision and mission), who (primary users), and what (objectives, scope, and non‑goals) at a level that product, engineering, and partner teams can align on. It is intentionally implementation‑light; architectural details and component breakdowns live in later Masters documents.

Audience: Product, Engineering, Early Adopters, and any contributor evaluating scope trade‑offs.

Key takeaways:

- Dream Forge is an API‑first, programmable render fabric for apps.
- MVP optimizes for successful, reproducible‑enough, single‑step image generation on local GPU with excellent artifact handling.
- V2 introduces minimal multi‑step chaining (generate → upscale); extensions and remote providers come via adapters.
- Delivery posture favors simplicity, observability, and single‑node deploys first.

---

## 2) Executive Summary

Dream Forge provides a clean HTTP API to create and track media generation jobs with great defaults, structured progress, and first‑class artifact handling to S3‑compatible storage (MinIO). Developers integrate via stable endpoints for job create, status, logs, progress (including SSE), and artifacts. The system is designed to be simple to embed yet open for extension via custom jobs/containers and provider adapters.

MVP centers on a local GPU runner using a SDXL checkpoint (EpicRealism‑XL), minimizing external dependencies and maximizing reliability for the primary audience: app creators and integrators. The platform captures inputs and parameters for reproducible‑enough outputs and exposes artifacts and logs with presigned URLs. V2 adds minimal sequencing (generate → upscale) without introducing a heavy workflow UI.

---

## 3) Vision (3‑Year)

Be the easiest programmable render fabric for applications: a small, reliable API surface, drop‑in jobs that run locally or via adapters, minimal recipe chaining, reproducible outputs, and optional governance. Teams can extend the system with custom jobs/containers without adopting a complex workflow tool or marketplace.

---

## 4) Mission (12‑Month)

Deliver and harden a Python‑based HTTP service with:

- Stable endpoints for job creation, status, artifacts, logs, and progress (including SSE stream).
- High success rate for single‑step generate jobs on local GPU, writing artifacts to MinIO with embedded metadata by default.
- Packaging for single‑node Docker Compose; bring‑your‑own keys for any remote providers introduced via adapters.
- Early adopters running Dream Forge in production or staging environments.

---

## 5) Strategy Pillars

- Simplicity first: Keep the surface area small with strong defaults.
- API‑first: Everything scriptable and automatable; OpenAPI documented.
- Extendable: Custom jobs/containers and provider adapters are first‑class.
- Observable: Structured logs/events, job lifecycle, artifacts, and progress.
- Reproducible‑enough: Capture inputs/params/seeds and checkpoint hashes.
- Separation of concerns: Modular API, queue, runners, and storage.

Note: Detailed design principles are expanded in Masters Document 2.

---

## 6) Target Users & Value Proposition

Primary persona: App Creator / Integrator (API‑first). They want a minimal, dependable HTTP API that produces high‑quality results with sensible defaults and gives them control when needed (custom jobs, seeds, parameters, runners). They do not want to adopt a heavy UI or manage brittle scripts for artifacts and logs.

What Dream Forge unlocks:

- A programmable render fabric that embeds cleanly into backends and automation.
- Reproducible‑enough outputs with embedded metadata for traceability.
- Streamed progress (SSE) and structured logs to build responsive UX.
- Strong artifact handling to S3‑compatible storage with clear pathing and presigned URLs.
- A path to scale breadth via adapters and custom containers without changing core API semantics.

Secondary personas (future): Small Studios, Enterprise Platforms, CLI‑first indie creators.

---

## 7) Goals & KPIs

MVP (0–3 months):

- Deliver HTTP API for job create/status/artifacts/logs/progress (+ SSE stream).
- Local GPU generate runner using SDXL EpicRealism‑XL with MinIO artifact writes.
- Job lifecycle (queued → running → succeeded/failed) and retry policy.
- Dev packaging via Docker Compose (API, worker, Redis, Postgres, MinIO).
- No auth in dev mode; bind to localhost by default.

Beta (3–6 months):

- V2 chaining: generate → upscale (simple sequence per job).
- K3S single‑node manifests for staging; GPU scheduling.
- Optional second provider via adapter, behind a feature flag.

V1 (6–12 months):

- Additional job types (e.g., enhance), quotas, optional CLI, stronger reproducibility receipts.

KPI candidates:

- Time‑to‑first‑render (p50/p95), job success rate, job latency.
- % jobs with artifacts in MinIO; API error rate.
- Early adopter satisfaction (qualitative) and weekly active jobs.

---

## 8) Scope & Non‑Goals (Initial)

In scope (MVP):

- Single‑step image generation with robust artifact/log handling.
- Embedded metadata by default (prompt, seed, scheduler, steps, guidance, checkpoint hash).
- Progress endpoints and SSE stream; basic retry policy.
- Single‑node Docker Compose deployment for local/staging.

Deferred / Not in scope (MVP):

- Heavy workflow UI or visual graph editor.
- Safety/cost controls beyond basics; marketplace features.
- Multi‑tenant auth and quotas (may introduce basic API key auth in V2/V1).
- Auto‑download of models (explicit downloader utility preferred for clarity and verification).

Rationale: Maintain focus on a minimal, reliable API and first‑class artifacts/progress. Avoid scope creep that would slow delivery or add complexity disproportionate to value at this stage.

---

## 9) Deployment Posture

- Development: Single‑node Docker Compose including API (FastAPI), queue (Celery), broker (Redis), DB (Postgres), and MinIO. Bind to localhost with dev defaults.
- Staging: K3S single‑node manifests with GPU scheduling for API and worker; externalized Postgres and MinIO as needed.
- Production: Not prescriptive yet; adapters and runners should remain modular to support local GPU or remote providers. Hardening priorities include observability, retries, idempotency, and artifact retention policies.

Operational tenets:

- Prefer explicit configuration and verification (e.g., model downloader utility) over implicit automation.
- Fail loudly and transparently with structured error events; avoid silent degradation.
- Default private storage buckets; presigned access for artifacts.

---

## 10) Risks & Assumptions

Key risks:

- Model/runtime variance across environments can impact reproducibility and perceived quality.
- GPU memory constraints and scheduler/preset choices can affect reliability and latency.
- Celery/DB complexity for small teams if defaults are not ergonomic.

Mitigations:

- Ship sane presets and document trade‑offs; capture sufficient metadata for reproducibility.
- Provide progress stage weights and SSE to set UX expectations; allow future overrides.
- Compose defaults and K3S manifests reduce ops burden; strong docs and examples.

Assumptions:

- Primary users prefer API control over UI; they will integrate artifacts/URLs into their own workflows.
- Local GPU runner with SDXL EpicRealism‑XL is sufficient for initial quality bar.
- Early adopters accept limited auth/governance in exchange for simplicity and speed.

---

## 11) Success Criteria & Milestones

- First render in < 15 minutes from fresh clone using Compose (p50).
- > 95% job success rate across default preset in dev/staging.
- Artifacts consistently available in MinIO with embedded metadata; presigned access verified.
- Basic generate → upscale chaining demonstrably stable by Beta.
- At least two external adopters integrate the API for real use cases by end of V1.

---

## 12) Change Log & Links

Decisions reference: see Decision Log in docs/ideation/vision.md for context (IDs D‑001 … D‑018).

Related docs:

- Ideation Vision: docs/ideation/vision.md
- Design Phases Guide: docs/masters/design-phases.md
- Next: Masters Document 2 — Principles of System Design

