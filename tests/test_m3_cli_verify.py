from __future__ import annotations

from tools.dreamforge_cli.downloader import verify_registry_model
from modules.persistence.db import get_session
from modules.persistence import repos


def _seed_model_installed() -> str:
    with get_session() as session:
        m = repos.upsert_model(session, name="verify-model", kind="sdxl-checkpoint", version="1.0", source_uri="dummy:verify")
        # point to an empty local path with matching files_json (empty)
        repos.mark_model_installed(session, model_id=m.id, local_path="/tmp", files_json=[], installed=True)
        return str(m.id)


def test_verify_registry_model_trivial_ok():
    mid = _seed_model_installed()
    ok, files = verify_registry_model(mid)
    assert ok is True
    assert files == []

