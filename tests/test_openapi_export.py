import json
from pathlib import Path

import pytest
import subprocess
import os


@pytest.mark.parametrize("out", ["docs/openapi/openapi.v1.json"]) 
def test_export_openapi(out: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure PYTHONPATH includes repo root
    env = os.environ.copy()
    env["PYTHONPATH"] = "." + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.check_call(["uv", "run", "python", "scripts/export_openapi.py", "--out", out], env=env)
    p = Path(out)
    assert p.exists() and p.stat().st_size > 100
    data = json.loads(p.read_text())
    assert "/v1/" in data.get("paths", {})

