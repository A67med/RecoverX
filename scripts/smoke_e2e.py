#!/usr/bin/env python3
"""End-to-end smoke test of the Quick Recovery pipeline with the REAL installed engines.

Builds a disposable 24 MiB FAT16 image containing a JPG and a PDF, deletes both,
then runs every Quick Recovery method against it and prints a JSON summary.

* Linux: needs mkfs.vfat + mtools.  Windows: builds the image inside WSL
  (mkfs.vfat + mtools in the default distribution); recovery then uses the
  native Windows Sleuth Kit and PhotoRec through WSL — exactly like the app.
* Only files under --workdir are created. No real disk is touched.

Usage:  python scripts/smoke_e2e.py --workdir <empty folder> [--methods tsk,photorec,...]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from recoverx.datasets.generator import make_content  # noqa: E402
from recoverx.forensic.hashing import sha256_bytes  # noqa: E402


def sh(cmd: list[str]):
    if os.name == "nt":
        cmd = ["wsl.exe", "--exec", *cmd]
    subprocess.run(cmd, check=True, capture_output=True)


def to_tool_path(p: Path) -> str:
    if os.name != "nt":
        return str(p)
    out = subprocess.run(["wsl.exe", "--exec", "wslpath", "-a", "-u", str(p)], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def build_image(workdir: Path) -> tuple[Path, dict]:
    img = workdir / "usb-stick.img"
    with open(img, "xb") as f:
        f.truncate(24 * 2**20)
    sh(["/usr/sbin/mkfs.vfat" if os.name == "nt" else "mkfs.vfat", "-F", "16", "-n", "SMOKE", to_tool_path(img)])
    rng = random.Random(4040)
    files = {"holiday.jpg": make_content("jpg", 48000, rng), "invoice.pdf": make_content("pdf", 30000, rng),
             "keep.txt": make_content("txt", 5000, rng)}
    for name, data in files.items():
        (workdir / name).write_bytes(data)
        sh(["mcopy", "-i", to_tool_path(img), to_tool_path(workdir / name), f"::{name}"])
    for name in ("holiday.jpg", "invoice.pdf"):
        sh(["mdel", "-i", to_tool_path(img), f"::{name}"])
        (workdir / name).unlink()
    (workdir / "keep.txt").unlink()
    return img, {n: sha256_bytes(files[n]) for n in ("holiday.jpg", "invoice.pdf")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--methods", default="smart,tsk,photorec,combined,cart,rule")
    args = ap.parse_args()
    work = Path(args.workdir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        raise SystemExit("--workdir must be empty")
    os.environ["RECOVERX_HOME"] = str(work / "home")
    from recoverx import workflow
    from recoverx.ml.model_install import install_bundled_model
    install_bundled_model()
    img, hashes = build_image(work)
    before = sha256_bytes(img.read_bytes())
    summary = {"platform": sys.platform, "image": str(img), "image_sha256": before, "deleted_files": hashes, "runs": []}
    for method in args.methods.split(","):
        t0 = time.time()
        job = workflow.start_quick_job(source="image", image_path=str(img), method=method, authorized=True,
                                       output_dir=str(work / f"out-{method}"), known_hashes="\n".join(hashes.values()))
        job.done.wait(1800)
        snap = job.snapshot()
        run = snap.get("run") or {}
        sel = run.get("selection") or {}
        summary["runs"].append({
            "method": method, "outcome": snap["outcome"], "message": snap["message"], "seconds": round(time.time() - t0, 1),
            "status": run.get("status"), "engines_attempted": sel.get("engines_attempted"),
            "recommended": sel.get("recommended"), "selector": sel.get("model_version"),
            "exact_recovered": (run.get("metrics") or {}).get("exact_recovered"),
            "exported": [{"name": f.get("original_name") or f.get("recovered_name"), "engine": f["engine"],
                          "validation": f["validation"]["state"], "copy_verified": f["copy_verified"],
                          "matches_original": f["sha256"] in hashes.values()}
                         for f in (snap.get("export") or {}).get("files", [])],
            "engine_status": {e["engine"]: e["status"] for e in run.get("engine_runs", [])},
            "source_unchanged": run.get("source_unchanged"),
        })
    summary["image_unchanged_after_all_runs"] = sha256_bytes(img.read_bytes()) == before
    print(json.dumps(summary, indent=2))
    ok = summary["image_unchanged_after_all_runs"] and all(r["outcome"] == "success" and r["exact_recovered"] == 2
                                                          for r in summary["runs"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
