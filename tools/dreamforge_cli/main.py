from __future__ import annotations

import argparse
import json
import sys

from modules.persistence.db import get_session
from modules.persistence import repos


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

