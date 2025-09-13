from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.api.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAPI spec from the FastAPI app")
    parser.add_argument("--out", default="docs/openapi/openapi.v1.json", help="Output path for JSON spec")
    args = parser.parse_args()

    spec = app.openapi()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

