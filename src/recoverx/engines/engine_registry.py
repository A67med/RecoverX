from __future__ import annotations

from .photorec_engine import PhotoRecEngine
from .sleuthkit_engine import SleuthKitEngine

ENGINES = {"tsk": SleuthKitEngine, "photorec": PhotoRecEngine}


def get_engine(name: str):
    try:
        return ENGINES[name]()
    except KeyError:
        raise ValueError(f"unknown engine {name!r}") from None


def all_capabilities() -> list[dict]:
    return [cls().capabilities() for cls in ENGINES.values()]
