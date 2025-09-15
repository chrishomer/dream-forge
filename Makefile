.PHONY: uv-sync lint fmt type test openapi up up-fake down logs migrate-head migrate-rev run-api run-worker status inspect-env gpu-cdi-generate gpu-cdi-list e2e-m1 e2e-m4 bucket bucket-ls

API_BASE?=http://localhost:8001/v1
E2E_TIMEOUT_S?=480

uv-sync:
	uv sync

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

type:
	uv run mypy services modules tools

test:
	uv run pytest -q

openapi:
	PYTHONPATH=. uv run python scripts/export_openapi.py --out docs/openapi/openapi.v1.json

# M3 CLI helpers
model-download:
	uv run python -m tools.dreamforge_cli model download $(ref) --models-root $${DF_MODELS_ROOT:-$$HOME/.cache/dream-forge}

model-verify:
	uv run python -m tools.dreamforge_cli model verify $(id)

model-list:
	uv run python -m tools.dreamforge_cli model list | jq .

model-get:
	uv run python -m tools.dreamforge_cli model get $(id) | jq .

up:
	cd compose && docker compose up -d --build

up-fake:
	cd compose && docker compose -f docker-compose.yml -f docker-compose.fake.yml up -d --build

down:
	cd compose && docker compose down -v

logs:
	cd compose && docker compose logs -f --tail=200 api worker

migrate-head:
	uv run alembic upgrade head

migrate-rev:
	uv run alembic revision --autogenerate -m "$(m)"

run-api:
	PYTHONPATH=. uv run uvicorn services.api.app:app --host 127.0.0.1 --port 8001 --reload

run-worker:
	uv run celery -A services.worker.celery_app.app worker -Q gpu.default -l info

status:
	bash scripts/status.sh

inspect-env:
	bash scripts/inspect_env.sh

gpu-cdi-generate:
	bash scripts/gpu_cdi_generate.sh

gpu-cdi-list:
	command -v nvidia-ctk >/dev/null 2>&1 && nvidia-ctk cdi list || echo "nvidia-ctk not found"

gpu-free:
	cd compose && docker compose exec -T worker python scripts/gpu_cleanup.py || true

e2e-m1:
	API_BASE=$(API_BASE) E2E_TIMEOUT_S=$(E2E_TIMEOUT_S) uv run python scripts/e2e_m1.py

e2e-m4:
	uv run python scripts/validate_m4.py

bucket:
	cd compose && docker compose run --rm minio-create-bucket

bucket-ls:
	cd compose && docker compose run --rm minio-create-bucket sh -lc 'mc alias set local http://minio:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD >/dev/null 2>&1 || true; mc ls -r local/dreamforge || true'
