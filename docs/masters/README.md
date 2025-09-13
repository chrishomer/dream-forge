# Dream Forge — Masters Series Index & Guide

Last updated: 2025-09-13

Status: Living document (kept current alongside the Masters series)

Owners: DX (primary), Product, Engineering

---

## Purpose

This README is the single entry point for the Dream Forge “Masters” documents. It explains what each document is for, how the set fits together, and where to find the relevant details when you’re building, reviewing, or planning.

The sequence and intent are informed by our design phases guide, but this index excludes the `design-phases.md` file itself from the table of contents.

---

## Reading Order (Thin-Slice Friendly)

Follow this order for first-time readers or when aligning a new change. It mirrors the progression from “why” → “what” → “how” → “deliver”.

1) Introduction, Vision, and Goals → foundations and scope
2) Principles of System Design → guardrails and non‑negotiables
3) Requirements → functional and non‑functional, prioritized
4) Architecture Overview → high‑level structure and flows
5) Systems (Components & Modules) → concrete responsibilities and interfaces
6) Data Model → entities, relationships, constraints, queries
7) Communication (Interfaces & Protocols) → REST, SSE, logs, internal tasks
8) Roadmap → thin functional slices, milestones, acceptance criteria
9) Project Structure Bootstrap (Epic 0) → repo layout, tooling, CI, Compose
10) OpenAPI, Makefile, and CLI → contract surface, developer workflow, CLI UX

Tip: When proposing a change, start by checking 2) Principles and 3) Requirements before opening 4–7. Use 8–10 to validate delivery posture and developer experience.

---

## Quick Links

- 01 — Introduction, Vision, and Goals → [01-introduction-vision-goals.md](./01-introduction-vision-goals.md)
- 02 — Principles of System Design → [02-principles-of-system-design.md](./02-principles-of-system-design.md)
- 03 — Requirements → [03-requirements.md](./03-requirements.md)
- 04 — Architecture Overview → [04-architecture-overview.md](./04-architecture-overview.md)
- 05 — Systems (Components & Modules) → [05-systems-components-modules.md](./05-systems-components-modules.md)
- 06 — Data Model → [06-data-model.md](./06-data-model.md)
- 07 — Communication (Interfaces & Protocols) → [07-communication-interfaces-protocols.md](./07-communication-interfaces-protocols.md)
- 08 — Roadmap (Milestones & Epics) → [08-roadmap.md](./08-roadmap.md)
- 09 — Project Structure Bootstrap (Epic 0) → [09-project-structure-bootstrap.md](./09-project-structure-bootstrap.md)
- 10 — OpenAPI, Makefile, and CLI → [10-openapi-makefile-cli.md](./10-openapi-makefile-cli.md)

Related materials:

- Ideation Vision → [../ideation/vision.md](../ideation/vision.md)
- Exported OpenAPI specs → [../openapi/](../openapi/)
- ADRs (when present) → `docs/adrs/`

---

## Document Summaries & What You’ll Find

### 01 — Introduction, Vision, and Goals

- Why this exists: Sets the north star; frames audience, mission (12‑month), and vision (3‑year).
- Highlights: Strategy pillars (simplicity, API‑first, extensible, observable, reproducible‑enough), target users, MVP→Beta→V1 goals and KPIs.
- Scope posture: In‑scope vs non‑goals for MVP; deployment posture (Compose first, K3S single‑node later).
- Success criteria: p50 time‑to‑first‑render, >95% success rate, artifact handling with metadata.
- Use when: You need a concise articulation of focus and trade‑offs to align scope.

### 02 — Principles of System Design

- Guardrails: Simplicity‑first, API‑first contracts, modular seams, observability by default, explicit configuration, compatibility/versioning, and extensibility without complexity.
- OR‑001 (GPU hygiene): Mandatory GPU memory cleanup on success/failure/timeout with metrics; OOM is a distinct error class.
- System‑wide policies: REST+JSON+SSE; Celery+Redis; Postgres as system of record; MinIO/S3 with private buckets and presigned URLs; subprocess isolation for runners.
- Baseline: Recommended tech choices and ops posture for a lean, maintainable implementation.
- Use when: Evaluating a design or dependency—does it respect our non‑negotiables?

### 03 — Requirements

- Functional (FR):
  - API surface under `/v1` (jobs create/status/artifacts/logs/progress + SSE) with idempotency.
  - Batch generation (`count` up to 100) with per‑item runtime seeds and indexed artifacts.
  - Job lifecycle (queued/running/succeeded/failed), events, retries with backoff, error taxonomy.
  - Artifact handling to S3‑compatible storage with embedded metadata by default.
  - Local SDXL runner (EpicRealism‑XL) with strict GPU hygiene (OR‑001).
- Non‑Functional (NFR):
  - Performance targets, reliability (bounded retries, DLQ), observability (NDJSON logs, Prometheus), deployability (Compose; K3S later), maintainability (typed, linted), versioning.
- Prioritization: Clear MoSCoW summary and MVP acceptance criteria.
- Use when: Scoping work or verifying completeness against acceptance criteria.

### 04 — Architecture Overview

- Components: API, Worker, Redis, Postgres, MinIO/S3; runner subprocess on GPU.
- Data flows: Job create → enqueue → run → artifacts/logs/progress; SSE fed by DB‑tailed aggregator.
- Responsibilities & contracts: Idempotency, error envelope, progress aggregation, artifact keying.
- Operations: Health/readiness, resiliency and failure modes, security posture for dev vs prod.
- Use when: You need the big‑picture blueprint and runtime sequence.

### 05 — Systems (Components & Modules)

- Concrete modules: API routers/services/adapters; Worker tasks/executor/runners/gpu monitor/artifacts/events; shared modules (persistence, storage, telemetry); unified downloader CLI.
- Runners: Protocol (`prepare/run_step/cleanup`), batch semantics, subprocess isolation, optional container isolation (NVIDIA Toolkit + CDI).
- Persistence & storage: Repos, migrations, indices; S3 keying and presigned URLs; metadata embedding.
- Extension points: Provider adapters, runner plugins, downloader adapters, storage backends.
- Use when: Implementing a module or reviewing ownership/abstractions.

### 06 — Data Model

- Entities: `jobs`, `steps`, `events`, `artifacts`, `models` (registry) with JSONB payloads where appropriate.
- Constraints & indices: Status checks, idempotency key partial unique index, `artifacts(job_id,step_id,item_index)` uniqueness, time‑ordered tails for events.
- Contracts: Example payload shapes (progress, artifact written, gpu.mem, errors), parameters schema for models.
- DDL & queries: Illustrative SQL for schema and common queries (artifact listing, event tails, model listing).
- Use when: Designing migrations, repositories, or debugging data concerns.

### 07 — Communication (Interfaces & Protocols)

- Public API: REST endpoints, path versioning (`/v1`), idempotency, error envelope.
- Streaming: SSE event types (progress, log, artifact, error), heartbeats, reconnect semantics.
- Logs: NDJSON format with correlation fields; pagination by `tail`/`since_ts`.
- Internal messaging: Celery queues and payloads (`jobs.generate`, future `models.download`), retry/backoff policies.
- Use when: Implementing endpoints/clients, or writing integration‑facing docs.

### 08 — Roadmap (Milestones & Epics)

- Delivery strategy: Thin, end‑to‑end functional slices tied to the App Creator persona.
- Milestones: M0 (Bootstrap) → M5 (GPU hygiene & resilience) → M6+ (staging/K3S, chaining, adapters, admin downloads, V1 hardening & DX).
- Quality gates: OpenAPI examples, SSE samples, simplicity guardrails, GPU hygiene checks.
- Use when: Planning scope/time, staging features behind flags, or negotiating trade‑offs.

### 09 — Project Structure Bootstrap (Epic 0)

- Tooling: Python 3.12, `uv` for packaging, FastAPI, SQLAlchemy/Alembic, Celery/Redis, boto3, ruff, mypy, pytest.
- Repository layout: `services/api`, `services/worker`, shared `modules/*`, `tools/dreamforge_cli`, `alembic/`, `compose/`, `docker/`, `docs/openapi/`.
- OpenAPI strategy: Code‑first generation and committed spec; CI diff to prevent drift.
- Compose: API/Worker/Redis/Postgres/MinIO; GPU access notes (NVIDIA Toolkit + CDI).
- DevEx: Make targets, `.env.example`, health/metrics endpoints, testing strategy, ADR & PR templates.
- Use when: Bootstrapping, adding dependencies, or wiring CI/Compose.

### 10 — OpenAPI, Makefile, and CLI (MVP Target)

- OpenAPI: Target YAML sketch covering `/jobs`, `/jobs/{id}/artifacts|logs|progress|progress/stream`, `/models`, `/models/{id}`; schemas for requests/responses.
- Makefile: Canonical developer tasks (`uv-sync`, `lint`, `fmt`, `type`, `test`, `openapi`, `up/down`, `logs`, `migrate-*`, `run-*`).
- CLI UX: `dreamforge` commands for jobs (optional wrapper) and unified downloader (MUST for MVP), with env vars like `DF_API_BASE`, `HF_TOKEN`, `CIVITAI_TOKEN`.
- Use when: Finalizing contracts, wiring dev workflow, or introducing the CLI.

---

## Cross‑Document Threads to Keep in Mind

- Reproducible‑enough outputs: Documented in Principles (02), required in Requirements (03), implemented across Runner/Artifacts (05), and reflected in metadata contracts (06, 07).
- GPU hygiene (OR‑001): Defined in Principles (02) with acceptance criteria, enforced in Requirements (03 NFR‑070), implemented in Systems (05) and validated in Roadmap milestones (08 M5).
- Batch semantics: API contracts (07), data model (`item_index` and keys in 06), and worker execution (05) must align.
- Versioning: Path‑based API versioning in Communication (07); `schema_version` fields in Data Model (06); tracked in OpenAPI (10).

---

## How to Propose Changes

- Start with Principles (02) and Requirements (03). If a change introduces a new service, external dependency, public endpoint, or schema addition, write an ADR in `docs/adrs/` and reference it from the affected Masters documents.
- Keep the OpenAPI spec current: when endpoints change, update the API app and regenerate `docs/openapi/openapi.v1.json` per 09/10.
- Update cross‑references: if a change affects batch semantics, progress, or artifact keying, touch 05, 06, and 07 together.
- Maintain simplicity: use the PR Simplicity Checklist (see 02 and 09) and budget constraints (endpoints, services, image sizes).

---

## Status & Ownership Conventions

- Each Masters document begins with `Last updated`, `Status`, and `Owners`. Keep these fields current.
- Preferred statuses: Draft → In Review → Accepted → Deprecated.
- Typical ownership: Product (scope/roadmap), Engineering (architecture/execution), DX (API contracts/devex).

---

## Changelog (for this Index)

- 2025-09-13 — Initial comprehensive index created; reading order aligned with design phases; includes cross‑document threads and contribution guidance.

