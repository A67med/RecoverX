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
from recoverx.config import get_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--exp", type=Path, required=True)
ap.add_argument("--dataset", type=Path, default=Path("workspace/datasets/v1"))
ap.add_argument("--install-only", action="store_true", help="copy the experiment's existing model")
a = ap.parse_args()
if not a.install_only:
    exp = Experiment(a.exp.resolve(), a.dataset.resolve())
    exp.phase2()
import json  # noqa: E402
rep = json.loads((a.exp / "training_report.json").read_text())
src = Path(rep["model_dir"])
if not src.is_dir():
    # Archived experiment reports can contain a workstation-specific absolute
    # path. Resolve the model relative to the selected experiment instead.
    src = a.exp.resolve() / "models" / src.name
if not (src / "model.joblib").is_file() or not (src / "meta.json").is_file():
    sys.exit(f"Model not found at {src}. For the supplied archive use: python3 scripts/install_bundled_model.py")
dst = get_settings().ensure().models_dir / src.name
if not dst.exists():
    shutil.copytree(src, dst)
print(f"active model: {dst}")
