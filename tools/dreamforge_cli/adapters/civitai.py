from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


def _parse_ref(ref: str) -> tuple[str | None, str]:
    # Support: civitai:<version_id> OR civitai:<model_id>@<version_id>
    if not ref.startswith("civitai:"):
        raise ValueError("invalid civitai ref")
    body = ref[len("civitai:"):]
    if "@" in body:
        model_id, version = body.split("@", 1)
        return model_id, version
    return None, body


def _filename_from_headers(headers) -> str | None:  # type: ignore[no-untyped-def]
    cd = headers.get("Content-Disposition")
    if not cd:
        return None
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return m.group(1)
    return None


class CivitAIAdapter:
    def resolve(self, ref: str) -> dict:
        model_id, version = _parse_ref(ref)
        # If only one part provided, treat it as version_id (most stable for downloads)
        version_id = version if model_id is not None else version
        if not version_id or not version_id.isdigit():
            raise ValueError("civitai ref must include a numeric version id: civitai:<version_id> or civitai:<model_id>@<version_id>")
        return {
            "name": f"civitai-{version_id}",
            "kind": "sdxl-checkpoint",
            "version": version_id,
            "source_uri": ref,
            "civitai": {"version_id": version_id},
        }

    def fetch(self, descriptor: dict, tmpdir: Path) -> list[Path]:
        version_id = descriptor.get("civitai", {}).get("version_id")
        url = f"https://civitai.com/api/download/models/{urllib.parse.quote(str(version_id))}"
        req = urllib.request.Request(url)
        token = os.getenv("CIVITAI_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
            filename = _filename_from_headers(resp.headers) or f"model-{version_id}.safetensors"
        out = tmpdir / filename
        out.write_bytes(data)
        return [out]

