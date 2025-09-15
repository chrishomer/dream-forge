# Milestone 5 — Epic 5: Minimal Chaining (V2: generate → upscale)

Last updated: 2025-09-15

Status: Draft for review

Owners: Engineering (API/Worker), DX (Contracts/Docs), Product (Scope)

References: docs/masters/08-roadmap.md (M5), docs/masters/10-openapi-makefile-cli.md, docs/masters/04-architecture-overview.md, docs/masters/06-data-model.md, docs/masters/07-communication-interfaces-protocols.md

---

## 1) Summary

Lean M5 delivers a fixed two‑step chain within one job: `generate` → `upscale`. We keep the API surface minimal by adding an optional top‑level `chain` object to the existing generate request instead of introducing an open‑ended pipeline array. We persist both steps and their artifacts, compute combined progress (simple average), and continue streaming transitions and artifacts via the existing SSE event types (no new SSE event kinds).

This milestone builds on M4 (batch + per‑item seeds) and M3 (model registry). It reuses the current data model (`jobs`, `steps`, `events`, `artifacts`) and limits changes to a small request extension, orchestration, and one new worker task.

---

## 2) Outcomes & Acceptance Criteria (AC)

- Outcome: API accepts an optional `chain.upscale.scale` to enable a fixed two‑step chain; worker executes `generate` then `upscale`; steps/events persisted; artifacts per step; combined progress.
- AC‑1: Back‑compat: legacy requests without `chain` behave unchanged.
- AC‑2: When `chain.upscale.scale` is present (2 or 4), the server persists two ordered steps (`generate`, `upscale`) and enqueues `generate`.
- AC‑3: `GET /v1/jobs/{id}` lists both steps in order with statuses; `summary` reports `{ count, completed }` for the terminal step.
- AC‑4: `GET /v1/jobs/{id}/artifacts` returns artifacts from both steps; S3 keys include step prefix (`.../generate/...`, `.../upscale/...`).
- AC‑5: `GET /v1/jobs/{id}/progress` returns aggregate `progress` as a simple average of step completions (0.5/0.5); response shape remains `{ progress, items, stages }`; `items` reflect terminal step.
- AC‑6: `GET /v1/jobs/{id}/progress/stream` continues to emit `event: artifact`, `event: progress`, and `event: log` (for `step.start/finish`); no new event types.
- AC‑7: Failure behavior: generate failure stops chain and fails job; upscale failure fails job while preserving generate artifacts.
- AC‑8: OpenAPI regenerated and committed with a single chaining example using `chain.upscale.scale`.
- AC‑9: Tests cover chain creation, artifacts for both steps, combined progress to 1.0, SSE includes step transitions as `log`, and failure propagation.

---

## 3) Scope & Non‑Goals

### In Scope
- Backward‑compatible request schema extension via `chain.upscale.scale` (2 or 4).
- Minimal upscale implementation:
  - Fake path (DF_FAKE_RUNNER=1): upscale by image‑space resize (e.g., Pillow) from prior step’s artifacts.
  - Real path: placeholder for a lightweight upscaler (image‑space or simple SR); heavy model integration deferred.
- Orchestration: enqueue `jobs.generate` then `jobs.upscale` if and only if previous step `succeeded`.
- Progress math: simple average (0.5/0.5) across `generate` and `upscale`.
- SSE: keep current mapping; step transitions remain visible as `event: log` (codes `step.start/finish`).

### Out of Scope (defer to later milestones)
- Arbitrary step graphs or branching; only a fixed two‑step linear chain.
- Advanced super‑resolution models and tuning; use simple, reliable method for MVP.
- Cross‑job chaining or referencing artifacts between jobs.
- Persisted step‑level configuration schemas beyond minimal parameters.

---

## 4) Epics Breakdown

### E5‑1 — Request Schema: Chain Support (API + Schemas + Validation)

- Objective: Extend `JobCreateRequest` to accept an optional `chain.upscale.scale` (2 or 4). Maintain full back‑compat with the current `type=generate` body.
- Design:
  - Shape: `chain?: { upscale?: { scale?: 2|4 } }`.
  - Validation: `scale` accepts 2 or 4; if absent, default to 2. Absence of `chain` implies legacy single‑step behavior.
- Files:
  - `services/api/schemas/jobs.py` — add `ChainUpscale` and `Chain` models; extend `JobCreateRequest` with optional `chain`.
  - `services/api/routes/jobs.py` — detect `chain.upscale` and persist two steps accordingly.
- AC:
  - Posting with only legacy top‑level fields still works.
  - Posting with `pipeline=[{generate...},{upscale...}]` creates a job with two steps persisted and the first step enqueued.

### E5‑2 — Orchestration: Create Job with Chain & Schedule

- Objective: Create and run two ordered steps within one job, with proper status transitions and events.
- Design:
  - Persistence: add `create_job_with_chain(session, scale)` that creates a `Job` (queued) and two `Step` rows (queued) in order; store per‑step metadata (e.g., `{scale}`) in `Step.metadata_json`.
  - Scheduling: API enqueues only the first step task (`jobs.generate`). The worker marks step/job running, completes, and on success triggers the next step (`jobs.upscale`).
  - Failure: if a step fails, mark step `failed`, mark job `failed`, append `error` and `job.finish` events.
  - Events: ensure `step.start`/`step.finish` are emitted for both steps.
- Files:
  - `modules/persistence/repos.py` — add `create_job_with_steps(...)`; keep `create_job_with_step(...)` for back‑compat.
  - `services/api/routes/jobs.py` — branch: if pipeline detected → call `create_job_with_steps`; enqueue first step; otherwise legacy path.
  - `services/worker/tasks/generate.py` — on success, enqueue `jobs.upscale` if an `upscale` step exists for the job.
- AC:
  - Two steps persisted in created order; `GET /v1/jobs/{id}` returns both.
  - Upstream failure prevents enqueuing/downstream execution.

### E5‑3 — Worker: Upscale Task (Fake + Minimal Real)

- Objective: Implement `jobs.upscale(job_id)` task that reads prior step artifacts, upscales per item, writes new artifacts, and emits events.
- Design (MVP):
  - Enumerate generate artifacts for the job ordered by `item_index`.
  - Fake path: open PNG bytes, resize by `scale` with Pillow (`Image.BICUBIC`/`LANCZOS`), write PNG.
  - Real path placeholder: image‑space resize (CPU) suffices; defer SR model integration.
  - Persistence: insert artifacts with `step_id=upscale_step_id`, preserve `item_index`, `seed` (inherit), format `png` by default; key under `dreamforge/default/jobs/{job_id}/upscale/...`.
  - Events: `step.start`, per‑item `artifact.written`, `step.finish`, `job.finish` (only if this is terminal step).
- Files:
  - `services/worker/tasks/upscale.py` — new module with `@shared_task(name="jobs.upscale")`.
  - `services/worker/celery_app.py` — import/register `services.worker.tasks.upscale`.
- AC:
  - With `DF_FAKE_RUNNER=1`, upscaled artifacts exist with larger dimensions (e.g., 64x64 → 128x128 for `scale=2`).
  - Artifacts have correct key prefixes and metadata and appear in `/artifacts`.

### E5‑4 — Progress: Combined Across Steps (Simple Average)

- Objective: Provide combined progress while preserving the existing response shape.
- Design:
  - Weights: fixed `generate: 0.5`, `upscale: 0.5` (no env knob in M5).
  - Step progress: `(completed_artifacts_for_step / count)` clipped to [0, 1].
  - Combined: `sum(step_weight[i] * step_progress[i])`.
  - API response for `/progress` remains `{ progress, items, stages }`. Do not add `per_step` in M5.
- Files:
  - `services/api/routes/progress.py` — compute per‑step completion and combined; include two stages with weights; do not add new fields.
  - `modules/persistence/repos.py` — add helper(s) if needed for per‑step completion counts.
- AC:
  - `/progress` reflects combined progress rising through generate first, then upscale to 1.0 at job completion.

### E5‑5 — SSE: Reuse Existing Event Types

- Objective: Keep SSE surface stable while reflecting multi‑step execution.
- Design:
  - Keep `step.start`/`step.finish` as `event: log` with their existing codes.
  - Keep `artifact.written` mapped to `event: artifact` for both steps.
  - Maintain periodic `progress` events and `:` heartbeat.
- Files:
  - `services/api/routes/progress.py` — no event‑type changes; may include step name in payload if trivially available.
- AC:
  - SSE stream contains at least one `event: step` for each step and `event: artifact` for both steps; stream terminates when job is terminal.

### E5‑6 — OpenAPI & Docs

- Objective: Reflect new request shape and SSE examples in the committed spec and docs.
- Tasks:
  - Update `JobCreateRequest` schema to include `chain.upscale.scale`.
  - Add examples: legacy single‑step; chained generate→upscale using `chain`.
  - SSE examples remain the same event types; include step.start/finish as NDJSON log examples (optional).
  - Regenerate `docs/openapi/openapi.v1.json` via `make openapi` and update Masters 10 with examples.
- Files:
  - `services/api/schemas/jobs.py` (source of truth for schema)
  - `docs/openapi/openapi.v1.json` (generated)
  - `docs/masters/10-openapi-makefile-cli.md` (examples section)
- AC:
  - Spec changes committed and validated; examples render as expected.

### E5‑7 — Tests: Unit + Integration + E2E (Fake)

- Objective: Ensure correctness via automated tests and a runnable validation script.
- New tests (under `tests/`):
  - `test_m5_pipeline_create_and_steps.py` — create with pipeline; assert two steps and order.
  - `test_m5_upscale_artifacts_shape_and_keys.py` — assert both generate and upscale artifacts exist; item indexes preserved; keys contain `.../upscale/...`.
  - `test_m5_progress_combined_and_per_step.py` — verify combined progress rises and reaches 1.0; check `per_step`.
  - `test_m5_sse_step_transitions.py` — SSE includes `event: step` for both steps and `event: artifact` for upscale.
  - `test_m5_failure_propagation.py` — force upscale failure (env flag or injected error) → job `failed` and `generate` artifacts still present.
- E2E validation script:
  - `scripts/validate_m5.py` — mimic M4 validator; posts pipeline job, polls status, fetches artifacts, and asserts presence from both steps; prints sample SSE transcript.
- AC:
  - All tests pass in `DF_CELERY_EAGER=true` and `DF_FAKE_RUNNER=1` mode.

### E5‑8 — DX/Observability (Minimal)

- Objective: Keep minimal but helpful metrics and toggles.
- Tasks (optional for M5):
  - Add counters for `jobs_upscale_started_total`, `jobs_upscale_succeeded_total`, `jobs_upscale_failed_total` via Prometheus client in `upscale.py` (exposed on worker metrics port).
  - Add `DF_PROGRESS_WEIGHTS` env parsing in API to tune step weights (format: `generate:0.5,upscale:0.5`), default to 0.5/0.5.
- AC: Metrics visible in `/metrics` (worker) when enabled; weights default behavior unchanged if env missing/invalid.

---

## 5) Interfaces & Contracts

### Request (POST /v1/jobs)
- Legacy (unchanged): top‑level `type=generate` with existing fields.
- New (M5):
```json
{
  "pipeline": [
    { "type": "generate", "prompt": "a castle", "width": 64, "height": 64, "steps": 2, "count": 3 },
    { "type": "upscale",  "scale": 2, "mode": "image" }
  ]
}
```
- Validation: if `pipeline` present but invalid, return `422 invalid_input` with `{ field: 'pipeline', reason: 'M5 only supports [generate, upscale]' }`.

### Status (GET /v1/jobs/{id})
- `steps`: now contains two elements. `summary` remains `{ count, completed }` — interpreted as terminal step’s artifact completion.

### Artifacts (GET /v1/jobs/{id}/artifacts)
- Returns artifacts for all steps; keys encode step (`.../generate/...`, `.../upscale/...`).

### Progress (GET /v1/jobs/{id}/progress)
- Add `per_step` object and `stages` includes two entries with weights.

### SSE (GET /v1/jobs/{id}/progress/stream)
- Emits `event: step`, `event: artifact`, and `event: progress` per E5‑5.

---

## 6) Data Model & Storage

- No schema changes required. Existing uniqueness `(job_id, step_id, item_index)` supports per‑step artifacts.
- Persist per‑step parameters in `steps.metadata_json` for traceability (e.g., upscale `scale`).
- S3 keying:
  - Generate: `dreamforge/default/jobs/{job_id}/generate/{ts}_{idx}_{WxH}_{seed}.png`
  - Upscale:  `dreamforge/default/jobs/{job_id}/upscale/{ts}_{idx}_{W'xH'}_{seed}.png`

---

## 7) Implementation Plan (Tasks)

- API & Schemas
  - [ ] Add pipeline models (`StepGenerate`, `StepUpscale`) to `services/api/schemas/jobs.py`.
  - [ ] Extend `JobCreateRequest` with optional `pipeline` and normalization helpers.
  - [ ] Update `services/api/routes/jobs.py` to call `create_job_with_steps(...)` when pipeline present; else legacy.
- Persistence
  - [ ] Add `create_job_with_steps(...)` to `modules/persistence/repos.py` that seeds two steps and returns job.
- Worker
  - [ ] Create `services/worker/tasks/upscale.py` with `@shared_task(name="jobs.upscale")`.
  - [ ] Import `upscale` in `services/worker/celery_app.py` to register task.
  - [ ] In `generate.py`, after success, detect next step and enqueue `jobs.upscale`.
- Progress & SSE
  - [ ] Extend `/progress` to compute per‑step completion and combined weighted progress.
  - [ ] Extend `/progress/stream` event mapper to emit `event: step` for step transitions and include step name in artifact payload where available.
- Docs & Spec
  - [ ] Update examples in Masters 10 and regenerate `docs/openapi/openapi.v1.json`.
- Tests & E2E
  - [ ] Add M5 test modules listed in E5‑7.
  - [ ] Add `scripts/validate_m5.py` for a quick smoke.

---

## 8) Configuration & Env Knobs (M5)

- `DF_FAKE_RUNNER` (worker): keep `1` for CI/dev to resize images using Pillow in both steps.
- `DF_PROGRESS_WEIGHTS` (api; optional): `generate:0.5,upscale:0.5`; fallback to 0.5 each on parse error.

---

## 9) Risks & Mitigations

- VRAM headroom during upscale: Fake path avoids GPU; real path can reuse CPU image‑space resize to avoid VRAM pressure in M5. Heavy SR deferred.
- API surface creep: keep `pipeline` constrained; reject anything beyond `[generate, upscale]` in M5.
- SSE volume: rate controlled already by `DF_SSE_POLL_MS` and heartbeats; no change needed.
- Back‑compat: preserve legacy request; add tests to ensure non‑pipeline requests remain identical.

---

## 10) Rollout & Verification

- Dev: implement behind default‑open behavior (no flags required); fake runner for stability.
- Compose: no changes required; same services.
- Verification steps:
  1) `make up-fake`
  2) POST pipeline job; confirm two steps in `/v1/jobs/{id}`.
  3) Verify artifacts in both `generate/` and `upscale/` prefixes; seeds preserved; indices aligned.
  4) Verify `/progress` combined math and SSE `event: step` occurrences.
  5) Run `make e2e-m4` (regression) and new `validate_m5.py`.

---

## 11) Estimates & Timeline (2–3 dev days)

- E5‑1 Schema & API plumbing: 0.5d
- E5‑2 Orchestration + repo helper: 0.5d
- E5‑3 Upscale task (fake + minimal real): 0.5–1.0d
- E5‑4/5 Progress + SSE mapping: 0.5d
- E5‑6/7 Docs, OpenAPI, tests, validator: 0.5–1.0d

---

## 12) File‑Level Change Index

- API
  - `services/api/schemas/jobs.py` — add pipeline models; extend request schema.
  - `services/api/routes/jobs.py` — create multi‑step jobs; enqueue first step; idempotency unchanged.
  - `services/api/routes/progress.py` — combined progress; `event: step` mapping; include step name in artifact payload.
  - `services/api/routes/logs.py` — no change expected.
- Worker
  - `services/worker/tasks/upscale.py` — new file; fake + minimal real implementation.
  - `services/worker/tasks/generate.py` — enqueue next step on success.
  - `services/worker/celery_app.py` — import/register `upscale` task.
- Persistence
  - `modules/persistence/repos.py` — add `create_job_with_steps(...)` and helpers for per‑step completion.
- Docs & Spec
  - `docs/masters/10-openapi-makefile-cli.md` — examples.
  - `docs/openapi/openapi.v1.json` — regenerated.
- Tests & Scripts
  - `tests/test_m5_*.py` — new.
  - `scripts/validate_m5.py` — new.

---

## 13) Definition of Done (DoD)

- All ACs satisfied; tests added and passing locally in fake runner mode.
- OpenAPI regenerated and committed; examples updated.
- Docs cross‑referencing: this plan linked from Roadmap item M5 in PR description.
- No additional services introduced; simplicity guardrails remain intact.
