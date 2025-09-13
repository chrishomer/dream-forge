.PHONY: uv-sync lint fmt type test openapi up down logs migrate-head migrate-rev run-api run-worker status inspect-env gpu-cdi-generate gpu-cdi-list

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

up:
	cd compose && docker compose up -d

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
