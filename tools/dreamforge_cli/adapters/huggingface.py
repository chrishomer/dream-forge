from __future__ import annotations

import os
import urllib.request
from pathlib import Path


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
        token = os.getenv("HF_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        out = tmpdir / Path(filename).name
        with urllib.request.urlopen(req) as resp, open(out, "wb") as f:
            f.write(resp.read())
        return [out]

