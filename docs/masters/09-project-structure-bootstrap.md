# Dream Forge — Masters Document 9: Project Structure Bootstrap and Foundation (Epic 0)

Last updated: 2025-09-12

Status: Draft for review

Owners: Engineering (DevEx), Product (Scope), DX (Contracts)

References: docs/masters/design-phases.md, docs/masters/01..08

---

## 1) Purpose

Establish a lean, maintainable project foundation that accelerates delivery of thin slices while enforcing simplicity guardrails. This covers language/runtime, dependency tooling, project layout, local dev (Compose), OpenAPI contracts, migrations, testing, lint/type checks, CI basics, and operational defaults.

Preferences addressed: use `uv` for Python packaging and virtualenvs; adopt OpenAPI as the API contract surfaced from the service and checked into the repo.

---

## 2) Language, Runtime, and Dependencies

- Python: 3.12 (or latest 3.x LTS we can pin). Use `PYTHONUTF8=1` and `PYTHONDONTWRITEBYTECODE=1` in containers.
- Package & venv management: `uv` (fast, hermetic). Single `pyproject.toml` at repo root; `uv.lock` committed.
  - Dev flow: `uv sync` (create venv + install), `uv run ...` (run tools), `uv add fastapi ...` (add deps), `uv tree` (inspect dep graph).
  - Inside containers: install `uv` and use it for layer-cached, deterministic installs.
- Core libs (minimal set):
  - Web/API: FastAPI, Uvicorn.
  - Data: SQLAlchemy 2.x, Alembic, asyncpg/psycopg (choose one; `psycopg[binary]` for simplicity initially).
  - Validation: Pydantic v2.
  - Queue: Celery, redis-py.
  - Storage: boto3/minio SDK (choose one; start with boto3 S3 client configured for MinIO).
  - Telemetry: prometheus-client, structlog or stdlib logging with JSON formatter.
  - Testing: pytest, pytest-asyncio, freezegun (maybe), httpx (client), respx (HTTP mocking) if needed.
  - Types & lint: mypy, ruff (formatter + lints), types-* stubs as needed.

---

## 3) Repository Layout (MVP)

```
.
├─ services/
│  ├─ api/
│  │  ├─ app.py                 # FastAPI app factory
│  │  ├─ routes/                # /v1/jobs, /v1/models, /healthz, /readyz
│  │  ├─ schemas/               # Pydantic models (requests/responses)
│  │  ├─ services/              # job service, model read service, progress aggregator
│  │  ├─ adapters/              # db (repos), queue (celery), s3 (presign)
│  │  ├─ telemetry/             # logging + metrics
│  │  └─ config.py              # Pydantic Settings
│  └─ worker/
│     ├─ celery_app.py          # Celery config
│     ├─ tasks/                 # generate
│     ├─ exec/                  # subprocess supervisor (timeouts, signals)
│     ├─ runners/               # generate runner (SDXL), protocol
│     ├─ gpu/                   # NVML/framework metrics, headroom checks
│     ├─ artifacts/             # s3 writes, metadata embedding
│     ├─ events/                # writers, helpers
│     └─ presets/               # per-GPU presets
├─ modules/
│  ├─ registry/                 # model DAO, descriptors, parameters_schema
│  ├─ persistence/              # SQLAlchemy models, repositories (jobs, steps, events, artifacts, models)
│  ├─ storage/                  # s3 client utils
│  └─ telemetry/                # shared telemetry utils
├─ tools/
│  └─ dreamforge_cli/           # unified downloader CLI (download/verify/list)
├─ alembic/                     # migrations
├─ compose/                     # docker-compose.yml, envs, init scripts
├─ docker/                      # Dockerfiles (api, worker, base-cuda)
├─ docs/
│  ├─ openapi/                  # exported openapi.v1.json/yaml (generated)
│  └─ masters/                  # this series
├─ scripts/                     # dev helpers (bash/python), minimal
├─ pyproject.toml               # uv-managed project
├─ uv.lock                      # pinned lockfile (commit)
├─ .env.example                 # sample env
├─ Makefile                     # common tasks via uv
└─ .ruff.toml / mypy.ini        # tooling configs
```

Notes:

- Keep service count to `api` and `worker`. Downloader is a CLI in `tools/` not a service.
- Shared domain modules live under `modules/` and are imported by both services.

---

## 4) OpenAPI Strategy (Contract & Drift Control)

- Source of truth: typed FastAPI app generates OpenAPI (code-first) to stay lean.
- Exported spec: generate and commit `docs/openapi/openapi.v1.json` (and `.yaml`) via a small script calling `app.openapi()`.
- Lint & diff: run Spectral (optional) to lint; diff current vs committed file in CI so changes are explicit in PRs.
- Dev docs: serve Swagger UI/ReDoc in dev; disable/lock down in prod as needed.

Commands (examples):

- `uv run python scripts/export_openapi.py --out docs/openapi/openapi.v1.json`
- `uv run spectral lint docs/openapi/openapi.v1.yaml` (optional)

---

## 5) Docker, Compose, and GPU (Dev/Staging)

- Compose services: `api`, `worker`, `redis`, `postgres`, `minio`.
- Images: multi-stage Dockerfiles using `uv` to install deps; pin CUDA/PyTorch base for runner image; small Python base for API.
- GPU access: NVIDIA Container Toolkit + CDI for container GPU access; Compose uses `device_requests`/`--gpus` when enabled.
- Volumes: mount a `models/` volume for registry and runner access; mount `alembic/` and `scripts/` as needed.
- Ports: API on localhost (8xxx); MinIO console internal by default.

---

## 6) Configuration & Secrets

- Pydantic Settings; env-vars are the override mechanism. Provide `.env.example` and ignore `.env`.
- Secrets: in dev via `.env`; in K3S via Secrets. Never commit secrets.
- Required envs: DB URL, Redis URL, MinIO endpoint/key/secret/bucket, API bind host/port, GPU toggles, models root.

---

## 7) Database & Migrations

- SQLAlchemy 2.x models for Jobs, Steps, Events, Artifacts, Models per Doc 6.
- Alembic initialized with a baseline migration reflecting Doc 6 schema.
- Migration policy: additive forward-only within v1; destructive changes require a new major (`/v2`) or data migration plan.

---

## 8) Testing & Quality Gates

- Tests: `pytest` with markers for unit/integration. Integration uses Compose (Redis/Postgres/MinIO). GPU tests gated behind an env flag.
- Golden seeds: establish a set of seeded runs for drift detection (skipped in CI if no GPU).
- Lint/format: `ruff` (as formatter too) with a focused rule set; type-check with `mypy` in `--strict` where feasible.
- PR checklist includes Simplicity questions (Doc 2 §3.11), OpenAPI export updated, schema/migration changes reviewed.

Make targets (examples):

- `make uv-sync` → `uv sync`
- `make lint` → `uv run ruff check .`
- `make fmt` → `uv run ruff format .`
- `make type` → `uv run mypy`
- `make test` → `uv run pytest -q`
- `make openapi` → export and (optionally) lint OpenAPI
- `make up` / `make down` → Compose up/down

---

## 9) Observability & Health

- Logging: JSON logs (structured) with request IDs; NDJSON for job logs.
- Metrics: prometheus-client; `/metrics` on API and Worker (authz optional in dev).
- Health: `/healthz` and `/readyz` endpoints in API and a basic Celery health task; include DB/object-store checks.

---

## 10) Security & Posture

- Dev: No auth; bind to localhost; private buckets + presigned URLs.
- Prod-ready later: API keys, stricter CORS, secrets via orchestrator, retention policies.
- Inputs: strict validation; limit prompt lengths and sizes per preset.

---

## 11) ADRs, Templates, and Docs

- ADRs: `docs/adrs/` with a lightweight template (decision, context, alternatives, consequences). Required for new services, external deps, public endpoints, or schema changes.
- PR Template: includes Simplicity Checklist, OpenAPI/spec changes, migration notes.
- DEV.md: quickstart for `uv`, Compose, OpenAPI export, running tests, and common troubleshooting.

---

## 12) Initial Tickets (Epic 0)

- E0-1: Initialize `pyproject.toml` with `uv` and base deps; commit `uv.lock`.
- E0-2: Scaffold `services/api` + `services/worker` with health endpoints; wire logging/metrics.
- E0-3: Export OpenAPI (empty v1 skeleton) to `docs/openapi/openapi.v1.json`; CI diff check.
- E0-4: Add Alembic and create baseline migration per Doc 6.
- E0-5: Compose stack with Redis/Postgres/MinIO; `make up/down` targets.
- E0-6: Lint/type/test setup: ruff, mypy, pytest wired to `uv run`.
- E0-7: ADR and PR templates; `.env.example`; DEV.md quickstart.

---

## 13) Notes on Keeping It Lean

- Prefer `uv` for deterministic envs; avoid overlapping tools (no Poetry/Conda/Poetry+Pip mix).
- Code-first OpenAPI with generated artifact committed keeps us fast and safe from drift without a heavy contract toolchain.
- Two images only (api, worker); runner CUDA base is a FROM stage re-used as needed.
- Feature flags include expiry and removal tasks; avoid long-lived toggles.

