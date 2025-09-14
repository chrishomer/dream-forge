#!/usr/bin/env python
"""
GPU cleanup utility for Dream Forge.

Best-effort VRAM reclamation for the current process:
- Clears PyTorch CUDA caching allocator
- Collects CUDA IPC memory
- Triggers Python GC
- Prints before/after memory snapshots per device

Run inside the worker container:
  docker compose exec -T worker python scripts/gpu_cleanup.py
"""
from __future__ import annotations

import gc
import os
import sys
from typing import Tuple


def _fmt_mb(b: int) -> str:
    return f"{b/1024/1024:.1f} MiB"


def _mem_info(device: int) -> Tuple[int, int]:
    import torch  # type: ignore

    with torch.cuda.device(device):
        free, total = torch.cuda.mem_get_info(device)
    used = total - free
    return used, total


def _print_snapshot(phase: str) -> None:
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            print(f"[{phase}] CUDA not available; nothing to do.")
            return
        n = torch.cuda.device_count()
        for d in range(n):
            name = torch.cuda.get_device_name(d)
            used, total = _mem_info(d)
            print(f"[{phase}] GPU{d} {name}: used={_fmt_mb(used)} / total={_fmt_mb(total)}")
    except Exception as e:  # pragma: no cover
        print(f"[{phase}] snapshot error: {e}")


def main() -> int:
    # Optional: target a specific device via env var
    target = os.getenv("DF_GPU_DEVICE")
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            print("CUDA not available; nothing to clear.")
            return 0
        _print_snapshot("before")

        # Switch to target device if provided
        if target is not None:
            try:
                torch.cuda.set_device(int(target))
            except Exception:
                pass

        # Clear caches (best-effort)
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception as e:
            print(f"cuda cache clear note: {e}")

        # Python GC as a backup to drop lingering references
        gc.collect()

        _print_snapshot("after")
        print("GPU cache cleared (best-effort). If memory remains high, restart worker: 'docker compose restart worker'.")
        return 0
    except ModuleNotFoundError:
        print("torch not installed in this environment.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

