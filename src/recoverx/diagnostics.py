"""Environment diagnostics (no recovery run required)."""
from __future__ import annotations

import importlib
import os
import shutil
import sys

from .config import get_settings
from .engines.engine_registry import all_capabilities
from .ml.selector import latest_model_dir

PACKAGES = ["sklearn", "pandas", "numpy", "scipy", "joblib", "streamlit", "plotly", "PIL", "pytest"]
OPTIONAL_EXES = ["mkfs.vfat", "mkfs.ext4", "mcopy", "mdel", "filefrag", "istat", "mount"]


def run_diagnostics() -> dict:
    s = get_settings().ensure()
    pkgs = {}
    for p in PACKAGES:
        try:
            m = importlib.import_module(p)
            pkgs[p] = getattr(m, "__version__", "installed")
        except ImportError:
            pkgs[p] = None
    dirs = {}
    for name, d in [("cases", s.cases_dir), ("models", s.models_dir), ("datasets", s.datasets_dir),
                    ("experiments", s.experiments_dir)]:
        dirs[name] = {"path": str(d), "writable": os.access(d, os.W_OK)}
    du = shutil.disk_usage(s.home)
    md = latest_model_dir(s.models_dir)
    exps = sorted(p.name for p in s.experiments_dir.glob("*") if (p / "experiment_config.json").exists())
    for e in exps:
        md = md or latest_model_dir(s.experiments_dir / e / "models")
    return {
        "python": sys.version.split()[0], "packages": pkgs, "engines": all_capabilities(),
        "dataset_tools": {e: shutil.which(e) for e in OPTIONAL_EXES},
        "home": str(s.home), "directories": dirs,
        "disk_free_gb": round(du.free / 1e9, 2), "disk_warning": du.free < 5e9,
        "model": str(md) if md else None,
        "datasets": sorted(p.name for p in s.datasets_dir.glob("*") if (p / "manifest.json").exists()),
        "experiments": exps,
        "can_loop_mount": os.geteuid() == 0 if hasattr(os, "geteuid") else False,
    }
