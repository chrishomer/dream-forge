import importlib
import os
import time
from typing import Any

import httpx
import pytest


@pytest.mark.asyncio
async def test_worker_ping_and_metrics(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Run Celery tasks eagerly to avoid needing Redis in this test
    monkeypatch.setenv("DF_CELERY_EAGER", "true")
    monkeypatch.setenv("DF_WORKER_METRICS_PORT", "9010")  # avoid collisions

    celery_mod = importlib.import_module("services.worker.celery_app")

    # Send ping as an eager task
    res = celery_mod.ping.delay()
    assert res.get(timeout=1) == {"status": "ok"}

    # Metrics endpoint should be up on the configured port
    # Allow a short delay for server to bind
    for _ in range(10):
        try:
            r = await httpx.AsyncClient().get("http://127.0.0.1:9010/metrics", timeout=1.0)
            if r.status_code == 200 and "df_worker_ping_total" in r.text:
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.05)
    else:
        pytest.fail("Worker metrics endpoint did not respond as expected")
