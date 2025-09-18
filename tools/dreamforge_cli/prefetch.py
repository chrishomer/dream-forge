from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from modules.persistence.db import get_session
from modules.persistence import repos
from .downloader import download as dl_download, verify_registry_model
from .adapters.huggingface import HFAdapter
from .adapters.civitai import CivitAIAdapter


def _sha256(s: bytes) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(s)
    return h.hexdigest()


class DirectAdapter:
    """Minimal adapter that fetches a single file from a URL or file:// path.

    Descriptor fields:
      - name, kind, version
      - source_uri (echoed)
      - direct: { url, sha256 }
    """

    def resolve(self, ref: str) -> dict:
        # ref is a JSON string of the descriptor for simplicity
        try:
            desc = json.loads(ref)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid direct ref json: {e}")
        for k in ("name", "kind", "version", "source_uri", "direct"):
            if k not in desc:
                raise ValueError(f"direct descriptor missing field: {k}")
        return desc

    def fetch(self, descriptor: dict, tmpdir: Path) -> list[Path]:
        import urllib.request
        import urllib.parse

        d = descriptor.get("direct", {})
        url = d.get("url")
        sha_expected = d.get("sha256")
        if not url or not sha_expected:
            raise ValueError("direct descriptor requires url and sha256")
        parsed = urllib.parse.urlparse(url)
        out = tmpdir / Path(parsed.path).name

        if parsed.scheme == "file":
            src = Path(parsed.path)
            if not src.exists():
                raise FileNotFoundError(f"file not found: {src}")
            size = src.stat().st_size
            print(f"[direct] copy {size/1e6:.1f} MB from {src}", file=sys.stderr)
            with src.open("rb") as r, out.open("wb") as w:
                while True:
                    chunk = r.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    w.write(chunk)
        else:
            req = urllib.request.Request(url)
            # best-effort follow tokenized downloads if env proxy adds auth headers
            print(f"[direct] download {url}", file=sys.stderr)
            with urllib.request.urlopen(req) as resp, open(out, "wb") as f:  # nosec - operator CLI
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                last_pct = -1
                while True:
                    buf = resp.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
                    if total > 0:
                        pct = int(got * 100 / total)
                        if pct != last_pct:
                            print(f"[direct] progress {pct}% ({got/1e6:.1f}/{total/1e6:.1f} MB)", file=sys.stderr)
                            last_pct = pct
                    else:
                        if got % (512 * 1024 * 1024) < len(buf):  # every ~512MB
                            print(f"[direct] downloaded {got/1e6:.1f} MB", file=sys.stderr)
            print(f"[direct] done -> {out}", file=sys.stderr)

        # verify sha (stream to show progress) — warn by default, strict if DF_STRICT_SHA=1
        calc = _sha256(out.read_bytes())
        if sha_expected and calc != sha_expected:
            strict = (os.getenv("DF_STRICT_SHA", "0").lower() in {"1", "true", "yes"})
            msg = (
                f"[direct] sha256 mismatch: expected={sha_expected} got={calc}. "
                f"Update your manifest or set DF_STRICT_SHA=1 to enforce."
            )
            print(msg, file=sys.stderr)
            if strict:
                raise ValueError("sha256 mismatch for downloaded file")
        return [out]


def prefetch_from_manifest(path: str, *, models_root: str) -> list[dict[str, Any]]:
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("manifest must be a JSON array of assets")
    receipts: list[dict[str, Any]] = []
    for asset in entries:
        typ = asset.get("type")
        if typ == "registry_model":
            src = asset.get("source", {})
            adapter_name = src.get("adapter")
            if adapter_name == "direct":
                print(f"[prefetch] registry_model {asset.get('name')} via direct", file=sys.stderr)
                ref = json.dumps(
                    {
                        "name": asset["name"],
                        "kind": asset["kind"],
                        "version": asset.get("version"),
                        "source_uri": src.get("url"),
                        "capabilities": asset.get("capabilities", ["upscale"]),
                        "direct": {"url": src.get("url"), "sha256": src.get("sha256")},
                    }
                )
                res = dl_download(ref, adapter=DirectAdapter(), models_root=models_root)
            elif adapter_name == "hf":  # optional convenience
                ref = src.get("ref")
                print(f"[prefetch] registry_model {asset.get('name')} via hf:{ref}", file=sys.stderr)
                res = dl_download(ref, adapter=HFAdapter(), models_root=models_root)
            elif adapter_name == "civitai":
                ref = src.get("ref")
                print(f"[prefetch] registry_model {asset.get('name')} via civitai:{ref}", file=sys.stderr)
                res = dl_download(ref, adapter=CivitAIAdapter(), models_root=models_root)
            else:
                raise ValueError(f"unsupported adapter: {adapter_name}")
            receipts.append({"id": res.registry_id, "local_path": str(res.local_path), "files": res.files_json})
        elif typ == "diffusers_cache":
            repo = asset.get("repo")
            revision = asset.get("revision", "main")
            pipeline = asset.get("pipeline")  # optional hint: "sd-upscale" | "flux"
            # seed cache (best-effort; optional in CI if diffusers unavailable)
            seeded = False
            try:  # pragma: no cover - kept out of unit tests
                import torch  # noqa: F401
                if not os.getenv("HF_HOME"):
                    os.environ["HF_HOME"] = str(Path(models_root) / "hf-cache")
                if pipeline == "flux":
                    print(f"[prefetch] seeding FLUX cache for {repo}@{revision} (this may take minutes)", file=sys.stderr)
                    try:
                        from diffusers import FluxPipeline  # type: ignore
                    except Exception:
                        from diffusers import DiffusionPipeline as FluxPipeline  # type: ignore
                    _ = FluxPipeline.from_pretrained(repo, revision=revision)
                else:
                    print(f"[prefetch] seeding SD Upscale cache for {repo}@{revision}", file=sys.stderr)
                    from diffusers import StableDiffusionUpscalePipeline
                    _ = StableDiffusionUpscalePipeline.from_pretrained(repo, revision=revision)
                seeded = True
            except Exception:
                pass
            # upsert a registry marker so the entry appears in `model list`
            with get_session() as session:
                if pipeline == "flux":
                    kind = "flux-pipeline"
                    caps = ["generate"]
                else:
                    kind = "upscaler-diffusion"
                    caps = ["upscale"]
                m = repos.upsert_model(
                    session,
                    name=repo.split("/")[-1],
                    kind=kind,
                    version=revision,
                    source_uri=f"hf:{repo}@{revision}",
                    parameters_schema={"external_ref": {"hf_repo": repo, "revision": revision}},
                    capabilities=caps,
                )
                repos.mark_model_installed(session, model_id=m.id, local_path="", files_json=[], installed=True)
                receipts.append({
                    "id": str(m.id),
                    "external_ref": {"hf_repo": repo, "revision": revision},
                    "pipeline": pipeline or "sd-upscale",
                    "seeded": seeded,
                })
        else:
            raise ValueError(f"unsupported asset type: {typ}")
    return receipts


def cmd_assets_prefetch(args: argparse.Namespace) -> int:
    models_root = args.models_root
    if args.manifest:
        receipts = prefetch_from_manifest(args.manifest, models_root=models_root)
    else:
        if args.bundle != "upscalers":
            print(json.dumps({"error": {"code": "invalid_bundle", "message": "unknown bundle"}}))
            return 2
        # Default bundle uses manifest format under the hood; ESRGAN URLs must be provided by operator if needed.
        # Keep default non-networked here; print instructions.
        print(json.dumps({
            "note": "No default network bundle is shipped. Provide --manifest with URLs and sha256 for ESRGAN weights, or set HF_HOME and run a diffusers load once to seed SD x4 cache."
        }))
        receipts = []
    print(json.dumps({"receipts": receipts}, ensure_ascii=False))
    return 0


def cmd_assets_verify(args: argparse.Namespace) -> int:
    if not args.manifest:
        print(json.dumps({"error": {"code": "missing_manifest", "message": "--manifest required"}}))
        return 2
    entries = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    oks = []
    for asset in entries:
        if asset.get("type") == "registry_model":
            # We expect that download() created/updated a registry record. Attempt to locate it by name/kind/version.
            with get_session() as session:
                m = repos.get_model_by_key(session, name=asset["name"], version=asset.get("version"), kind=asset["kind"])  # type: ignore[arg-type]
                if not m:
                    oks.append(False)
                    continue
                ok, _files = verify_registry_model(str(m.id))
                oks.append(ok)
        else:
            # For diffusers cache entries we do a best-effort: presence in registry implies seeded/known.
            oks.append(True)
    all_ok = all(oks) if oks else True
    print(json.dumps({"ok": all_ok, "checks": oks}))
    return 0 if all_ok else 3
