from __future__ import annotations

import json
import subprocess

from modules.persistence.db import get_session
from modules.persistence import repos


def _seed_cli_model() -> str:
    with get_session() as session:
        m = repos.upsert_model(
            session,
            name="cli-epic",
            kind="sdxl-checkpoint",
            version="1.0",
            source_uri="hf:cli/epic@1.0",
        )
        repos.mark_model_installed(session, model_id=m.id, local_path="/models/sdxl-checkpoint/cli-epic@1.0", files_json=[], installed=True)
        return str(m.id)


def test_cli_model_list_and_get():
    mid = _seed_cli_model()
    # Note: PYTHONPATH is set in test_openapi_export; subprocess inherits env
    out = subprocess.check_output(["uv", "run", "python", "-m", "tools.dreamforge_cli", "model", "list"]).decode()
    data = json.loads(out)
    assert "models" in data and any(m["id"] == mid for m in data["models"])

    out2 = subprocess.check_output(["uv", "run", "python", "-m", "tools.dreamforge_cli", "model", "get", mid]).decode()
    d = json.loads(out2)
    assert d["id"] == mid and d["name"] == "cli-epic"

