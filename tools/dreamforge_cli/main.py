from __future__ import annotations

import argparse
import json
import sys

import os
from modules.persistence.db import get_session
from modules.persistence import repos
from .downloader import download as dl_download, verify_registry_model
from .adapters.huggingface import HFAdapter
from .adapters.civitai import CivitAIAdapter
from .prefetch import cmd_assets_prefetch, cmd_assets_verify


def cmd_model_list(args: argparse.Namespace) -> int:
    with get_session() as session:
        models = repos.list_models(session, enabled_only=True)
    data = [
        {
            "id": str(m.id),
            "name": m.name,
            "kind": m.kind,
            "version": m.version,
            "installed": bool(m.installed),
            "enabled": bool(m.enabled),
            "parameters_schema": m.parameters_schema or {},
        }
        for m in models
    ]
    print(json.dumps({"models": data}, ensure_ascii=False))
    return 0


def cmd_model_get(args: argparse.Namespace) -> int:
    with get_session() as session:
        m = repos.get_model(session, args.id)
    if not m:
        print(json.dumps({"error": {"code": "not_found", "message": "model not found"}}), file=sys.stderr)
        return 2
    out = {
        "id": str(m.id),
        "name": m.name,
        "kind": m.kind,
        "version": m.version,
        "installed": bool(m.installed),
        "enabled": bool(m.enabled),
        "parameters_schema": m.parameters_schema or {},
        "capabilities": m.capabilities or ["generate"],
        "source_uri": m.source_uri,
        "local_path": m.local_path,
        "files_json": m.files_json or [],
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dreamforge", description="Dream Forge CLI (M3 subset)")
    sp = p.add_subparsers(dest="cmd")

    p_model = sp.add_parser("model", help="Model registry commands")
    spm = p_model.add_subparsers(dest="subcmd")

    p_list = spm.add_parser("list", help="List enabled models")
    p_list.set_defaults(func=cmd_model_list)

    p_get = spm.add_parser("get", help="Get a model descriptor")
    p_get.add_argument("id", help="Model UUID")
    p_get.set_defaults(func=cmd_model_get)

    p_dl = spm.add_parser("download", help="Download and register a model by ref (hf: or civitai:)")
    p_dl.add_argument("ref", help="Model reference, e.g., hf:repo@rev#file or civitai:<version_id>")
    p_dl.add_argument("--models-root", default=os.path.expanduser("~/.cache/dream-forge"), help="Install root directory")
    p_dl.set_defaults(func=cmd_model_download)

    p_verify = spm.add_parser("verify", help="Verify a registered model by id")
    p_verify.add_argument("id", help="Model UUID")
    p_verify.set_defaults(func=cmd_model_verify)

    # assets prefetch/verify (ops tooling)
    p_assets = sp.add_parser("assets", help="Assets utilities (prefetch/verify)")
    spa = p_assets.add_subparsers(dest="subcmd")

    p_pref = spa.add_parser("prefetch", help="Prefetch assets (bundle or manifest)")
    p_pref.add_argument("--bundle", default=None, help="Convenience bundle (e.g., 'upscalers')")
    p_pref.add_argument("--manifest", default=None, help="Path to manifest JSON for assets")
    p_pref.add_argument("--models-root", default=os.path.expanduser("~/.cache/dream-forge"), help="Install root directory")
    p_pref.set_defaults(func=cmd_assets_prefetch)

    p_av = spa.add_parser("verify", help="Verify assets from manifest")
    p_av.add_argument("--manifest", required=True, help="Path to manifest JSON for assets")
    p_av.set_defaults(func=cmd_assets_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not hasattr(ns, "func"):
        parser.print_help()
        return 1
    return int(ns.func(ns))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


def cmd_model_download(args: argparse.Namespace) -> int:
    ref = args.ref
    if ref.startswith("hf:"):
        adapter = HFAdapter()
    elif ref.startswith("civitai:"):
        adapter = CivitAIAdapter()
    else:
        print(json.dumps({"error": {"code": "invalid_ref", "message": "ref must start with hf: or civitai:"}}))
        return 2
    try:
        res = dl_download(ref, adapter=adapter, models_root=args.models_root)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": {"code": "download_failed", "message": str(exc)}}))
        return 3
    print(json.dumps({"id": res.registry_id, "local_path": str(res.local_path), "files": res.files_json}))
    return 0


def cmd_model_verify(args: argparse.Namespace) -> int:
    ok, files = verify_registry_model(args.id)
    print(json.dumps({"ok": ok, "files": files}))
    return 0 if ok else 4
