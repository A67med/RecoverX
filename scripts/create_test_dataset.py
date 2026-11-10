#!/usr/bin/env python3
"""Generate the controlled ground-truth corpus (needs root for ext4 loop mounts,
plus mtools, dosfstools, e2fsprogs, sleuthkit).

  sudo python3 scripts/create_test_dataset.py --out workspace/datasets/v1
  python3 scripts/create_test_dataset.py --out workspace/datasets/v1 --validate-only"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recoverx.datasets.generator import FILESYSTEMS, SCENARIOS, generate_dataset, validate_dataset  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, default=Path("workspace/datasets/v1"))
ap.add_argument("--seeds", type=int, default=8, help="seeds 0-4 train, 5 val, 6-7 test")
ap.add_argument("--fs", nargs="*", default=list(FILESYSTEMS))
ap.add_argument("--validate-only", action="store_true")
a = ap.parse_args()
if not a.validate_only:
    if "ext4" in a.fs and os.geteuid() != 0:
        sys.exit("ext4 images need root (loop mount). Re-run with sudo or use --fs fat16 fat32")
    if (a.out / "manifest.json").exists():
        sys.exit(f"{a.out} already contains a dataset; choose a new --out (datasets are never overwritten)")
    generate_dataset(a.out, seeds=range(a.seeds), filesystems=a.fs, scenarios=SCENARIOS)
problems = validate_dataset(a.out)
print("VALID" if not problems else "\n".join(problems))
sys.exit(1 if problems else 0)
