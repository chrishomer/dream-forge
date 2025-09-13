# Dream Forge — Masters Document 7: Communication (Interfaces and Protocols)

Last updated: 2025-09-12

Status: Draft for review

Owners: DX (API Contracts), Engineering (Runtime), Product (Scope)

References: docs/masters/01-introduction-vision-goals.md, docs/masters/02-principles-of-system-design.md, docs/masters/03-requirements.md, docs/masters/04-architecture-overview.md, docs/masters/05-systems-components-modules.md, docs/masters/06-data-model.md

---

## 1) Purpose

Define external and internal communication contracts: public REST endpoints, streaming semantics (SSE), log formats, error envelopes, idempotency, and internal task messaging. Keep the stack simple (REST + JSON + SSE) with clear evolution paths.

---

## 2) Protocol Stack & Formats

- Transport: HTTP/1.1
- Public API: REST + JSON (`application/json`)
- Streaming: Server-Sent Events (`text/event-stream`)
- Logs: NDJSON (`application/x-ndjson`)
- Binary artifacts: S3/MinIO presigned HTTP GET URLs
- Character encoding: UTF-8

---

## 3) Versioning & Base URL

- Base path: `/v1` (path-based versioning)
- Compatibility: additive changes within `v1` only; breaking changes trigger `v2`

---

## 4) Public Endpoints (MVP)

Jobs:

- `POST /v1/jobs` — Create job (generate)
- `GET /v1/jobs/{id}` — Get job status summary
- `GET /v1/jobs/{id}/artifacts` — List artifacts (with presigned URLs)
- `GET /v1/jobs/{id}/logs` — Structured logs as NDJSON
- `GET /v1/jobs/{id}/progress` — Aggregated progress JSON
- `GET /v1/jobs/{id}/progress/stream` — SSE for progress/events

Models (Registry):

- `GET /v1/models` — List enabled models (id, name, kind, version, installed, enabled, parameters_schema)
- `GET /v1/models/{id}` — Get full model descriptor

Admin (future, Beta option):

- `POST /v1/jobs` with `type="model_download"` (admin-triggered background download)
  or `POST /v1/models:download` (admin-only)

---

## 5) Headers & Conventions

- Request id: Client may send `X-Client-Request-Id`; server returns `X-Request-Id`
- Idempotency: `Idempotency-Key` on `POST /v1/jobs`
- Content negotiation: `Accept: application/json` or `text/event-stream` for SSE; `Accept: application/x-ndjson` for logs (optional)
- Compression: `Accept-Encoding: gzip` supported for JSON/NDJSON
- CORS (dev): permissive for `http://localhost`
- Auth: none in dev; API key/Bearer planned for Beta

---

## 6) Error Envelope

All error responses are JSON with consistent shape:

```
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json; charset=utf-8

{
  "code": "invalid_input",
  "message": "width must be >= 64 and <= 2048",
  "details": { "field": "width", "minimum": 64, "maximum": 2048 },
  "correlation_id": "req_01H..."
}
```

Error codes (initial): `invalid_input`, `not_found`, `conflict`, `oom`, `provider_error`, `infra_unavailable`, `timeout`, `internal`.

---

## 7) Jobs API Contracts

Create Job

- `POST /v1/jobs`
- Headers: `Idempotency-Key` (recommended)
- Body (generate):

```
{
  "type": "generate",
  "provider": "local-sdxl-epicrealism",
  "prompt": "an old-growth forest at dawn",
  "negative_prompt": "",
  "width": 1024,
  "height": 1024,
  "steps": 30,
  "guidance": 7.0,
  "scheduler": "dpmpp_2m_karras",
  "format": "png",
  "embed_metadata": true,
  "count": 1,
  "model_id": "<uuid>"
}
```

- Responses:
  - 202 Accepted: `{ "job": { "id": "...", "status": "queued", "type": "generate", "created_at": "..." } }`
  - 409 Conflict if duplicate idempotency key with changed body

Get Job Status

- `GET /v1/jobs/{id}`
- Response: `{ "id": "...", "type": "generate", "status": "running", "created_at": "...", "updated_at": "...", "steps": [ { "name": "generate", "status": "running" } ], "summary": { "count": 8, "completed": 3 } }`

List Artifacts

- `GET /v1/jobs/{id}/artifacts`
- Response:

```
{
  "artifacts": [
    {
      "id": "...",
      "format": "png",
      "width": 1024,
      "height": 1024,
      "seed": 123456789,
      "item_index": 0,
      "s3_key": "dreamforge/default/jobs/<job>/generate/169...._0_1024x1024_123456789.png",
      "url": "https://minio/...",
      "expires_at": "..."
    }
  ]
}
```

Logs (NDJSON)

- `GET /v1/jobs/{id}/logs?tail=200&since_ts=2025-09-12T21:00:00Z`
- Response: `application/x-ndjson` where each line is a JSON object with `ts`, `level`, `code`, `message`, `job_id`, `step_id`, optional `item_index`.

Progress (Polling)

- `GET /v1/jobs/{id}/progress`
- Response: `{ "progress": 0.42, "items": [ { "item_index": 0, "progress": 1.0 }, ... ], "stages": [ { "name": "sampling", "weight": 0.7 } ] }`

Progress (SSE)

- `GET /v1/jobs/{id}/progress/stream`
- Headers: `Accept: text/event-stream`
- Stream format: SSE events; see §8

---

## 8) Streaming (SSE)

Endpoint: `GET /v1/jobs/{id}/progress/stream`

- Content-Type: `text/event-stream; charset=utf-8`
- Caching: `Cache-Control: no-store`
- Keep-alive: heartbeat comment line every 15s (`:\n`)
- Reconnect: client may send `Last-Event-ID`; server includes `id:` in events (use `events.id` or a monotonic token)
- Backpressure: server may coalesce events; client should tolerate occasional bursts

Event types and payloads:

- `event: progress`

```
id: 01HG...
event: progress
data: { "progress": 0.55, "items": [ { "item_index": 0, "progress": 1.0 }, { "item_index": 1, "progress": 0.1 } ] }

```

- `event: log`

```
id: 01HG...
event: log
data: { "level": "info", "code": "sampling.tick", "message": "step 12/30", "item_index": 1 }

```

- `event: artifact`

```
id: 01HG...
event: artifact
data: { "item_index": 0, "artifact_id": "...", "s3_key": "...", "format": "png", "width": 1024, "height": 1024, "seed": 123456789 }

```

- `event: error`

```
id: 01HG...
event: error
data: { "code": "oom", "message": "Out of memory", "details": { "peak": 16777216 } }

```

Termination: server sends final `progress` at 1.0 and closes stream after terminal job state.

---

## 9) Models API Contracts

List Models

- `GET /v1/models?enabled=true`
- Response: `{ "models": [ { "id": "...", "name": "EpicRealism-XL", "kind": "sdxl-checkpoint", "version": "x.y", "installed": true, "enabled": true, "parameters_schema": { ... } } ] }`

Get Model Detail

- `GET /v1/models/{id}`
- Response: full descriptor with `parameters_schema`, `capabilities`, and file metadata (if exposed)

---

## 10) Internal Messaging (Tasks)

Broker: Redis

Queues:

- `gpu.default` — generate jobs (GPU-bound)
- `io.downloads` — downloader tasks (io-bound, future beta)

Task names and payloads (JSON):

- `jobs.generate`

```
{
  "job_id": "<uuid>",
  "step": "generate",
  "params": { ... },
  "preset": "<name>",
  "count": 8,
  "model_id": "<uuid>",
  "correlation_id": "req_..."
}
```

- `models.download` (future)

```
{
  "ref": "hf:repo@rev#file",
  "force": false,
  "verify_only": false,
  "correlation_id": "req_..."
}
```

Celery policies:

- acks-late; prefetch-limit small; bounded retries with backoff; visibility timeout > max task duration
- idempotent handlers for create/enqueue; deduplicate by idempotency key

---

## 11) Security & Access

- Dev: no auth; API bound to localhost; private buckets; presigned URLs
- Beta/V1: API keys (Authorization: Bearer), stricter CORS; secrets via env/orchestrator
- Input validation: strict body/query/schema validation; reject unsafe values

---

## 12) Rate Limiting & Retry Semantics

- Rate limiting (optional): 429 Too Many Requests with `Retry-After` header
- Infra issues: 503 Service Unavailable with `Retry-After`
- Clients should implement exponential backoff for 429/503

---

## 13) Timeouts

- HTTP request timeouts: client suggests 30s for JSON endpoints
- SSE: long-lived; heartbeat every 15s; clients reconnect with `Last-Event-ID` on disconnect

---

## 14) Observability

- Request/response logging (redact secrets); per-request `X-Request-Id`
- Metrics: request counts/latencies; SSE client counts; queue depth
- Correlation: propagate `correlation_id` into task payloads and events

---

## 15) Extensibility

- gRPC: optional internal adapters in future; no public gRPC in MVP
- WebSockets: not required; SSE suffices for one-way streaming
- Webhooks: future alternative to SSE for server-to-client notifications

---

## 16) Examples (Concise)

SSE session (excerpt):

```
event: progress
data: { "progress": 0.1, "items": [ {"item_index":0,"progress":0.2} ] }

event: log
data: { "level":"info","code":"sampling.start","item_index":0 }

event: artifact
data: { "item_index":0, "artifact_id":"...", "s3_key":"..." }
```

NDJSON (logs):

```
{"ts":"2025-09-12T21:20:00Z","level":"info","code":"step.start","job_id":"...","step_id":"..."}
{"ts":"2025-09-12T21:20:01Z","level":"info","code":"progress","job_id":"...","step_id":"...","payload":{"value":0.1,"item_index":0}}
```

---

## 17) Change Log & Links

- 2025-09-12: Initial draft of communication contracts (REST, SSE, NDJSON, tasks)

Related:

- Masters Doc 3: docs/masters/03-requirements.md
- Masters Doc 4: docs/masters/04-architecture-overview.md
- Masters Doc 5: docs/masters/05-systems-components-modules.md
- Masters Doc 6: docs/masters/06-data-model.md

