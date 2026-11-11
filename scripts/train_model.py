#!/usr/bin/env python3
"""Train CART from an experiment's phase-1 labels and install it as the
application's active model.

  python3 scripts/train_model.py --exp workspace/experiments/exp1"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recoverx.benchmarking.experiment import Experiment  # noqa: E402
from recoverx.ml.selector import CartSelector
from recoverx.config import get_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--exp", type=Path, required=True)
ap.add_argument("--dataset", type=Path, default=Path("workspace/datasets/v1"))
ap.add_argument("--install-only", action="store_true", help="copy the experiment's existing model")
a = ap.parse_args()
exp = Experiment(a.exp.resolve(), a.dataset.resolve())
if not a.install_only:
    exp.phase2()
import json  # noqa: E402
rep = json.loads((a.exp / "training_report.json").read_text())
src = Path(rep["model_dir"])
if not src.exists():
    src = exp.dir / "models" / rep["model_version"]
CartSelector.load(src)
dst = get_settings().ensure().models_dir / src.name
if not dst.exists():
    dst.mkdir()
    for name in ("model.json", "meta.json"):
        shutil.copy2(src / name, dst / name)
print(f"active model: {dst}")
