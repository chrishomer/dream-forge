# Dream Forge — Developer Quickstart (M0 Bootstrap)

This guide gets you from clone to a healthy local run using `uv` and Docker Compose.

## Prereqs
- Python 3.12+ and `pip`
- `uv` (`pip install uv`)
- Docker + Docker Compose

## Setup
- Sync deps: `make uv-sync`
- Lint/type/tests: `make lint type test`
- Export OpenAPI: `make openapi`
 - Bring up stack: `make up`
 - Verify readiness: `curl http://127.0.0.1:8001/readyz` should return `{ "status": "ready" }`
 - Quick health snapshot: `make status`

## Run (Compose)
- Start stack: `make up`
- Check API health: `curl http://127.0.0.1:8001/healthz`
- Readiness (after DB/MinIO are up): `curl http://127.0.0.1:8001/readyz`
- Worker metrics: `curl http://127.0.0.1:9010/metrics | head`
- Tail logs: `make logs`
- Stop stack: `make down`

Notes:
- API binds to `127.0.0.1:8001`.
- MinIO console is at `http://127.0.0.1:9001` with `minioadmin:minioadmin` (dev only).
- The default bucket `dreamforge` is auto-created at startup.

## Container GPU via CDI (M1)
- Ensure NVIDIA drivers and Container Toolkit are installed (`nvidia-smi`, `nvidia-ctk --version`).
- Generate CDI spec if missing: `make gpu-cdi-generate` (writes `/etc/cdi/nvidia.yaml`).
- Inspect environment: `make inspect-env` to print Docker, runtimes, CDI devices, and groups.
- The `worker` service in Compose requests GPUs via CDI devices (`driver: cdi`, `device_ids: ["nvidia.com/gpu=all"]`).
- Verify inside the container: `cd compose && docker compose exec worker nvidia-smi`.

## Migrations
- Upgrade to head: `make migrate-head`
- Create a new revision: `make migrate-rev m="add table foo"`

## Contributing
- See `CONTRIBUTING.md` and the PR template.
- Keep the OpenAPI spec in sync: run `make openapi` and commit changes.
- If you introduce a new service, external dependency, public endpoint, or schema change, write an ADR under `docs/adrs/`.

## M2 (Artifacts/Logs/Progress) Env Knobs
- `DF_PRESIGN_EXPIRES_S` — presigned URL expiry seconds (min 300, max 86400; default 3600)
- `DF_LOGS_TAIL_DEFAULT` — default NDJSON tail lines (default 500)
- `DF_LOGS_TAIL_MAX` — maximum allowed `tail` (default 2000)
- `DF_SSE_POLL_MS` — DB poll interval for SSE in milliseconds (default 500)
- `DF_SSE_HEARTBEAT_S` — SSE heartbeat seconds (default 15)

## M3 (Models) Quickstart

- Ensure `DF_MODELS_ROOT` is set (see `.env.example`). Compose mounts `${HOME}/.cache/dream-forge` to `/models` read‑only for API/Worker.
- Download a model via CLI to the host models root:
  - Hugging Face: `make model-download ref="hf:<repo>@<rev>#<file>"`
  - CivitAI (version id): `make model-download ref="civitai:<version_id>"`
  - Tokens: set `HF_TOKEN` / `CIVITAI_TOKEN` if required by the source.
- Verify the registry via API: `curl http://127.0.0.1:8001/v1/models | jq`.
- Create a job with a selected `model_id` (from the list). With `DF_FAKE_RUNNER=1` you can smoke‑test without a GPU.

CLI helpers:
- `make model-list`, `make model-get id=<UUID>`, `make model-verify id=<UUID>`.

Notes:
- In M3 the Models API is read‑only and returns installed+enabled models. Mutations happen via CLI.
- The CivitAI adapter accepts numeric version IDs in M3; richer resolution (slug/name) is planned (see `docs/future/`).

## M4 (Batch + Seeds) Quickstart

- Summary: Add `count` (1..100, default 1) to `POST /v1/jobs` to generate a batch in one job. Each item runs sequentially and receives its own runtime seed. Logs and artifacts include `item_index`; progress exposes aggregate and per‑item snapshots.

- Smoke setup (no GPU): `make up-fake` starts the stack with `DF_FAKE_RUNNER=1` and smaller defaults.

- Create a batch job (count=5):
  - `curl -sS http://127.0.0.1:8001/v1/jobs -H 'Content-Type: application/json' -d '{"type":"generate","prompt":"m4 demo","width":64,"height":64,"steps":2,"count":5}' | jq .`

- Check status summary (shows `{ count, completed }`):
  - `curl -sS http://127.0.0.1:8001/v1/jobs/$JOB | jq .summary`

- List artifacts (note `item_index` and `seed`):
  - `curl -sS http://127.0.0.1:8001/v1/jobs/$JOB/artifacts | jq .`

- Progress (aggregate and per‑item):
  - `curl -sS http://127.0.0.1:8001/v1/jobs/<job_id>/progress | jq .`
  - Stream SSE (closes when terminal): `curl -N http://127.0.0.1:8001/v1/jobs/<job_id>/progress/stream`

- Logs (NDJSON with per‑item `artifact.written`):
  - `curl -sS 'http://127.0.0.1:8001/v1/jobs/<job_id>/logs?tail=200'`

Notes:
- Seeds: When `count>1`, the worker randomizes per item even if a `seed` is provided. This keeps batches diverse; a future `seed_strategy` may make this configurable.
- Execution model: Items run sequentially in one step to keep VRAM steady and semantics simple. Real runner may reload the pipeline per item in MVP; further optimization is planned in M5/M11.
- Bounds: Server rejects `count<1` or `count>100` with `422 invalid_input`.

## FLUX.1-dev + SRPO (Opt-in Engine)

- Prefetch assets (no auto-download in worker):
  - Edit `docs/assets/flux_prefetch.json` and set the SRPO transformer `sha256`.
  - Run `make assets-prefetch MANIFEST=docs/assets/flux_prefetch.json` with `HF_TOKEN` set (gated FLUX base).
  - This registers `flux-transformer` (SRPO) and a `flux-pipeline` marker for the FLUX base in the registry.
- Compose env (worker): ensure `HUGGINGFACE_HUB_TOKEN` or `HF_TOKEN` is provided; keep `HF_HOME=/models/hf-cache`.
- Submit a job with the engine flag (default remains SDXL):
  - `ENGINE=flux-srpo python scripts/run_live_generate2_upscale.py`
  - Or via API JSON: `{ "type": "generate", ..., "engine": "flux-srpo" }`.
- Memory: the engine enables model CPU offload by default and falls back to sequential CPU offload + fewer steps on OOM.
- CLI helpers (`uv run dreamforge-cli ...`) now surface job/asset introspection:
  - `dreamforge-cli jobs list --limit 5` → recent jobs (optionally `--status running`).
  - `dreamforge-cli jobs get <job_id>` → status + summary bundle.
  - `dreamforge-cli artifacts list <job_id> [--presign --expires 900]` → per-item metadata + optional signed URLs when S3 env is configured.
  - `dreamforge-cli logs tail <job_id> [--since-ts 2025-09-18T00:00:00Z --tail 50]` → NDJSON stream of recent events.
