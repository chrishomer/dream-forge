import httpx
import pytest

from services.api.app import app


@pytest.mark.asyncio
async def test_healthz_and_readyz_and_metrics() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

        # Readiness should succeed by default (no strict checks configured)
        r2 = await client.get("/readyz")
        assert r2.status_code == 200
        assert r2.json().get("status") == "ready"

        r3 = await client.get("/metrics")
        assert r3.status_code == 200
        body = r3.text
        assert "df_api_healthz_hits" in body

