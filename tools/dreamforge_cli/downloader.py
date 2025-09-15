from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

from modules.persistence.db import get_session
from modules.persistence import repos


class FileEntry(TypedDict):
    path: str
    sha256: str
    size: int


class Adapter(Protocol):
    def resolve(self, ref: str) -> dict:  # descriptor fields: name, kind, version, source_uri, files
        ...

    def fetch(self, descriptor: dict, tmpdir: Path) -> list[Path]:
        ...


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_install_root(models_root: Path, *, kind: str, name: str, version: str | None) -> Path:
    safe_name = name.replace("/", "-")
    ver = version or "unknown"
    return models_root / kind / f"{safe_name}@{ver}"


def _atomic_install(tmpdir: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # If target exists, remove it then move into place to honor idempotency decisions made by caller
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(tmpdir), str(target))


def _write_descriptor(target: Path, descriptor: dict, files: list[FileEntry]) -> None:
    payload = {
        "schema_version": 1,
        **descriptor,
        "files_json": files,
        "local_path": str(target),
    }
    (target / "model.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class DownloadResult:
    local_path: Path
    files_json: list[FileEntry]
    registry_id: str


def download(ref: str, *, adapter: Adapter, models_root: str) -> DownloadResult:
    """Resolve → fetch → verify → install → upsert registry.

    This is source-agnostic; tests can pass a dummy adapter. In production adapters
    will implement network fetching.
    """
    desc = adapter.resolve(ref)
    required = ["name", "kind", "version"]
    for k in required:
        if k not in desc:
            raise ValueError(f"descriptor missing required field: {k}")

    # Prepare temp workspace
    tmp = Path(tempfile.mkdtemp(prefix="df-dl-"))
    try:
        paths = adapter.fetch(desc, tmp)
        files: list[FileEntry] = []
        for p in paths:
            rel = p.name  # ensure file is directly under tmp
            sha = _sha256_file(p)
            files.append({"path": rel, "sha256": sha, "size": p.stat().st_size})

        target = _normalize_install_root(Path(models_root), kind=desc["kind"], name=desc["name"], version=desc.get("version"))
        # Idempotency: if target exists and files match, short-circuit install but ensure registry is upserted/updated
        if target.exists():
            # Compare file list shallowly by name and hash where possible
            existing = []
            meta = target / "model.json"
            if meta.exists():
                try:
                    j = json.loads(meta.read_text(encoding="utf-8"))
                    existing = j.get("files_json", [])
                except Exception:
                    existing = []
            same = existing and all(any(e.get("path") == f["path"] and e.get("sha256") == f["sha256"] for e in existing) for f in files)
            if not same:
                # replace
                tmp_target = target.parent / (target.name + ".new")
                if tmp_target.exists():
                    shutil.rmtree(tmp_target)
                shutil.copytree(tmp, tmp_target)
                _atomic_install(tmp_target, target)
        else:
            _atomic_install(tmp, target)
            # tmp moved; prevent cleanup block from removing target
            tmp = target

        # Write descriptor and upsert registry
        desc_out = {
            "id": desc.get("id"),
            "name": desc["name"],
            "kind": desc["kind"],
            "version": desc.get("version"),
            "checkpoint_hash": desc.get("checkpoint_hash"),
            "source_uri": desc.get("source_uri"),
            "parameters_schema": desc.get("parameters_schema", {}),
            "capabilities": desc.get("capabilities", ["generate"]),
        }
        _write_descriptor(target, desc_out, files)

        with get_session() as session:
            m = repos.upsert_model(
                session,
                name=desc_out["name"],
                kind=desc_out["kind"],
                version=desc_out["version"],
                source_uri=desc_out.get("source_uri"),
                checkpoint_hash=desc_out.get("checkpoint_hash"),
                parameters_schema=desc_out.get("parameters_schema") or {},
                capabilities=desc_out.get("capabilities") or ["generate"],
            )
            repos.mark_model_installed(session, model_id=m.id, local_path=str(target), files_json=files, installed=True)
            reg_id = str(m.id)

        return DownloadResult(local_path=target, files_json=files, registry_id=reg_id)
    finally:
        # Best-effort cleanup if tmp still exists and wasn't moved
        try:
            if tmp.exists() and tmp.is_dir() and "df-dl-" in tmp.name:
                shutil.rmtree(tmp)
        except Exception:
            pass

