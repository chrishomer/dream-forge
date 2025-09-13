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

## Migrations
- Upgrade to head: `make migrate-head`
- Create a new revision: `make migrate-rev m="add table foo"`

## Contributing
- See `CONTRIBUTING.md` and the PR template.
- Keep the OpenAPI spec in sync: run `make openapi` and commit changes.
- If you introduce a new service, external dependency, public endpoint, or schema change, write an ADR under `docs/adrs/`.

