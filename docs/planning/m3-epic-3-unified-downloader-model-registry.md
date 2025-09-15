# Milestone 3 — Unified Downloader + Model Registry (Read APIs)

Last updated: 2025-09-15

Status: Planning (ready for implementation)

Owners: DX (CLI + contracts), Backend (API + persistence), Product (scope/AC)

References:
- Masters 08 Roadmap (M3): docs/masters/08-roadmap.md
- Masters 03 Requirements (FR-080..097): docs/masters/03-requirements.md
- Masters 02 Principles (deterministic model layout, background jobs posture): docs/masters/02-principles-of-system-design.md
- Masters 10 OpenAPI/CLI (target surface; adjust milestone label to M3): docs/masters/10-openapi-makefile-cli.md

---

## 1) Purpose & Outcome

Deliver the “Unified Downloader + Model Registry” thin slice with a read‑only Models API and a CLI that can download and register models from multiple sources. Jobs can target a specific `model_id` selected from the registry.

Outcome (DoD):
- CLI `dreamforge model download` supports at least Hugging Face (`hf:`) and CivitAI (`civitai:`) references; verifies files; installs under a deterministic `DF_MODELS_ROOT` layout; writes a model descriptor and upserts the registry.
- API exposes `GET /v1/models` and `GET /v1/models/{id}` showing registry entries (enabled only by default) and a full descriptor respectively. In M3 the API remains strictly read‑only with no extra filters to keep the surface minimal.
- `POST /v1/jobs` accepts an optional `model_id` that is validated against the registry; worker uses the selected model’s `local_path` if installed and enabled.
- OpenAPI v1 updated; tests cover Models API, CLI flows (mocked network), and job execution using `model_id` (with fake runner).

Out of scope (explicit):
- Background downloader job via API (Roadmap M9 optional).
- Model enable/disable mutation APIs; write operations stay in CLI for MVP.

---

## 2) Success Metrics

- AC‑1: `dreamforge model download hf:<repo>@<rev>#<file>` installs files under `DF_MODELS_ROOT` with checksums recorded; registry shows `installed=true` and `enabled=true`.
- AC‑2: `dreamforge model download civitai:<id|slug>@<version>` installs and registers similarly.
- AC‑3: `dreamforge model list` shows registered models; `dreamforge model get <id>` outputs full JSON descriptor.
- AC‑4: `GET /v1/models` returns at least one installed model; `GET /v1/models/{id}` returns full descriptor including a minimal `parameters_schema` and constant `capabilities=["generate"]`.
- AC‑5: `POST /v1/jobs` with `model_id` runs using that model; artifacts/logs/progress unchanged. With omitted `model_id`, default installed model is used.
- AC‑6: OpenAPI spec includes `/models`, `/models/{id}` and `model_id` in `JobCreateRequest`; CI spec export and tests pass.

---

## 3) Architecture Overview (MVP)

- Registry: persisted in Postgres (`models` table exists). Accessed via new repository helpers in `modules/persistence/repos.py`.
- Deterministic install layout: `${DF_MODELS_ROOT}/{kind}/{name}@{version}/...`. The registry’s `local_path` points at the root directory. Files hashed (SHA256) and listed in `files_json`.
- Descriptor: written to `${local_path}/model.json` and mirrored in DB (fields below). Serves as the source of truth for CLI idempotency and verification.
- Unified downloader: core library in CLI layer to resolve a source ref → concrete descriptor → fetch files → verify → normalize layout → upsert registry.
- Source adapters: `hf:` and `civitai:` implement a common interface (`resolve`, `fetch`, `verify`, `to_model_descriptor`).
- Models API: read‑only; lists enabled models by default; item endpoint returns full descriptor for UIs.
- Jobs integration: `JobCreateRequest` gains `model_id` (UUID). Worker resolves chosen model from registry; falls back to default model (configured or first installed+enabled SDXL checkpoint).

Descriptor (logical fields; mapped to DB columns — lean set):
- `id` (UUID), `name` (str), `kind` (e.g., `sdxl-checkpoint`), `version` (str), `checkpoint_hash` (str|nullable), `source_uri` (str), `local_path` (str|nullable),
- `installed` (bool), `enabled` (bool), `parameters_schema` (obj; minimal static skeleton for MVP), `capabilities` (constant `["generate"]`), `files_json` (list[{path, sha256, size}]).

---

## 4) Epics & Workstreams

### Epic A — Registry Foundation & Repository Helpers

Scope
- Implement model repository functions; ensure schema aligns with FR‑080..097 and existing migration.

Tasks
- Add repo APIs in `modules/persistence/repos.py`:
  - `list_models(enabled: bool|None = True) -> list[Model]`
  - `get_model(id: UUID) -> Model|None`
  - `upsert_model(descriptor: dict) -> Model` (by unique key: `name+version+kind`)
  - `mark_installed(id, local_path, files_json)`; `mark_enabled(id, enabled)`
- Provide a helper to obtain the “default” model (first installed+enabled `sdxl-checkpoint`).

Acceptance
- Unit tests for list/get/upsert; uniqueness respected; timestamps maintained.

Risks/Mitigations
- Unique conflicts → use `ON CONFLICT` pattern via SQLAlchemy; normalize inputs.

---

### Epic B — Models API (Read‑Only)

Scope
- Add `GET /v1/models` and `GET /v1/models/{id}`.

Tasks
- Implement `services/api/routes/models.py` with list/get endpoints (list returns enabled models only; no query filter in M3).
- Add Pydantic schemas in `services/api/schemas/models.py` (`ModelSummary`, `ModelDescriptor`, `ModelListResponse`).
- Mount in `services/api/routes/__init__.py`.
- Export OpenAPI and update `docs/openapi/openapi.v1.json`.

Acceptance
- `GET /v1/models` returns installed+enabled entries (no `enabled` query parameter in M3).
- `GET /v1/models/{id}` returns full descriptor or 404.
- Tests: `tests/test_m3_models_api.py` covers both endpoints and shapes.

---

### Epic C — CLI Skeleton & Registry Client

Scope
- Initialize Typer‑based CLI package and baseline commands that read registry.

Tasks
- Create `tools/dreamforge_cli/main.py` and package `__init__.py`.
- Commands: `model list`, `model get <id>` with `--output json|table` (default json).
- Config: `DF_API_BASE` (for future), DB direct access via `modules.persistence.db` for MVP.
- Wire entrypoint via `python -m tools.dreamforge_cli` and Makefile wrappers.

Acceptance
- `uv run python -m tools.dreamforge_cli model list` prints JSON; exit codes sane.

---

### Epic D — Unified Downloader Core

Scope
- Build the source‑agnostic downloader pipeline and deterministic install layout.

Tasks
- Define ref grammar: `hf:<repo>[@<rev>][#<file>]`, `civitai:<id|slug>[@<version>]`.
- Implement core steps: `resolve(ref) → descriptor`, `fetch(descriptor) → artifacts`, `verify(files) → checksums` (export as reusable function), `normalize → install dir`, `write model.json`, `upsert registry`.
- Implement idempotency: if target dir exists and checksums match, skip download; ensure registry upsert idempotent.
- Compute and record SHA256 for all files; populate `files_json`. Always compute locally; compare to remote hashes only when trivially available.
- Ensure atomic writes: download to temp dir, verify, then move into place. No resume/multi-connection logic in M3.

Acceptance
- Dry‑run shows planned install path; repeat invocation is a no‑op.
- Unit tests with stubbed adapters and small fixture files.

Risks/Mitigations
- Large files → stream to disk, show progress; configurable temp dir.
- Interrupted downloads → resume or clean temp dir; fail safely.

---

### Epic E — Adapters: Hugging Face

Scope
- Support `hf:` refs with optional `@rev` and `#file`.

Tasks
- Auth via `HF_TOKEN` when required; respect license gating (error with actionable messaging).
- Resolve refs to concrete download URLs and metadata (repo id, revision, filename).
- Download with progress; verify SHA256 (from `.safetensors` metadata or separate SHA files when available; otherwise compute locally and store).
- Map to descriptor fields (`source_uri`, `version`, `checkpoint_hash` when derivable).

Acceptance
- `dreamforge model download hf:<repo>#<file>` installs and registers; `verify` passes.

Risks/Mitigations
- Model card variability → allow manual `--name`, `--version` overrides.

---

### Epic F — Adapters: CivitAI

Scope
- Support `civitai:` refs with optional `@version`.

Tasks
- Auth via `CIVITAI_TOKEN` as required.
- Resolve model/version to file URL and metadata (hash, size, filename).
- Download, verify, install; construct descriptor with provenance.

Acceptance
- `dreamforge model download civitai:<id|slug>@<ver>` registers and verifies.

Risks/Mitigations
- Slug changes and API variance → robust resolver with clear errors.

---

### Epic G — Verify Command (Thin Wrapper)

Scope
- Validate on‑disk files against recorded checksums and update registry.

Tasks
- `dreamforge model verify <model_id|ref>` delegates to the downloader’s verification function; marks `installed=true` only when all files present and matching.
- Report discrepancies; support `--fix-enabled` to toggle enabled state based on verification. Avoid duplicate verification implementations.

Acceptance
- Corrupt/missing file detection; exit code non‑zero on mismatch.

---

### Epic H — Job Contract & Worker Integration

Scope
- Allow selecting a model via `model_id` and use it in generation.

Tasks
- Extend `services/api/schemas/jobs.py::JobCreateRequest` with optional `model_id` (UUID).
- Persist `model_id` in `params_json` within `create_job`.
- Worker: resolve model before running; ensure `installed && enabled && local_path` present; else fail with `invalid_model` error envelope. Retain `DF_GENERATE_MODEL_PATH` as a developer override (last resort) for local smoke.
- Fallback: if `model_id` absent, select default installed+enabled SDXL checkpoint.

Acceptance
- Tests: create job with `model_id` and confirm worker picks `local_path` (fake runner).

---

### Epic I — Docs, DX, and OpenAPI

Scope
- Update docs, Makefile, and environment examples.

Tasks
- Update `.env.example`: add `DF_MODELS_ROOT`, `HF_TOKEN`, `CIVITAI_TOKEN`.
- Makefile: `model-download`, `model-verify`, `model-list`, `model-get` invocations via `uv`.
- Regenerate `docs/openapi/openapi.v1.json`; ensure models endpoints and `model_id` are present.
- Align Masters 10 milestone mapping to M3 (note in doc change log).

Acceptance
- Quickstart section enables a full demo from download → list → job → artifacts.

---

## 5) Detailed Task Breakdown (Checklist)

- [ ] Repos: list/get/upsert/mark helpers for `Model` (A)
- [ ] Models API routes + schemas + router wiring (B)
- [ ] OpenAPI export updated; spec contains `/models*` (B/I)
- [ ] CLI skeleton with `model list/get` (C)
- [ ] Downloader core: pipeline, idempotency, atomic move, checksums (D)
- [ ] Adapter HF: resolve+download+verify (E)
- [ ] Adapter CivitAI: resolve+download+verify (F)
- [ ] CLI `model verify` (G)
- [ ] Job schema: `model_id`; API persists; worker resolves (H)
- [ ] Compose/Env: `DF_MODELS_ROOT` docs; tokens in `.env.example` (I)
- [ ] Tests: repos, API, CLI (mocked), worker selection (H)
- [ ] Docs: usage and demo flow (I)

---

## 6) Testing Strategy

Unit
- Repository helpers: upsert semantics, uniqueness, filters.
- CLI parser and output formatting; downloader steps with stubbed adapters.

Integration
- Models API list/get against SQLite fallback (in CI) and Postgres locally.
- CLI download (network mocked) → registry upsert; `verify` detects tampering.

E2E (dev, Compose)
- Configure `DF_MODELS_ROOT` to host mount; run `dreamforge model download` (HF with a small test artifact) → `GET /v1/models` shows the entry.
- Create a job with `model_id` and `DF_FAKE_RUNNER=1`; verify worker selected registry path and produced artifact.

Contract
- OpenAPI diff in CI; schemas for models endpoints and `model_id` in JobCreate.

---

## 7) Acceptance Demo Script

1) `uv run python -m tools.dreamforge_cli model download hf:<repo>#<file>`
2) `uv run python -m tools.dreamforge_cli model list | jq` → capture an `id`.
3) `curl -X POST /v1/jobs -d '{"type":"generate","prompt":"...","width":256,"height":256,"model_id":"<id>"}'` with `DF_FAKE_RUNNER=1`.
4) Poll `/v1/jobs/{id}` to `succeeded`; list artifacts; open presigned URL.
5) Verify `docs/openapi/openapi.v1.json` contains `/models`.

---

## 8) Risks & Mitigations

- Network and size: large downloads can fail or be slow → stream to disk, resume or cleanly abort; document minimum disk space; allow `--concurrency 1`.
- Auth/Gating: tokens required; license terms vary → fail with clear remediation, never embed tokens in descriptors.
- Path collisions: normalize `name` and `version` and check for occupied paths; idempotent design.
- VRAM/Compatibility: selected model may be too heavy for hardware → surface errors early; document supported GPU classes for SDXL in dev.
- Schema drift: keep DB and descriptor synchronized; include `schema_version` in descriptor and DB.

---

## 9) Timeline (Target ~1–1.5 weeks)

- Day 1–2: Epics A–B (repos, Models API), OpenAPI, tests.
- Day 3: Epic C (CLI skeleton) and D (downloader core API shape, temp dir, hashing).
- Day 4: Epic E (HF adapter) with verify; smoke via tiny HF asset.
- Day 5: Epic F (CivitAI adapter) happy path; Epic G (`verify`).
- Day 6: Epic H (job `model_id` plumbing) + tests; Epic I docs/Makefile/env.
- Day 7: Stabilization, E2E demo, polish errors, CI green.

---

## 10) Deliverables

- Code: new API routes (`services/api/routes/models.py`), schemas (`services/api/schemas/models.py`), repo helpers, CLI package (`tools/dreamforge_cli/*`), downloader core and adapters.
- Spec: updated `docs/openapi/openapi.v1.json`.
- Docs: this plan; Quickstart updates; `.env.example` additions; Makefile targets.
- Tests: `tests/test_m3_models_api.py`, CLI tests, worker selection test.

---

## 11) Appendix

Descriptor example (`model.json` and DB mirror):
```json
{
  "id": "a7a1e7d4-...",
  "name": "epicrealism-xl",
  "kind": "sdxl-checkpoint",
  "version": "2.1",
  "checkpoint_hash": "sha256:abcdef...",
  "source_uri": "hf:author/epicrealism-xl@a1b2c3#model.safetensors",
  "local_path": "/models/sdxl-checkpoint/epicrealism-xl@2.1",
  "installed": true,
  "enabled": true,
  "parameters_schema": {"type": "object", "properties": {"width": {"type": "integer"}}},
  "capabilities": ["generate"],
  "files_json": [
    {"path": "model.safetensors", "sha256": "abcdef...", "size": 123456789}
  ],
  "schema_version": 1
}
```

Normalized install path examples:
- `/models/sdxl-checkpoint/epicrealism-xl@2.1/model.safetensors`
- `/models/sdxl-checkpoint/epicrealism-xl@2.1/model.json`

Environment
- `DF_MODELS_ROOT` (install root), `HF_TOKEN`, `CIVITAI_TOKEN` for adapters.

---

Notes
- Keep implementation lean; avoid adding services or background jobs this milestone. Use CLI for mutations; API remains read‑only for models.
- Prefer small working examples during development to avoid long downloads in CI.
