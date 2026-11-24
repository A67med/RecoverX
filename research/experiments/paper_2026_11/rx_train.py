"""Label derivation, CART training (phase 2) and analysis using the unmodified
RecoverX Experiment / analysis code.

usage:
  rx_train.py labels  --code C --dataset D --exp E        # derive labels.json from runs.jsonl
  rx_train.py train   --code C --dataset D --exp E        # labels + phase2 (writes models/, training_report.json)
  rx_train.py analyze --code C --dataset D --exp E        # analysis.json + per_image_results.csv
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["labels", "train", "analyze"])
    p.add_argument("--code", required=True); p.add_argument("--dataset", required=True); p.add_argument("--exp", required=True)
    a = p.parse_args()
    sys.path.insert(0, str(Path(a.code) / "src"))
    from recoverx.benchmarking.experiment import Experiment
    from recoverx.benchmarking.analysis import analyze_experiment
    exp = Experiment(Path(a.exp), Path(a.dataset))
    if a.action in ("labels", "train"):
        labels = exp.derive_labels()
        print("labels:", {k: sum(v["label"] == k for v in labels.values()) for k in ("tsk", "photorec", "combined")})
    if a.action == "train":
        rep = exp.phase2()
        print(json.dumps(rep["selected"]), rep["model_version"])
        print(rep["tree"])
    if a.action == "analyze":
        res = analyze_experiment(Path(a.exp))
        print(res["headline"])


if __name__ == "__main__":
    main()
