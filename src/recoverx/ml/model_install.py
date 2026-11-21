"""Opt-in installation of a trusted model bundled with this source archive.

The included joblib file is a Python pickle: never load models downloaded from
unknown sources. Only the known repository-managed experiment model is used.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..config import PROJECT_ROOT, get_settings
from ..exceptions import ModelError
from .features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION


def bundled_model_dir() -> Path | None:
    root = PROJECT_ROOT / "results" / "exp1" / "models"
    dirs = sorted(p for p in root.glob("cart-*") if (p / "meta.json").is_file() and (p / "model.joblib").is_file())
    return dirs[-1] if dirs else None


def install_bundled_model() -> Path:
    """Install a local, pre-trained CART model without requiring old absolute paths."""
    source = bundled_model_dir()
    if source is None:
        raise ModelError("No bundled model found in results/exp1/models")
    meta = json.loads((source / "meta.json").read_text())
    if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != FEATURE_NAMES:
        raise ModelError("Bundled model metadata is incompatible with this version")
    # Validate the exact, repository-bundled model before saving it as active.
    from .selector import CartSelector
    CartSelector.load(source)
    target = get_settings().ensure().models_dir / source.name
    if not target.exists():
        shutil.copytree(source, target)
    else:
        CartSelector.load(target)
    return target
