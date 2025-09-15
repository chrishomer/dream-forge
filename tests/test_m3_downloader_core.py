from __future__ import annotations

import io
import os
from pathlib import Path

from tools.dreamforge_cli import downloader as dl
from modules.persistence.db import get_session
from modules.persistence import repos


class DummyAdapter:
    def __init__(self, src_bytes: bytes, name: str = "dummy-model", kind: str = "sdxl-checkpoint", version: str = "0.0") -> None:
        self._data = src_bytes
        self._name = name
        self._kind = kind
        self._version = version

    def resolve(self, ref: str) -> dict:  # noqa: ARG002
        return {
            "name": self._name,
            "kind": self._kind,
            "version": self._version,
            "source_uri": f"dummy:{self._name}@{self._version}",
        }

    def fetch(self, descriptor: dict, tmpdir: Path) -> list[Path]:  # noqa: ARG002
        p = tmpdir / "model.safetensors"
        p.write_bytes(self._data)
        return [p]


def test_downloader_core_installs_and_upserts(tmp_path):
    adapter = DummyAdapter(b"hello-world")
    models_root = tmp_path / "models"
    res = dl.download("dummy:ref", adapter=adapter, models_root=str(models_root))

    # Files installed under normalized path
    assert res.local_path.exists()
    assert (res.local_path / "model.safetensors").exists()
    assert (res.local_path / "model.json").exists()
    # Registry upserted and marked installed
    with get_session() as session:
        m = repos.get_model(session, res.registry_id)
        assert m is not None and m.installed == 1 and m.local_path == str(res.local_path)

