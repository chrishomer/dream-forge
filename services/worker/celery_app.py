from __future__ import annotations

import os
from typing import Any

from celery import Celery
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
    )

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
