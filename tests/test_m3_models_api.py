from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app import app
from modules.persistence.db import get_session
from modules.persistence import repos


def _seed_model(name: str = "epicrealism-xl", version: str | None = "1.0", kind: str = "sdxl-checkpoint") -> str:
    with get_session() as session:
        m = repos.upsert_model(
            session,
            name=name,
            kind=kind,
            version=version,
            source_uri=f"hf:{name}@{version}",
            checkpoint_hash=None,
            parameters_schema={"type": "object", "properties": {}},
            capabilities=["generate"],
        )
        repos.mark_model_installed(
            session,
            model_id=m.id,
            local_path=f"/models/{kind}/{name}@{version}",
            files_json=[{"path": "model.safetensors", "sha256": "deadbeef", "size": 1}],
            installed=True,
        )
        return str(m.id)


def test_models_list_and_get_happy_path():
    client = TestClient(app)

    # Seed one installed+enabled model and one disabled model
    m_id = _seed_model()
    with get_session() as session:
        # disabled or not installed should be hidden from list
        m2 = repos.upsert_model(
            session,
            name="aux-model",
            kind="sdxl-checkpoint",
            version="0.1",
            source_uri="hf:aux/aux@0.1",
        )
        repos.mark_model_installed(session, model_id=m2.id, local_path="/models/x", files_json=[], installed=False)

    # List returns only installed+enabled entries
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert len(data["models"]) >= 1
    ids = {m["id"] for m in data["models"]}
    assert m_id in ids
    # Verify shape
    item = next(m for m in data["models"] if m["id"] == m_id)
    assert set(item.keys()) == {"id", "name", "kind", "version", "installed", "enabled", "parameters_schema"}

    # Get returns full descriptor
    r2 = client.get(f"/v1/models/{m_id}")
    assert r2.status_code == 200
    d = r2.json()
    for key in [
        "id",
        "name",
        "kind",
        "version",
        "installed",
        "enabled",
        "parameters_schema",
        "capabilities",
        "source_uri",
        "local_path",
        "files_json",
    ]:
        assert key in d
    assert d["id"] == m_id
    assert d["capabilities"] == ["generate"]

