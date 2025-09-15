from __future__ import annotations

import os
from typing import Any

from celery import Celery
from kombu import Exchange, Queue
from prometheus_client import Counter, Gauge, start_http_server


def _new_app() -> Celery:
    broker_url = os.getenv("DF_REDIS_URL", "redis://127.0.0.1:6379/0")
    backend_url = None  # We do not use a Celery result backend; app logic persists to Postgres (later)
    app = Celery("dream_forge", broker=broker_url, backend=backend_url)

    # Minimal config; tasks may run eagerly in tests if DF_CELERY_EAGER=true
    app.conf.update(
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_always_eager=os.getenv("DF_CELERY_EAGER", "false").lower() in {"1", "true", "yes"},
        worker_concurrency=int(os.getenv("DF_WORKER_CONCURRENCY", "2")),
        broker_connection_retry_on_startup=True,
        imports=("services.worker.tasks.generate", "services.worker.tasks.upscale"),
    )

    # Declare GPU queue with direct exchange and matching routing key
    gpu_exchange = Exchange("gpu.default", type="direct")
    app.conf.task_queues = (
        Queue("gpu.default", exchange=gpu_exchange, routing_key="gpu.default"),
    )
    app.conf.task_default_queue = "gpu.default"
    app.conf.task_default_exchange = "gpu.default"
    app.conf.task_default_exchange_type = "direct"
    app.conf.task_default_routing_key = "gpu.default"

    # Make this the default app so @shared_task binds here
    app.set_default()  # pragma: no cover
    # Discover tasks packages explicitly
    app.autodiscover_tasks(["services.worker.tasks"])  # pragma: no cover
    return app


app: Celery = _new_app()

_PING_COUNT = Counter("df_worker_ping_total", "Number of ping health checks")
_READY = Gauge("df_worker_ready", "Worker module import completed (1=ready)")


@app.task(name="df.ping")
def ping() -> dict[str, Any]:
    """Simple health task that returns a static payload."""
    _PING_COUNT.inc()
    return {"status": "ok"}


def _start_metrics_server() -> None:
    port = int(os.getenv("DF_WORKER_METRICS_PORT", "9009"))
    try:
        start_http_server(port)
        _READY.set(1)
    except OSError:
        # Port in use; skip (common in dev when reloaded). Keep gauge at 0.
        pass


_start_metrics_server()

# Ensure task modules are imported so Celery registers them
try:  # pragma: no cover
    import services.worker.tasks.generate  # noqa: F401
    import services.worker.tasks.upscale  # noqa: F401
except Exception:
    pass
