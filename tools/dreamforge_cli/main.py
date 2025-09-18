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
from modules.storage import s3 as s3mod
import datetime as dt


def _iso(dtobj: dt.datetime | None) -> str | None:
    return dtobj.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z") if dtobj else None


def cmd_jobs_list(args: argparse.Namespace) -> int:
    status = args.status
    limit = int(args.limit)
    with get_session() as session:
        jobs = repos.list_jobs(session, status=status, limit=limit)
    out = [
        {
            "id": str(j.id),
            "type": j.type,
            "status": j.status,
            "created_at": _iso(j.created_at),
            "updated_at": _iso(j.updated_at),
        }
        for j in jobs
    ]
    print(json.dumps({"jobs": out}, ensure_ascii=False))
    return 0


def cmd_jobs_get(args: argparse.Namespace) -> int:
    with get_session() as session:
        job, steps = repos.get_job_with_steps(session, args.id)
        if not job:
            print(json.dumps({"error": {"code": "not_found", "message": "job not found"}}))
            return 2
        arts = repos.list_artifacts_by_job(session, job.id)
    try:
        count = int(job.params_json.get("count", 1)) if isinstance(job.params_json, dict) else 1
    except Exception:
        count = 1
    summary = {"count": max(1, min(count, 100)), "completed": len(arts)}
    payload = {
        "id": str(job.id),
        "type": job.type,
        "status": job.status,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "steps": [{"name": s.name, "status": s.status} for s in steps],
        "summary": summary,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_artifacts_list(args: argparse.Namespace) -> int:
    with get_session() as session:
        job = repos.get_job(session, args.job_id)
        if not job:
            print(json.dumps({"error": {"code": "not_found", "message": "job not found"}}))
            return 2
        arts = repos.list_artifacts_by_job(session, args.job_id)
    urls = []
    if args.presign:
        try:
            cfg = s3mod.from_env()
            expires_s = int(args.expires)
            for a in arts:
                urls.append(s3mod.presign_get(cfg, a.s3_key, expires=dt.timedelta(seconds=expires_s)))
        except Exception:
            urls = [None] * len(arts)
    else:
        urls = [None] * len(arts)

    out = []
    for i, a in enumerate(arts):
        out.append({
            "id": str(a.id),
            "format": a.format,
            "width": a.width,
            "height": a.height,
            "seed": a.seed,
            "item_index": a.item_index,
            "s3_key": a.s3_key,
            **({"url": urls[i]} if urls[i] else {}),
        })
    print(json.dumps({"artifacts": out}, ensure_ascii=False))
    return 0


def _parse_since_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            return dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return dt.datetime.fromisoformat(v)
    except Exception:
        return None


def cmd_logs_tail(args: argparse.Namespace) -> int:
    with get_session() as session:
        job = repos.get_job(session, args.job_id)
        if not job:
            print(json.dumps({"error": {"code": "not_found", "message": "job not found"}}))
            return 2
        since = _parse_since_ts(args.since_ts)
        tail = int(args.tail) if args.tail else None
        events = repos.iter_events(session, args.job_id, since_ts=since, tail=tail)
    for e in events:
        line = {
            "ts": _iso(e.ts),
            "level": e.level,
            "code": e.code,
            "message": e.payload_json.get("message") if isinstance(e.payload_json, dict) else e.code,
            "job_id": str(e.job_id),
            **({"step_id": str(e.step_id)} if e.step_id else {}),
        }
        if isinstance(e.payload_json, dict) and "item_index" in e.payload_json:
            line["item_index"] = e.payload_json.get("item_index")
        sys.stdout.write(json.dumps(line) + "\n")
    return 0


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

    # jobs
    p_jobs = sp.add_parser("jobs", help="Browse jobs")
    spj = p_jobs.add_subparsers(dest="subcmd")

    p_jl = spj.add_parser("list", help="List recent jobs")
    p_jl.add_argument("--status", choices=["queued", "running", "succeeded", "failed"], default=None)
    p_jl.add_argument("--limit", default=20, help="Number of jobs (1..200)")
    p_jl.set_defaults(func=cmd_jobs_list)

    p_jg = spj.add_parser("get", help="Get job with steps and summary")
    p_jg.add_argument("id", help="Job UUID")
    p_jg.set_defaults(func=cmd_jobs_get)

    # artifacts
    p_art = sp.add_parser("artifacts", help="Browse artifacts")
    spa2 = p_art.add_subparsers(dest="subcmd")
    p_al = spa2.add_parser("list", help="List artifacts for a job")
    p_al.add_argument("job_id", help="Job UUID")
    p_al.add_argument("--presign", action="store_true", help="Include presigned URLs (requires S3 env)")
    p_al.add_argument("--expires", default="3600", help="Presign TTL in seconds")
    p_al.set_defaults(func=cmd_artifacts_list)

    # logs
    p_logs = sp.add_parser("logs", help="Job logs")
    spl = p_logs.add_subparsers(dest="subcmd")
    p_tail = spl.add_parser("tail", help="Tail logs for a job (NDJSON)")
    p_tail.add_argument("job_id", help="Job UUID")
    p_tail.add_argument("--tail", default=None, help="Last N events")
    p_tail.add_argument("--since-ts", default=None, help="ISO timestamp (e.g., 2025-09-18T04:00:00Z)")
    p_tail.set_defaults(func=cmd_logs_tail)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not hasattr(ns, "func"):
        parser.print_help()
        return 1
    return int(ns.func(ns))


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
