# Milestone 4 — Batch Generation (1–100) + Per‑Item Seeds

Last updated: 2025-09-15

Status: Planning (ready for implementation)

Owners: Backend (API + worker), DX (contracts/docs), Product (scope/AC)

References
- Masters 08 Roadmap (M4): docs/masters/08-roadmap.md
- Masters 03 Requirements (FR‑007, FR‑008, FR‑014, FR‑024, FR‑030..033; NFR‑001, NFR‑003, NFR‑013): docs/masters/03-requirements.md
- Masters 06 Data Model (batch fields `item_index`, seeds in `artifacts`, `count` in job params): docs/masters/06-data-model.md
- Masters 07 Interfaces (batch semantics in APIs/SSE): docs/masters/07-communication-interfaces-protocols.md
- Masters 10 OpenAPI/Makefile/CLI (target surface for M4 fields): docs/masters/10-openapi-makefile-cli.md

Code Pointers (current baseline)
- API
  - `services/api/routes/jobs.py` → POST `/v1/jobs` (add `count`; status summary currently static)
  - `services/api/routes/progress.py` → `/progress`, `/progress/stream` (aggregate only; add per‑item and batch‑aware agg)
  - `services/api/routes/logs.py` → `/logs` (NDJSON already surfaces `item_index` when present)
  - `services/api/routes/artifacts.py` → `/artifacts` (already returns `item_index` with presigned URLs)
  - `services/api/schemas/jobs.py` → `JobCreateRequest` (add `count`, bounds 1..100)
  - `services/api/schemas/progress.py` → `ProgressResponse` already has `items: [ { item_index, progress } ]`
- Worker
  - `services/worker/tasks/generate.py` → currently renders a single item (index 0); emits `model.selected`, `artifact.written`, and terminal events. Extend to N items and per‑item seeds.
- Persistence
  - `modules/persistence/models.py` → `Artifact.seed` and `Artifact.item_index` already present; `Job.params_json` to carry `count`.
  - `modules/persistence/repos.py` → helpers for events/artifacts; `progress_for_job` stays as‑is. Batch aggregate will be computed in API routes.

---

## 1) Purpose & Outcome

Enable clients to request a batch of images from a single job by specifying `count` (default 1, max 100). Each item in the batch receives its own runtime seed. The system emits per‑item events and exposes aggregated progress across the batch, while artifact keying and metadata include the per‑item index and seed.

Definition of Done (DoD)
- `POST /v1/jobs` accepts `count` (1..100). Responses, status, logs, progress, and artifacts reflect batch semantics with `item_index`.
- Worker generates items sequentially (0..count‑1) under one `generate` step. For each item, it assigns a seed at runtime and records it in logs and artifact metadata.
- SSE `/progress/stream` includes aggregate progress plus an `items` array with per‑item progress snapshots; NDJSON logs include `item_index` for relevant events.
- `GET /v1/jobs/{id}` returns `summary: { count, completed }` where `completed` equals the number of items that produced an artifact.
- OpenAPI is updated; examples include batch requests and responses. Tests cover API shape, worker behavior (fake runner), and progress/artifacts.

Out of Scope (explicit, to remain lean per Masters 02)
- Seed derivation strategies beyond “random per item” (e.g., fixed or deterministic sequences). A future `seed_strategy` could introduce this.
- Parallel item rendering within a single job. Items run sequentially in MVP to minimize GPU contention and complexity.
- Multi‑step pipelines or cross‑item deduplication. Chaining remains M5.

---

## 2) Acceptance Criteria (Trace to Masters)

- AC‑M4‑1 (FR‑007): Creating a job with `count=5` yields exactly 5 artifacts with `item_index` 0..4.
- AC‑M4‑2 (FR‑008): When `seed` is omitted and `count>1`, each item uses a distinct random seed chosen immediately before rendering that item. When `seed` is provided and `count>1`, MVP behavior still randomizes per item.
- AC‑M4‑3 (FR‑024): Artifact keys include the item index: `.../{step}/{ts}_{index}_{WxH}_{seed}.{ext}` and the DB row stores `item_index` and `seed`.
- AC‑M4‑4 (FR‑014, FR‑030..033): `/logs` include per‑item `artifact.written` lines with `item_index` and `seed`; `/progress` returns `{ progress, items:[{item_index, progress}], stages }`; `/progress/stream` emits periodic aggregate progress and passes through per‑item events.
- AC‑M4‑5 (FR‑001): `GET /v1/jobs/{id}` summary shows `{ count, completed }` and converges to `{5,5}` for the example above.
- AC‑M4‑6 (NFR‑003): Server rejects `count<1` or `count>100` with `422 invalid_input`.

---

## 3) Design Notes & Lean Choices

- Sequential execution: One job → one step (`generate`) that loops items 0..count‑1. Keeps VRAM steady and simplifies progress semantics. A future optimization may load the pipeline once per job; MVP may reload per item to minimize code churn (acceptable for dev/staging; performance tuning is M7/M12).
- Seed policy (MVP): `seed_per_item = user_seed_ignored_if_count>1 or fresh_random_if_seed_missing`. Explicit `seed_strategy` is deferred.
- Progress computation (MVP): Aggregate `progress = completed_items / count`. Per‑item progress is 1.0 when its artifact is written; no “ticks” are emitted during sampling in MVP (optional lightweight `sampling.tick` can be added without affecting ACs).
- Error semantics (NFR‑013): If any item fails, the step and job fail; partial artifacts for prior items remain retrievable.

---

## 4) Epics & Tasks

### Epic A — API Contract: Add `count` and Batch Summary

Scope
- Extend job creation and status to be batch‑aware while keeping surface minimal.

Tasks
- `services/api/schemas/jobs.py`
  - Add `count: int = Field(1, ge=1, le=100)` to `JobCreateRequest`.
  - Document semantics in the model docstring.
- `services/api/routes/jobs.py`
  - Persist `count` in `params_json` when creating a job.
  - For `GET /v1/jobs/{id}`, compute `summary = {"count": N, "completed": K}`. Obtain `N` from `job.params_json.get("count", 1)`; compute `K` via artifacts count for that job.
- Validation & errors
  - Reject invalid `count` in request with `422 invalid_input`.

Acceptance
- Creating a job with `count=5` persists `params_json.count=5`.
- `GET /v1/jobs/{id}` shows `summary.count=5` and `summary.completed` grows to 5.

---

### Epic B — Worker: Batch Loop & Per‑Item Seeds

Scope
- Generate `count` items sequentially with per‑item runtime seeds; write artifacts and events with `item_index`.

Tasks
- `services/worker/tasks/generate.py`
  - Read `count = int(params.get("count", 1))`; bound to [1,100] defensively.
  - For each `i in range(count)`:
    - Choose `seed_i`: if `count>1`, ignore any provided `seed` and generate a new random seed; else preserve provided `seed` or randomize if missing.
    - Append event `seed.assigned` with `{ item_index: i, seed: seed_i }`.
    - Render item via existing `_run_fake` or `_run_real` using `seed_i`.
    - Build S3 key `.../{ts}_{i}_{WxH}_{seed_i}.{ext}`.
    - `repos.insert_artifact(..., item_index=i, seed=seed_i, ...)`.
    - Append `artifact.written` event with `{ item_index: i, seed: seed_i, s3_key, width, height }`.
  - Preserve existing `model.selected`, `step.start/finish`, `job.finish` emissions.
- Failure handling
  - On exception for any item, mark step/job failed and emit `error` event including `{ item_index }` when available.

Acceptance
- Fake runner: a `count=5` job produces five artifacts; NDJSON logs include five `seed.assigned` and five `artifact.written` events with indices 0..4.

---

### Epic C — Progress: Aggregate and Minimal Items Array

Scope
- Return batch‑aware progress snapshots and stream SSE updates with aggregate and per‑item states.

Tasks
- `modules/persistence/repos.py`
  - No changes. Keep `progress_for_job` unchanged; compute batch aggregate in the route using artifact counts.
- `services/api/routes/progress.py`
  - For `/progress`, load `N = count` from `job.params_json`; list artifacts; compute `K = len(arts)`; aggregate `progress = K / N` (bounded 0..1). Build `items = [{ item_index, progress: 1.0 }]` only for completed indices (omit zero‑progress entries for lean payloads).
  - For `/progress/stream`, keep emitting periodic `event: progress` with `{ progress, items, stages }`. Pass through existing events normally.
- Stages remain `_static_stages()` from M2.

Acceptance
- `/progress` for a 5‑item job shows `progress` moving from 0.0 → 1.0 as items complete; `items` contains entries with `progress: 1.0` for finished indices.
- SSE emits a `progress` event reflecting the aggregate after each `artifact.written`.

---

### Epic D — Logs (No New Event Types)

Scope
- Keep event taxonomy minimal. Do not add a `seed.assigned` event; rely on `artifact.written` including `item_index` and `seed`.

Tasks
- No route changes needed. Ensure worker emits `artifact.written` with the correct fields per item.

Acceptance
- `GET /v1/jobs/{id}/logs` shows per‑item `artifact.written` entries with correct indices and seeds.

---

### Epic E — OpenAPI & Examples

Scope
- Update schema and examples to reflect batch semantics.

Tasks
- Update `services/api/schemas/jobs.py` and regenerate spec via `make openapi` → `docs/openapi/openapi.v1.json`.
- Ensure `JobCreateRequest` contains `count` with `{ minimum: 1, maximum: 100, default: 1 }`.
- Add example responses for `/jobs/{id}`, `/progress`, and SSE snippets showing `item_index`.

Acceptance
- Spec contains `count` and batch shapes (artifacts include `item_index`; progress includes `items`).

---

### Epic F — Tests (Unit + Integration with Fake Runner)

Scope
- Validate API/worker behavior for batch requests with the fake runner and filesystem‑backed S3 monkeypatch.

Tasks
- Add tests:
  - `test_m4_batch_artifacts_and_keys.py`: POST job with `count=5`; assert 5 artifacts; verify keys include `_0_`, `_1_`, ...; seeds list has length 5 and at least two seeds differ.
  - `test_m4_progress_and_sse.py`: Verify `/progress` aggregate and minimal items; SSE contains `event: progress` updates and `artifact` events with `item_index`.
  - `test_m4_logs_per_item.py`: NDJSON includes five `artifact.written` with correct indices and seeds.
  - `test_m4_count_validation.py`: `count=0` and `count=101` rejected with `422`.
  - `test_m4_seed_randomized_for_batches.py`: With `count=3` and any provided seed, produced seeds are not all identical.

Acceptance
- All new tests pass locally; existing M1–M3 tests remain green.

---

### Epic G — Developer Experience & Makefile

Scope
- Minor DX updates; keep CLI job wrapper optional.

Tasks
- `DEV.md`: Add brief M4 notes about `count`, logs/progress examples, and performance expectations for large batches.
- `Makefile`: none required; optionally add `make e2e-m4` placeholder when an end‑to‑end script exists.

Acceptance
- Docs guide a new developer to try batch rendering with `DF_FAKE_RUNNER=1`.

---

### Epic H — Performance & Safety (MVP level)

Scope
- Keep execution simple and safe while noting follow‑ups.

Tasks
- Sequential loop with explicit VRAM cleanup already happens at the end of the step; acceptable for MVP.
- Optional micro‑optimization (deferred unless trivial): in real runner path, load pipeline once per job and reuse per item (requires refactor of `_run_real`/`_child_generate` to accept a list of seeds and to stream back multiple images).
- Timeouts per item are not introduced in M4; step‑level timeout is a later milestone (M7/M12). Document current behavior.

Acceptance
- No GPU OOM regressions observed in dev with modest counts; failures do not leak GPU memory (validated informally for now; formal OR‑001 in M7).

---

## 5) Risks & Mitigations

- Pipeline reload cost (real runner): Rendering N>1 items may reload the model N times. Mitigation: accept temporarily for MVP; document; plan refactor under M7/M12.
- Long‑running jobs with large `count`: Without per‑item timeouts, a hang stalls the step. Mitigation: keep `count<=100`; surface SSE heartbeats; add timeouts in M7.
- Progress granularity: Only jumps on artifact completion in MVP. Mitigation: optional lightweight `sampling.tick` logs; UIs can still show aggregate progress.
- Error taxonomy: All failures currently `internal`. Mitigation: tighten in M7.

---

## 6) Timeline & Checkpoints (1–2 working days)

Day 1
- Epics A, B scaffolding: schema change (`count`), worker loop with seeds, artifact keying; unit tests for count validation and artifacts.
- Epics C, D: batch progress computation in routes; logs NDJSON already compatible (no new event types).

Day 2
- Epics E, F: OpenAPI regen, examples, and full test suite (progress + SSE). DX doc note in DEV.md.
- Buffer for small refactors and CI fixes.

---

## 7) Definition of Ready (DOR)

- Masters docs confirm M4 semantics (done). No DB migrations required (fields exist).
- Fake runner path sufficient for tests; S3 monkeypatch utilities available and used in prior tests.
- Agreement on lean progress: aggregate based on completed items; no mid‑sampling ticks necessary for AC.

---

## 8) Future Work (Follow‑ups captured under docs/future/)

- Single‑load pipeline across items to reduce latency and VRAM thrash.
- Seed strategies: `fixed`, `increment`, `deterministic_sequence(base_seed)`; expose `seed_strategy` field.
- Parallelism caps: optional intra‑job parallel rendering with GPU headroom checks.
- Per‑item timeouts and cancellation; per‑item error isolation with partial success semantics.
- Rich progress: sampling ticks and stage weights proportional to `steps`; emit GPU metrics per item.

---

## 9) Quick Implementation Checklist

- [ ] Add `count` to `JobCreateRequest` with bounds; regenerate OpenAPI.
- [ ] Persist `count` in job params; validate in route.
- [ ] Worker loop: per‑item seed assignment; events; artifacts with indexed keys.
- [ ] Batch‑aware `/progress` and SSE aggregate.
- [ ] Status summary `{ count, completed }`.
- [ ] Tests: batch artifacts, progress/SSE, logs, validation, seed behavior.
- [ ] Update DEV.md; run `make openapi` and commit spec.
