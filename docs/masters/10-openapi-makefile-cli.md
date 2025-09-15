# Dream Forge — Masters Document 10: OpenAPI, Makefile, and CLI (MVP Target)

Last updated: 2025-09-12

Status: Draft for review

Owners: DX (Contracts), Engineering (DevEx), Product (Scope)

References: docs/masters/01..09

---

## 1) Purpose

Define the target OpenAPI v1 surface, Makefile developer workflow, and CLI UX for MVP (through Milestone M5) so implementation can proceed contract-first and stay lean.

---

## 2) OpenAPI v1 (Target Spec — YAML Sketch)

Notes:

- Path versioning `/v1`. Dev has no auth; production adds API keys later.
- Logs return NDJSON; SSE is `text/event-stream` with documented event shapes.
- Batch behavior: `count` (1–100, default 1); per-item events include `item_index`.

```yaml
openapi: 3.0.3
info:
  title: Dream Forge API
  version: 1.0.0
  description: API-first media generation service (MVP surface)
servers:
  - url: http://localhost:8001/v1
    description: Dev (Compose) — port configurable
paths:
  /jobs:
    post:
      summary: Create a job (generate)
      operationId: createJob
      parameters:
        - in: header
          name: Idempotency-Key
          required: false
          schema: { type: string }
          description: Ensures idempotent job creation
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/JobCreateRequest'
      responses:
        '202':
          description: Job accepted
          headers:
            X-Request-Id:
              schema: { type: string }
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobCreatedResponse'
        '409': { description: Idempotency conflict, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }
        '422': { description: Validation error, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }
        '503': { description: Infra unavailable, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /jobs/{id}:
    get:
      summary: Get job status
      operationId: getJob
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        '200':
          description: Job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobStatusResponse'
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /jobs/{id}/artifacts:
    get:
      summary: List artifacts for a job
      operationId: listArtifacts
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        '200':
          description: Artifacts
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ArtifactListResponse'
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /jobs/{id}/logs:
    get:
      summary: Stream job logs as NDJSON (polling)
      operationId: getLogs
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
        - in: query
          name: tail
          required: false
          schema: { type: integer, minimum: 1, maximum: 10000 }
          description: Return last N lines
        - in: query
          name: since_ts
          required: false
          schema: { type: string, format: date-time }
          description: Return logs since timestamp
      responses:
        '200':
          description: NDJSON stream (one JSON object per line)
          content:
            application/x-ndjson:
              schema: { type: string, description: NDJSON lines of LogEvent }
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /jobs/{id}/progress:
    get:
      summary: Get aggregated progress for a job
      operationId: getProgress
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        '200':
          description: Progress
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ProgressResponse'
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /jobs/{id}/progress/stream:
    get:
      summary: Server-Sent Events stream of progress and logs
      operationId: streamProgress
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        '200':
          description: SSE stream
          content:
            text/event-stream:
              schema: { type: string, description: SSE events: progress, log, artifact, error }
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

  /models:
    get:
      summary: List enabled models
      operationId: listModels
      parameters:
        - in: query
          name: enabled
          required: false
          schema: { type: boolean, default: true }
      responses:
        '200':
          description: Models
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModelListResponse'

  /models/{id}:
    get:
      summary: Get model descriptor
      operationId: getModel
      parameters:
        - in: path
          name: id
          required: true
          schema: { type: string, format: uuid }
      responses:
        '200':
          description: Model descriptor
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ModelDescriptor'
        '404': { description: Not found, content: { application/json: { schema: { $ref: '#/components/schemas/ErrorResponse' } } } }

components:
  schemas:
    ErrorResponse:
      type: object
      required: [code, message]
      properties:
        code: { type: string }
        message: { type: string }
        details: { type: object, additionalProperties: true }
        correlation_id: { type: string }

    JobCreateRequest:
      type: object
      required: [type, prompt, width, height]
      properties:
        type:
          type: string
          enum: [generate]
        provider:
          type: string
          default: local-sdxl-epicrealism
        prompt: { type: string, minLength: 1, maxLength: 4096 }
        negative_prompt: { type: string }
        width: { type: integer, minimum: 64, maximum: 4096 }
        height: { type: integer, minimum: 64, maximum: 4096 }
        steps: { type: integer, minimum: 1, maximum: 200, default: 30 }
        guidance: { type: number, minimum: 0, maximum: 50, default: 7.0 }
        scheduler: { type: string, enum: [dpmpp_2m_karras, unipc], default: dpmpp_2m_karras }
        format: { type: string, enum: [png, jpg], default: png }
        embed_metadata: { type: boolean, default: true }
        seed: { type: integer, minimum: 0 }
        count: { type: integer, minimum: 1, maximum: 100, default: 1 }
        model_id: { type: string, format: uuid }
      description: |
        If `seed` is omitted and `count>1`, a fresh random seed is generated for each item right before its generation begins.
        If `seed` is provided and `count>1`, MVP behavior randomizes per item (future seed_strategy may change this).

    JobCreatedResponse:
      type: object
      required: [job]
      properties:
        job:
          type: object
          required: [id, status, type, created_at]
          properties:
            id: { type: string, format: uuid }
            status: { type: string, enum: [queued, running, succeeded, failed] }
            type: { type: string, enum: [generate] }
            created_at: { type: string, format: date-time }

    JobStatusResponse:
      type: object
      required: [id, type, status, created_at, updated_at]
      properties:
        id: { type: string, format: uuid }
        type: { type: string }
        status: { type: string, enum: [queued, running, succeeded, failed] }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }
        steps:
          type: array
          items:
            type: object
            properties:
              name: { type: string }
              status: { type: string }
        summary:
          type: object
          properties:
            count: { type: integer }
            completed: { type: integer }

    Artifact:
      type: object
      required: [id, format, width, height, item_index, s3_key]
      properties:
        id: { type: string, format: uuid }
        format: { type: string, enum: [png, jpg] }
        width: { type: integer }
        height: { type: integer }
        seed: { type: integer }
        item_index: { type: integer }
        s3_key: { type: string }
        url: { type: string, format: uri }
        expires_at: { type: string, format: date-time }

    ArtifactListResponse:
      type: object
      required: [artifacts]
      properties:
        artifacts:
          type: array
          items: { $ref: '#/components/schemas/Artifact' }

    ProgressItem:
      type: object
      required: [item_index, progress]
      properties:
        item_index: { type: integer }
        progress: { type: number, minimum: 0, maximum: 1 }

    ProgressResponse:
      type: object
      required: [progress]
      properties:
        progress: { type: number, minimum: 0, maximum: 1 }
        items:
          type: array
          items: { $ref: '#/components/schemas/ProgressItem' }
        stages:
          type: array
          items:
            type: object
            properties:
              name: { type: string }
              weight: { type: number }

    ModelSummary:
      type: object
      required: [id, name, kind, installed, enabled]
      properties:
        id: { type: string, format: uuid }
        name: { type: string }
        kind: { type: string, enum: [sdxl-checkpoint, remote-api] }
        version: { type: string }
        installed: { type: boolean }
        enabled: { type: boolean }
        parameters_schema: { type: object, additionalProperties: true }

    ModelDescriptor:
      allOf:
        - $ref: '#/components/schemas/ModelSummary'
        - type: object
          properties:
            capabilities: { type: array, items: { type: string } }

    ModelListResponse:
      type: object
      required: [models]
      properties:
        models:
          type: array
          items: { $ref: '#/components/schemas/ModelSummary' }
```

---

## 3) Makefile (Target)

Assumes `uv` is available and `pyproject.toml` defines optional dev extras as needed.

```
.PHONY: uv-sync lint fmt type test openapi up down logs migrate-head migrate-rev run-api run-worker

uv-sync:
	uv sync

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

type:
	uv run mypy

test:
	uv run pytest -q

openapi:
	uv run python scripts/export_openapi.py --out docs/openapi/openapi.v1.json

up:
	docker compose -f compose/docker-compose.yml up -d

down:
	docker compose -f compose/docker-compose.yml down -v

logs:
	docker compose -f compose/docker-compose.yml logs -f --tail=200 api worker

migrate-head:
	uv run alembic upgrade head

migrate-rev:
	uv run alembic revision --autogenerate -m "$$m"

run-api:
	uv run uvicorn services.api.app:app --host 127.0.0.1 --port 8001 --reload

run-worker:
	uv run celery -A services.worker.celery_app.app worker -Q gpu.default -l info
```

---

## 4) CLI UX (Target)

Binary: `dreamforge` (Python Typer/Click). Default API base `DF_API_BASE` or `http://localhost:8001/v1`.

Jobs (wrapper around API — optional, nice-to-have):

- `dreamforge job create --prompt "..." --width 1024 --height 1024 [--steps 30] [--guidance 7] [--scheduler dpmpp_2m_karras] [--format png] [--embed-metadata] [--count 1] [--model-id UUID] [--idempotency-key KEY]`
  - Output: JSON with `job.id` and status
- `dreamforge job status JOB_ID`
- `dreamforge job logs JOB_ID [--tail 200] [--since 2025-09-12T21:00:00Z]`
- `dreamforge job artifacts JOB_ID [--download DIR]`
- `dreamforge job progress JOB_ID [--stream]`

Models (unified downloader — MUST):

- `dreamforge model download <ref> [--enable] [--name NAME] [--version VER]`
  - Refs: `hf:<repo>[@rev][#file]`, `civitai:<id|slug>[@ver]`
  - Env: `HF_TOKEN`, `CIVITAI_TOKEN` used when required
- `dreamforge model verify <model_id|ref>`
- `dreamforge model list [--enabled]`
- `dreamforge model get <model_id>`

Global flags:

- `--api-base URL` (env `DF_API_BASE`)
- `--output json|table` (default json)
- `-q/--quiet`, `-v/--verbose`

Exit codes:

- 0 success; non-zero on errors with printed ErrorResponse for API operations.

---

## 5) Env Vars & Config (MVP)

- `DF_API_BASE` — API base URL (default `http://localhost:8001/v1`)
- `DF_DB_URL`, `DF_REDIS_URL`, `DF_MINIO_ENDPOINT`, `DF_MINIO_ACCESS_KEY`, `DF_MINIO_SECRET_KEY`, `DF_MINIO_BUCKET`
- `DF_MODELS_ROOT` — filesystem path for installed models
- `HF_TOKEN`, `CIVITAI_TOKEN` — downloader auth tokens

---

## 6) Milestone Coverage

- M1: `POST /jobs`, `GET /jobs/{id}`
- M2: `/artifacts`, `/logs` (NDJSON), `/progress`, `/progress/stream`
- M3: `/models`, `/models/{id}` (read‑only), `model_id` in `JobCreateRequest`; CLI `model list|get|download|verify`
- M4: `count` in `JobCreateRequest`; add `item_index` to artifacts/progress/logs (batch)
- M7: GPU hygiene and resilience (OR‑001), retries/idempotency taxonomy

---

## 7) Next Steps

- Finalize YAML and generate `docs/openapi/openapi.v1.json` from the API app; CI adds spec diff.
- Scaffold `scripts/export_openapi.py` and Makefile targets. (Done.)
- Initialize CLI with models commands: list, get, download (hf:/civitai:), verify. (Done.)

Notes for M3 implementation specifics:
- Models list returns installed+enabled entries only; additional filters are deferred to keep surface lean.
- `civitai:` refs use numeric version IDs in M3 for reliable downloads; slug lookup is a future improvement.
