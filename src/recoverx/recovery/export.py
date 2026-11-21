"""Copy recovered files to the examiner's output folder with verified hashes.

Layout:  <output>/<case_id>/<run_id>/
            recovered/<engine>/<original path or carved name>
            RecoverX-report.pdf · manifest.json · inventory.csv · export.json

One copy per distinct SHA-256 (duplicates are listed, not copied twice). Every
copy is created exclusively (never overwrites) and re-hashed after writing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from ..forensic.case_store import Case, build_manifest
from ..forensic.image_validator import safe_join
from ..models import utcnow
from ..reporting.exports import csv_inventory
from .validation import validate_file

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
ENGINE_PREFERENCE = {"tsk": 0, "photorec": 1}


def safe_component(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = "unnamed"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name[:120]


def _relative_target(f: dict) -> Path:
    if f.get("engine") == "tsk" and f.get("original_name"):
        parts = [safe_component(p) for p in re.split(r"[\\/]+", f["original_name"]) if p not in ("", ".", "..")]
        if parts:
            return Path("tsk", *parts)
    return Path(f.get("engine") or "other", safe_component(f.get("recovered_name") or "recovered.bin"))


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Too many name collisions for {path.name}")


def _copy_verified(src: Path, dst: Path) -> str:
    h = hashlib.sha256()
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as fin, open(dst, "xb") as fout:
        for chunk in iter(lambda: fin.read(1024 * 1024), b""):
            fout.write(chunk)
            h.update(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    return h.hexdigest()


def plan_size(run: dict) -> int:
    seen, total = set(), 0
    for e in run.get("engine_runs", []):
        for f in e.get("files", []):
            if f["sha256"] not in seen:
                seen.add(f["sha256"])
                total += int(f.get("size") or 0)
    return total


def export_run(case: Case, run: dict, output_root: str | Path, *, pdf_bytes: bytes | None = None) -> dict:
    root = Path(output_root).expanduser().resolve()
    rec = case.load()
    evidence = Path(rec["image_path"]).resolve()
    target = root / case.id / run["run_id"]
    if target == evidence or evidence in target.parents or target in evidence.parents:
        raise OSError("Output folder overlaps the evidence image")
    needed = plan_size(run) + 32 * 2**20
    probe = root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    if shutil.disk_usage(probe).free < needed:
        raise OSError(f"Not enough free space in the output folder for {needed:,} bytes of recovered files")
    target.mkdir(parents=True, exist_ok=False)
    files_root = target / "recovered"
    candidates = [(e, f) for e in run.get("engine_runs", []) for f in e.get("files", [])]
    candidates.sort(key=lambda ef: (ENGINE_PREFERENCE.get(ef[1].get("engine"), 9), ef[1].get("recovery_id", "")))
    exported, by_hash = [], {}
    for engine, f in candidates:
        sha = f["sha256"]
        if sha in by_hash:
            by_hash[sha]["duplicates"].append({"recovery_id": f["recovery_id"], "engine": f["engine"],
                                               "recovered_name": f["recovered_name"]})
            continue
        entry = {"recovery_id": f["recovery_id"], "engine": f["engine"], "sha256": sha, "size": f["size"],
                 "original_name": f.get("original_name"), "recovered_name": f["recovered_name"],
                 "integrity_state": f.get("integrity_state"), "ground_truth_id": f.get("ground_truth_id"),
                 "duplicates": []}
        try:
            src = safe_join(engine["output_dir"], f["relative_path"])
            if src.is_symlink() or not src.is_file():
                raise OSError("source output missing or not a regular file")
            dst = _unique(files_root / _relative_target(f))
            copied = _copy_verified(src, dst)
            entry.update(exported_path=str(dst), relative_export_path=str(dst.relative_to(target)),
                         copy_verified=copied == sha, validation=validate_file(dst))
            if copied != sha:
                entry["error"] = "SHA-256 of the exported copy differs from the inventory"
        except OSError as exc:
            entry.update(exported_path=None, copy_verified=False, error=str(exc)[:300],
                         validation={"state": "invalid", "format": f.get("extension"), "reason": "not exported"})
        by_hash[sha] = entry
        exported.append(entry)
    summary = {
        "exported_at": utcnow(), "case_id": case.id, "run_id": run["run_id"], "output_dir": str(target),
        "distinct_files": len(exported), "copied_ok": sum(1 for e in exported if e.get("copy_verified")),
        "duplicates_skipped": sum(len(e["duplicates"]) for e in exported),
        "structurally_valid": sum(1 for e in exported if e["validation"]["state"] == "valid"),
        "structurally_invalid": sum(1 for e in exported if e["validation"]["state"] == "invalid"),
        "not_checked": sum(1 for e in exported if e["validation"]["state"] == "not_checked"),
        "files": exported,
        "note": "Structural validity is a plausibility check; exact recovery is proven only by matching a known original SHA-256.",
    }
    (target / "export.json").write_text(json.dumps(summary, indent=2))
    (target / "manifest.json").write_text(json.dumps(build_manifest(case), indent=2, default=str))
    rows = [{k: e.get(k) for k in ("recovery_id", "engine", "original_name", "recovered_name", "relative_export_path",
                                   "size", "sha256", "integrity_state", "copy_verified")}
            | {"validation": e["validation"]["state"], "validation_reason": e["validation"]["reason"],
               "duplicates": len(e["duplicates"])} for e in exported]
    (target / "inventory.csv").write_text(csv_inventory(rows), encoding="utf-8")
    if pdf_bytes:
        (target / "RecoverX-report.pdf").write_bytes(pdf_bytes)
    return summary
