#!/usr/bin/env python3
"""Install the locally evaluated JSON model without reading legacy pickle files."""
import argparse
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recoverx.config import get_settings
from recoverx.ml.selector import CartSelector


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",type=Path,default=Path("workspace/audits/modernization/evaluation.json"))
    args=parser.parse_args()
    report=json.loads(args.report.read_text())
    source=Path(report["model_dir"])
    CartSelector.load(source)
    dest=get_settings().ensure().models_dir/source.name
    if not dest.exists():
        dest.mkdir()
        for name in ("model.json","meta.json"):
            shutil.copy2(source/name,dest/name)
    CartSelector.load(dest)
    print(f"Installed JSON CART model: {dest}")


if __name__=="__main__": main()
