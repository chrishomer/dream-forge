# Milestone M0 — Epic 0 Bootstrap (Foundation)

Last updated: 2025-09-13

Status: Draft for review

Owners: Engineering (DevEx, Runtime), DX (Contracts/Docs), Product (Scope)

References:
- Masters 08 — Roadmap: docs/masters/08-roadmap.md
- Masters 09 — Project Structure Bootstrap: docs/masters/09-project-structure-bootstrap.md
- Masters 10 — OpenAPI, Makefile, and CLI: docs/masters/10-openapi-makefile-cli.md
- Masters 02 — Principles (guardrails, OR‑001 hygiene): docs/masters/02-principles-of-system-design.md
- Masters 06 — Data Model (names used for baseline Alembic): docs/masters/06-data-model.md
- Masters 07 — Communication (endpoint names, versions): docs/masters/07-communication-interfaces-protocols.md

---

## 1) Objective

Stand up a lean, maintainable foundation that enables thin, end‑to‑end slices starting in M1. At the end of M0, developers can clone the repo, boot the local stack with Docker Compose, hit placeholder health endpoints for `api` and `worker`, run `uv`‑managed lint/type/tests, export an OpenAPI v1 skeleton, and open a PR that passes the CI gates and the Simplicity Checklist.

---

## 2) Scope (In / Out)

In scope (M0):
- Repo scaffolding with `uv` packaging, lockfile, and baseline dependencies.
- Minimal `api` and `worker` services with `/healthz`, `/readyz`, `/metrics`.
- Docker/Compose stack: `api`, `worker`, `redis`, `postgres`, `minio` with sensible dev defaults.
- Alembic initialized with a baseline migration that reflects Masters 06 schema.
- OpenAPI v1 skeleton routes and export script; committed spec under `docs/openapi/`.
- Tooling: Makefile targets, ruff + mypy + pytest wiring, `.env.example`.
- CI basics: lint, type, test, OpenAPI spec diff.
- Governance: ADR template; PR template with Simplicity Checklist; DEV.md quickstart.

Out of scope (M0):
- Real model execution, GPU images, or runner logic (arrives M1+).
- Full endpoint implementations beyond health/metrics and empty scaffolds.
- Auth; production hardening beyond minimal dev posture.

---

## 3) Success Criteria (DoD for M0)

- `docker compose up` brings up `api`, `worker`, `redis`, `postgres`, `minio` and all containers report healthy.
- `curl http://localhost:<api_port>/healthz` returns 200; `/readyz` checks DB/object store reachability; `/metrics` scrapes.
- `uv sync` installs; `make lint type test` pass locally; CI runs the same and passes on PRs.
- `make openapi` regenerates `docs/openapi/openapi.v1.json` and CI enforces a spec diff.
- Baseline migration applies: `make migrate-head` against the dev DB succeeds.
- PR template and ADR template available and referenced by CONTRIBUTING/DEV docs.

---

## 4) Plan Structure

This milestone is broken into epics (E0‑A .. E0‑G). Each epic has stories/tasks, acceptance criteria, and dependencies. Complete all epics to finish M0.

---

## Epic E0‑A — Repository & Tooling Bootstrap

Goal
- Establish Python 3.12 project with `uv` for deterministic envs and a minimal, shared dependency set.

Deliverables
- `pyproject.toml` with core deps (FastAPI, Uvicorn, SQLAlchemy, Alembic, psycopg[binary], Celery, redis, boto3, prometheus-client, pydantic, ruff, mypy, pytest, httpx, pytest-asyncio).
- `uv.lock` committed.
- `.ruff.toml` and `mypy.ini` with focused rule sets (strict enough to catch issues; adjustable later).

Stories/Tasks
- Initialize `pyproject.toml` and add baseline dependencies via `uv add`.
- Create `.ruff.toml` (formatter + lints) and `mypy.ini` (targeting services + modules paths).
- Add `scripts/` folder for developer utilities.

Acceptance Criteria
- `uv sync` succeeds from a clean checkout.
- `uv run ruff check .` and `uv run mypy` run without errors on the scaffolded codebase.

Dependencies
- None (first epic).

---

## Epic E0‑B — Services Scaffolding (API + Worker)

Goal
- Scaffold `services/api` and `services/worker` with minimal runtime, health checks, metrics, and structured logging.

Deliverables
- API app factory at `services/api/app.py` exposing `/healthz`, `/readyz`, `/metrics`.
- Worker bootstrap at `services/worker/celery_app.py` and a health task (`celery inspect ping` equivalent or explicit task) plus `/metrics` endpoint (simple HTTP or Prometheus multiprocess).
- Shared logging utilities (JSON logs), common settings via Pydantic.

Stories/Tasks
- Implement API FastAPI app with routers folder and empty `/v1` placeholder router.
- Add health/readiness: readiness should validate DB and object store connectivity when env flags are set.
- Wire `prometheus-client` metrics and expose `/metrics` on API; for Worker, select approach: HTTP sidecar/simple aiohttp endpoint or Prometheus Celery exporter pattern (keep simple: small HTTP in-process).
- Set up minimal JSON logging with request IDs.

Acceptance Criteria
- API returns 200 on `/healthz`; readiness fails when DB is unavailable; `/metrics` returns Prometheus text.
- Worker responds to a health check (`celery` task runs and returns) and exposes `/metrics`.

Dependencies
- E0‑A (tooling) complete.

---

## Epic E0‑C — Persistence & Migrations (Alembic Baseline)

Goal
- Create SQLAlchemy models and Alembic baseline migration aligned with Masters 06.

Deliverables
- SQLAlchemy 2.x models for `Job`, `Step`, `Event`, `Artifact`, `Model` under `modules/persistence/`.
- Alembic project under `alembic/` with `env.py`, versions dir, and a baseline migration reflecting Masters 06 example DDL (adjusted for SQLAlchemy idioms).
- Make targets to run migrations.

Stories/Tasks
- Initialize Alembic; configure DB URL from env (Pydantic Settings in both services).
- Implement models and repositories skeletons with types; no business logic yet.
- Author baseline migration and verify `alembic upgrade head` against local Postgres.

Acceptance Criteria
- `make migrate-head` applies successfully; tables created match the intent of Masters 06 (jobs/steps/events/artifacts/models with key indexes & constraints).

Dependencies
- E0‑B (readiness checks can leverage DB once present).

---

## Epic E0‑D — Local Dev Environment (Docker/Compose)

Goal
- Provide a reproducible single-node environment for development with Compose.

Deliverables
- `compose/docker-compose.yml` with services: `api`, `worker`, `postgres`, `redis`, `minio`.
- Dockerfiles under `docker/` for `api` and `worker` (multi-stage; `uv` for installs). For M0, no CUDA base needed yet.
- Volumes for Postgres data and `models/` (future use), networks, sensible healthchecks.
- `.env.example` documenting required env vars (DB URL, Redis URL, MinIO config, API bind host/port, etc.).

Stories/Tasks
- Author Dockerfiles: slim Python base for API; worker image shares the same base (no GPU).
- Compose service definitions with `depends_on` and healthchecks; bind API to localhost dev port (8xxx as in Masters 09).
- Initialize MinIO bucket at startup (optional init container/script); or document manual init in DEV.md.
- Makefile targets: `up`, `down`, `logs`.

Acceptance Criteria
- `docker compose up -d` starts the stack; `docker compose ps` shows healthy containers.
- API reachable on `http://127.0.0.1:<port>/healthz`; worker health task runs.

Dependencies
- E0‑B (services) ready to containerize.

---

## Epic E0‑E — OpenAPI v1 Skeleton & Export Pipeline

Goal
- Establish contract-first workflow: generate and commit OpenAPI v1 from the API app; enforce spec diffs in CI.

Deliverables
- `scripts/export_openapi.py` that imports `services.api.app:app` and writes `docs/openapi/openapi.v1.json` (and optionally `.yaml`).
- Minimal placeholder `/v1` router and schemas sufficient to emit a v1 skeleton aligned with Masters 10.
- Make target `openapi` invoking the script.

Stories/Tasks
- Implement a thin `/v1` router module and schemas package (empty shapes acceptable for M0) so `app.openapi()` renders.
- Create export script with CLI args (`--out`), write JSON file deterministically (sorted keys/stable ordering).
- Commit initial spec artifact under `docs/openapi/`.

Acceptance Criteria
- `make openapi` produces identical output on repeated runs; file is committed and diffable.
- CI fails if the committed spec and generated spec differ.

Dependencies
- E0‑A (tooling), E0‑B (API app exists).

---

## Epic E0‑F — Quality Gates: Lint, Type, Test, CI

Goal
- Wire fast feedback loops locally and in CI to keep the codebase lean and correct from the start.

Deliverables
- Ruff and mypy configured and integrated with Makefile.
- Pytest scaffold with a couple of smoke tests (API health, OpenAPI export script).
- CI workflow (e.g., GitHub Actions) running on PRs: `uv sync`, `lint`, `type`, `test`, `openapi` + spec diff.

Stories/Tasks
- Add `tests/` with async httpx test hitting `/healthz` under a dev runner (can run against container or uvicorn in-process).
- Implement spec-diff step in CI: run export, `git diff --exit-code docs/openapi/openapi.v1.json`.
- Provide caching for `uv` in CI for speed (optional in M0).

Acceptance Criteria
- Local `make lint type test openapi` all pass.
- CI turns red on lint/type/test/spec drift; green when fixed.

Dependencies
- E0‑A, E0‑B, E0‑E.

---

## Epic E0‑G — Docs, Templates, Governance

Goal
- Establish contributor guidance and decision hygiene aligned with Masters 02 and 09.

Deliverables
- `DEV.md` quickstart: `uv sync`, Make targets, Compose up/down, migrations, OpenAPI export, common pitfalls.
- ADR template under `docs/adrs/000-template.md` with sections: Decision, Context, Options, Consequences, Links.
- PR template `.github/pull_request_template.md` including the Simplicity Checklist (Masters 02 §5.1) and prompts to update OpenAPI/spec and migrations.
- `CONTRIBUTING.md` that points to DEV.md, ADRs, coding standards, and CI gates.

Stories/Tasks
- Draft DEV.md based on Masters 09 §8 and §11.
- Add ADR template; link it from README/DEV and reference when adding services/deps/endpoints/schema.
- Create PR template with checklist items and a small “How tested” section.

Acceptance Criteria
- New contributors can follow DEV.md to get a healthy local run in < 15 minutes.
- PR template appears by default in new PRs; ADR template is discoverable and used for qualifying changes.

Dependencies
- E0‑A .. E0‑F provide content to reference.

---

## 5) Recommended Sequence & Estimates

Order of execution
- Week 1: E0‑A, E0‑B (scaffolds), E0‑D (Compose shells)
- Week 2: E0‑C (migrations), E0‑E (OpenAPI export), E0‑F (CI), E0‑G (docs/templates)

Rough effort (person‑days)
- E0‑A: 0.5
- E0‑B: 1.5
- E0‑C: 1.5
- E0‑D: 1.0
- E0‑E: 0.5
- E0‑F: 1.0
- E0‑G: 0.5
Total: ~6.5 person‑days (one engineer over ~1.5–2 weeks with context switching)

---

## 6) Risks & Mitigations

- Docker image drift or slow builds → use `uv` for deterministic installs; pin base images; keep images small (Masters 09).
- Flaky CI due to service startup timing → add healthchecks and retry/backoff in tests; gate integration tests behind an env flag if needed.
- Readiness semantics fragile in early days → allow a permissive flag to bypass object store checks until MinIO is initialized.
- Spec drift → enforce spec diff in CI and include OpenAPI updates in PR checklist.

---

## 7) Verification Checklist (Milestone)

- Local: `make uv-sync && make openapi && make lint && make type && make test` pass.
- Compose: `make up` → API `/healthz` 200; `/readyz` 200 after DB and MinIO reachable; `make migrate-head` applies.
- CI: Green on new PRs; red when spec drifts or gates fail.
- Docs: DEV.md accurate; PR and ADR templates present; `.env.example` complete.

---

## 8) Handover to M1

Prereqs created in M0 enable M1 “E2E Generate v0 (Happy Path)” to focus on:
- Adding initial `/v1/jobs` and `/v1/jobs/{id}` endpoints and schemas per Masters 10.
- Implementing a minimal worker task and runner stub (no GPU yet) to exercise the flow end‑to‑end.
- Surfacing artifacts/log lines as placeholders (MinIO write smoke).

---

## 9) Glossary (Selected)

- `uv`: fast Python package/venv manager used for deterministic developer environments.
- ADR: Architecture Decision Record; a short document capturing an important decision, context, alternatives, and consequences.
- Health vs Readiness: Health indicates the process is up; readiness asserts dependencies (DB/object store) are reachable.

---

## 10) Change Log

- 2025-09-13 — Initial detailed plan drafted from Masters 08–10 and aligned with Principles (02) and Data Model (06).

