#!/usr/bin/env python3
"""Run the RecoverX benchmark.

  python scripts/run_benchmarks.py --exp workspace/experiments/exp1 all
  python scripts/run_benchmarks.py --exp ... phase1|phase2|phase3|analyze

Resumable: completed (image, method, repeat) runs are skipped on restart."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recoverx.benchmarking.analysis import analyze_experiment  # noqa: E402
from recoverx.benchmarking.experiment import Experiment  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, type=Path)
    ap.add_argument("--dataset", type=Path, default=Path("workspace/datasets/v1"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("phase", choices=["phase1", "phase2", "phase3", "analyze", "all"])
    a = ap.parse_args()
    exp = Experiment(a.exp.resolve(), a.dataset.resolve(), repeats=a.repeats)
    if a.phase in ("phase1", "all"):
        exp.phase1()
    if a.phase in ("phase2", "all"):
        exp.phase2()
    if a.phase in ("phase3", "all"):
        exp.phase3()
    if a.phase in ("analyze", "all"):
        res = analyze_experiment(a.exp.resolve())
        print(res["headline"])


if __name__ == "__main__":
    main()
