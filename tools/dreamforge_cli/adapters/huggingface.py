from __future__ import annotations

import os
import urllib.request
from pathlib import Path
import sys


def _parse_ref(ref: str) -> tuple[str, str, str]:
    # hf:repo@rev#file
    if not ref.startswith("hf:"):
        raise ValueError("invalid hf ref")
    body = ref[3:]
    if "#" not in body or "@" not in body:
        raise ValueError("hf ref must be in the form hf:<repo>@<rev>#<file>")
    repo_rev, filename = body.split("#", 1)
    repo, rev = repo_rev.split("@", 1)
    return repo, rev, filename


class HFAdapter:
    def resolve(self, ref: str) -> dict:
        repo, rev, filename = _parse_ref(ref)
        # Derive a simple name from repo tail
        name = repo.split("/")[-1]
        return {
            "name": name,
            "kind": "sdxl-checkpoint",
            "version": rev,
            "source_uri": ref,
            "hf": {"repo": repo, "rev": rev, "filename": filename},
        }

    def fetch(self, descriptor: dict, tmpdir: Path) -> list[Path]:
        hf = descriptor.get("hf", {})
        repo = hf.get("repo")
        rev = hf.get("rev")
        filename = hf.get("filename")
        url = f"https://huggingface.co/{repo}/resolve/{rev}/{filename}"
        req = urllib.request.Request(url)
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        out = tmpdir / Path(filename).name
        print(f"[hf] download {repo}@{rev}#{filename}", file=sys.stderr)
        with urllib.request.urlopen(req) as resp, open(out, "wb") as f:
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
                        print(f"[hf] progress {pct}% ({got/1e6:.1f}/{total/1e6:.1f} MB)", file=sys.stderr)
                        last_pct = pct
                else:
                    if got % (512 * 1024 * 1024) < len(buf):
                        print(f"[hf] downloaded {got/1e6:.1f} MB", file=sys.stderr)
        print(f"[hf] done -> {out}", file=sys.stderr)
        return [out]
