from __future__ import annotations

import json
from pathlib import Path

from tools.dreamforge_cli.prefetch import prefetch_from_manifest
from tools.dreamforge_cli.downloader import verify_registry_model
from modules.persistence.db import get_session
from modules.persistence import repos


def test_prefetch_manifest_local_direct(tmp_path, monkeypatch):
    # Prepare a fake weight file and compute sha256
    src = tmp_path / "weights.bin"
    data = b"hello-real-esrgan"
    src.write_bytes(data)
    import hashlib

    h = hashlib.sha256(); h.update(data)
    sha = h.hexdigest()

    manifest = [
        {
            "type": "registry_model",
            "kind": "upscaler-gan",
            "name": "realesrgan",
            "version": "x2plus",
            "source": {"adapter": "direct", "url": f"file://{src}", "sha256": sha},
        }
    ]
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")

    receipts = prefetch_from_manifest(str(mf), models_root=str(tmp_path / "models"))
    assert len(receipts) == 1
    # Validate registry entry exists and verifies
    with get_session() as session:
        m = repos.get_model_by_key(session, name="realesrgan", version="x2plus", kind="upscaler-gan")
        assert m is not None
        ok, files = verify_registry_model(str(m.id))
        assert ok and files

