# M2 — Artifacts, Logs, Progress (SSE): Execution Plan

Last updated: 2025-09-14

Status: Proposed plan (awaiting sign‑off)

Owners: Engineering (Delivery), DX (Contracts), Product (Scope)

Related Masters: 08-roadmap (M2), 07-communication-interfaces-protocols, 06-data-model, 05-systems-components-modules, 10-openapi-makefile-cli

---

## 1) Executive Summary

Deliver the first-class observability and artifact surfaces around jobs:

- List artifacts for a job with presigned URLs and expirations.
- Stream structured logs as NDJSON with `tail` and `since_ts` filters (polling only; no long-lived tail in M2).
- Report aggregated progress via polling JSON and real-time Server-Sent Events (SSE). Keep SSE reconnect simple via `since_ts` only (no cursors/Last-Event-ID in M2).

The slice is additive on top of M1 (create job + status + one artifact written). It introduces no new services and keeps the API surface small and stable per Masters 02.

---

## 2) Goals & Non-Goals

Goals (this milestone):
- Public endpoints: `/v1/jobs/{id}/artifacts`, `/v1/jobs/{id}/logs`, `/v1/jobs/{id}/progress`, `/v1/jobs/{id}/progress/stream`.
- Presigned GET URLs for artifacts (MinIO/S3) with expirations.
- NDJSON logs with `tail` and `since_ts` parameters; stable, minimal line shape.
- Progress JSON and SSE with minimal aggregation (no dynamic stage weighting) and heartbeats.
- OpenAPI spec regenerated and committed; examples added.
- Unit and integration tests; examples and mini integration guide in docs.

Non‑Goals (defer to later milestones):
- Batch artifacts (`count>1`) and per-item progress (M4).
- Background downloader and model registry endpoints (M3/M4 per Roadmap numbering).
- GPU hygiene hardening, retries/DLQ, full error taxonomy enforcement (M5).
- Authentication/authorization (Beta).

---

## 3) User Stories & Acceptance Criteria

US‑A (Artifacts): As an integrator, I can list artifacts for a job and fetch them via presigned URLs.
- AC‑A1: `GET /v1/jobs/{id}/artifacts` returns array with `id, format, width, height, seed, item_index, s3_key, url, expires_at`.
- AC‑A2: URLs are valid for ≥ 60 minutes (configurable).
- AC‑A3: 404 for unknown job; empty list if no artifacts.

US‑L (Logs): As an integrator, I can tail job logs as NDJSON for troubleshooting.
- AC‑L1: `GET /v1/jobs/{id}/logs?tail=&since_ts=` returns NDJSON lines; `Content-Type: application/x-ndjson`.
- AC‑L2: Each line includes `ts, level, code, message, job_id, step_id` and optional `item_index`.
- AC‑L3: `tail` returns last N lines; `since_ts` filters by timestamp (UTC ISO‑8601).

US‑P (Progress): As an integrator, I can poll and/or stream job progress.
- AC‑P1: `GET /v1/jobs/{id}/progress` returns `{ progress: 0..1, items: [], stages: [...] }`.
- AC‑P2: `GET /v1/jobs/{id}/progress/stream` returns SSE with event types: `progress`, `log`, `artifact`, `error`, plus heartbeats.
- AC‑P3: On terminal state, stream emits final `progress` (1.0 for success) and closes.

---

## 4) Architecture & Design Overview

Public API (FastAPI):
- New routers under `/v1`:
  - `GET /jobs/{id}/artifacts` (JSON)
  - `GET /jobs/{id}/logs` (NDJSON)
  - `GET /jobs/{id}/progress` (JSON)
  - `GET /jobs/{id}/progress/stream` (SSE)

Persistence & Queries (SQLAlchemy):
- Use existing tables: `jobs`, `steps`, `events`, `artifacts`.
- Add repository helpers for listing artifacts, tailing events, and computing progress.

Presigned URLs (boto3):
- Use `modules.storage.s3.presign_get` with configurable expiry (default 1 hour), bounded by env caps.

Progress Model (initial, minimal):
- `queued=0.0`, `running=0.5`, `artifact.written=0.9`, `succeeded=1.0`; `failed` retains last known value.
- `stages` returned as static descriptors for forward compatibility; no dynamic weighting in M2.
- SSE: send current delta events and periodic heartbeats (`:\n`) every 15s; reconnect guidance via `since_ts` only.

---

## 5) Epics, Deliverables, and File Targets

### E2‑1 — Artifacts API + Presigned URLs
Deliverables:
- Endpoint `GET /v1/jobs/{id}/artifacts` returning list with presigned `url` and `expires_at`.
- Pagination not required (lists are small per job in M2).

Acceptance:
- Matches OpenAPI 10’s `Artifact` and `ArtifactListResponse` schemas.
- 404 for non‑existent job; 200 with empty array for jobs without artifacts.

Implementation Targets:
- `services/api/routes/artifacts.py` (new router)
- `services/api/schemas/artifacts.py` (Pydantic models) or extend existing schemas module
- `modules/persistence/repos.py` → `list_artifacts_by_job(job_id)`
- `modules/storage/s3.py` → reuse `presign_get` (expiry env/config)

### E2‑2 — Logs NDJSON Endpoint
Deliverables:
- Endpoint `GET /v1/jobs/{id}/logs?tail=&since_ts=` streaming NDJSON.
- Stable line shape with required fields.

Acceptance:
- `Content-Type: application/x-ndjson; charset=utf-8`; supports `tail` and `since_ts`.
- Lines ordered by `events.ts` ascending after filtering.

Implementation Targets:
- `services/api/routes/logs.py` (streaming response generator; polling only)
- `modules/persistence/repos.py` → `iter_events(job_id, since_ts=None, tail=None)`
- Log mapping: pull `message` from `payload_json.get("message")` else synthesize from `code`.

### E2‑3 — Progress (Polling JSON)
Deliverables:
- Endpoint `GET /v1/jobs/{id}/progress` returning aggregate progress.

Acceptance:
- Schema matches Masters 10 `ProgressResponse`.
- Returns `stages` array with basic weights, and `items` (empty array in M2).

Implementation Targets:
- `services/api/routes/progress.py` (JSON route + SSE in same module or separate)
- `modules/persistence/repos.py` → `progress_for_job(job_id)` deriving from job/step/events

### E2‑4 — Progress (SSE)
Deliverables:
- Endpoint `GET /v1/jobs/{id}/progress/stream` emitting `progress|log|artifact|error` events.
- Heartbeat comment lines; `since_ts` query parameter only (no Last-Event-ID/cursors in M2).

Acceptance:
- `Content-Type: text/event-stream; charset=utf-8`; cache disabled; connection kept alive.
- Closes stream after terminal job state with final `progress` event.

Implementation Targets:
- `services/api/routes/progress.py` (SSE generator)
- `modules/persistence/repos.py` → polling helper `iter_new_events(job_id, since_ts)`
- Backoff/poll interval: 500ms default (configurable via env).

### E2‑5 — Worker Event Instrumentation (Light)
Deliverables:
- Ensure key lifecycle events are present: `step.start`, `artifact.written`, `step.finish`, `job.finish`, `error`.
- Optional: add sparse `sampling.tick` info logs (non‑blocking).

Acceptance:
- Progress derivation works with current event set.

Implementation Targets:
- `services/worker/tasks/generate.py` (verify/augment minimal events only if necessary)

### E2‑6 — Contracts & OpenAPI
Deliverables:
- Update FastAPI models to align with Masters 10.
- Regenerate `docs/openapi/openapi.v1.json`.

Acceptance:
- New paths present with correct content types and basic examples.
- Examples reflect simplified reconnect (`since_ts` only) and minimal progress aggregation.

Implementation Targets:
- `services/api/schemas/*.py` additions
- `scripts/export_openapi.py`, `Makefile openapi` (already present)

### E2‑7 — Tests & CI
Deliverables:
- Unit tests for repo helpers and schema serialization.
- Integration tests (fake runner) for artifacts, logs, progress, SSE.

Acceptance:
- `make test` green; coverage over new endpoints; SSE test verifies event ordering and termination.

Implementation Targets:
- `tests/test_m2_artifacts.py`
- `tests/test_m2_logs.py`
- `tests/test_m2_progress.py` (polling + SSE)

### E2‑8 — DevEx & Docs
Deliverables:
- Mini integration guide snippets in this file and Masters 07/10 references.
- Curl examples; troubleshooting notes (noisy logs, empty artifacts, SSE disconnects).

Acceptance:
- Examples validated locally against Compose + fake runner.

Implementation Targets:
- This plan; minor additions in Masters 07/10 examples if needed.

---

## 6) Performance & Reliability Budgets (Dev/Staging)

- Artifacts: list latency p50 < 50ms (DB + presign round‑trips amortized), N ≤ 10 in M2.
- Logs: up to 10k lines via `tail` cap; stream as chunked response; gzip if `Accept-Encoding: gzip`.
- Progress polling: p50 < 20ms; no heavy aggregation.
- SSE: heartbeat every 15s (env `DF_SSE_HEARTBEAT_S`); poll DB at 500ms (env `DF_SSE_POLL_MS`); aim for ≤ 50 concurrent clients in dev.

Backpressure & Limits:
- Coalesce bursts for SSE; drop to latest progress if backlog.
- Enforce `tail` max=10000 lines; reject larger with `422 invalid_input`.

---

## 7) Telemetry & Metrics (Minimal)

- API counters/gauges: requests by route; SSE clients gauge; SSE events sent counter. No new metrics beyond these in M2.
- Worker already exposes minimal metrics; no changes required for M2.

---

## 8) Risks & Mitigations

- Long‑lived SSE connections block workers → use async generator; avoid holding DB transactions; keep queries bounded.
- NDJSON response buffering by proxies → set `Cache-Control: no-store`, `X-Accel-Buffering: no` (if nginx); send small keep‑alive chunks if needed.
- Presign configuration drift → centralize in `modules/storage/s3.py` and test expiry math.
- Event sparsity for progress → keep approximation model; add sampling ticks later without breaking contracts.

---

## 9) Rollout & Timeline (suggested)

Week 1 (or 3–4 working days):
- E2‑1/2 repo helpers + artifacts endpoint + NDJSON logs (with tests).

Week 2 (or 3–4 working days):
- E2‑3 progress polling + E2‑4 SSE + tests; OpenAPI regen; docs polish.

---

## 10) Validation Checklist (Exit Criteria)

- [ ] Artifacts endpoint returns signed URLs and expirations; 404 for unknown job.
- [ ] Logs endpoint produces NDJSON with `tail` and `since_ts` filters; shapes stable.
- [ ] Progress JSON returns aggregate value and basic stages.
- [ ] SSE streams `progress|log|artifact|error`, heartbeats, and terminates correctly. Reconnect recommendation uses `since_ts` only.
- [ ] OpenAPI updated and committed; examples included.
- [ ] Tests: unit + integration green in CI.

---

## 11) Implementation Notes & File Map

- API routes (new):
  - `services/api/routes/artifacts.py`
  - `services/api/routes/logs.py`
  - `services/api/routes/progress.py`
- Schemas:
  - `services/api/schemas/artifacts.py` (or add to `jobs.py` if preferred)
  - `services/api/schemas/progress.py`
- Utilities:
  - `services/api/utils/streaming.py` (tiny helpers for NDJSON and SSE formatting)
- Repos:
  - `modules/persistence/repos.py` → `list_artifacts_by_job`, `iter_events`, `progress_for_job`, `iter_new_events`
- Tests:
  - `tests/test_m2_artifacts.py`
  - `tests/test_m2_logs.py`
  - `tests/test_m2_progress.py`

---

## 12) Examples

Artifacts (200):
```json
{
  "artifacts": [
    {
      "id": "e3f7...",
      "format": "png",
      "width": 1024,
      "height": 1024,
      "seed": 123456789,
      "item_index": 0,
      "s3_key": "dreamforge/default/jobs/<job>/generate/20250914T010203_0_1024x1024_123456789.png",
      "url": "https://minio/...",
      "expires_at": "2025-09-14T03:10:00Z"
    }
  ]
}
```

Logs (NDJSON):
```
{"ts":"2025-09-14T01:02:03Z","level":"info","code":"step.start","message":"generate","job_id":"<job>","step_id":"<step>"}
{"ts":"2025-09-14T01:02:15Z","level":"info","code":"artifact.written","message":"artifact 0","job_id":"<job>","step_id":"<step>","item_index":0}
{"ts":"2025-09-14T01:02:16Z","level":"info","code":"job.finish","message":"succeeded","job_id":"<job>"}
```

Progress (JSON):
```json
{
  "progress": 0.9,
  "items": [],
  "stages": [
    { "name": "queued_to_start", "weight": 0.1 },
    { "name": "sampling", "weight": 0.8 },
    { "name": "finalize", "weight": 0.1 }
  ]
}
```

SSE (headers elided; reconnect with `since_ts`):
```
event: progress
data: {"progress":0.5}

event: artifact
data: {"item_index":0,"artifact_id":"e3f7...","s3_key":"dreamforge/...","format":"png","width":1024,"height":1024,"seed":123456789}

event: progress
data: {"progress":0.9}

event: progress
data: {"progress":1.0}
```

---

## 13) Out‑of‑Scope & Future Hooks

- Batch (`count>1`) and per‑item events (M4) — plan now for `item_index` to appear but keep items array empty.
- Admin background downloader (M9 optional) — no API exposure in M2.
- Stronger receipts and metadata (M10+) — keep `metadata_json` fields populated for forward compatibility.

---

## 14) Cross‑Document Notes

- Keep contracts aligned with Masters 07/10; update examples if field names diverge.
- Respect simplicity guardrails (Masters 02): avoid adding services/endpoints beyond the minimal set for M2.
