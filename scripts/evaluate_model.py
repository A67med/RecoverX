#!/usr/bin/env python3
"""Re-evaluate recorded synthetic features without disk images or legacy models."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recoverx.ml.evaluation import evaluate_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=Path("results/exp1"))
    parser.add_argument("--manifest", type=Path, default=Path("results/dataset_v1/manifest.json"))
    parser.add_argument("--out", type=Path, default=Path("workspace/audits/modernization"))
    args = parser.parse_args()
    model, report = evaluate_records(args.records, args.manifest)
    args.out.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    version = "cart-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = model.save(args.out / "models", version)
    report.update(model_dir=str(path), model_version=version)
    (args.out / "evaluation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(args.out / "evaluation.json"), "split_sizes": report["split_sizes"],
                      "held_out_accuracy": report["held_out"]["accuracy"],
                      "balanced_accuracy": report["held_out"]["balanced_accuracy"],
                      "test_eligible_rate": report["test_eligible_rate"], "model": str(path)}, indent=2))


if __name__ == "__main__":
    main()
