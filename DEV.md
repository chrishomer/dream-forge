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
