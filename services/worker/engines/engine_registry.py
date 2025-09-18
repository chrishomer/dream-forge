from __future__ import annotations

from typing import Dict

from .base import Engine


_ENGINES: Dict[str, Engine] = {}


def get_engine(name: str) -> Engine:
    key = name.lower().strip()
    if key in _ENGINES:
        return _ENGINES[key]
    if key == "flux-srpo":
        from .flux_srpo import FluxSrpoEngine  # lazy import

        inst = FluxSrpoEngine()
    else:
        raise ValueError(f"unknown engine: {name}")
    _ENGINES[key] = inst
    return inst


def shutdown_all() -> None:  # pragma: no cover - runtime cleanup
    for eng in list(_ENGINES.values()):
        try:
            eng.shutdown()
        except Exception:
            pass
    _ENGINES.clear()

