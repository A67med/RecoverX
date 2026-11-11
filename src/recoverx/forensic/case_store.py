"""Case directories, persisted JSON records, event log and evidence manifest.

The evidence manifest supports auditability; it does NOT by itself establish a
legally sufficient chain of custody."""
from __future__ import annotations

import json
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..models import utcnow
from .hashing import sha256_file
from .storage import atomic_json
from .image_validator import safe_identifier, validate_image


def new_case_id() -> str:
    return datetime.now(timezone.utc).strftime("C%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


class Case:
    def __init__(self, case_dir: Path):
        self.dir = case_dir
        self.id = case_dir.name

    @property
    def record_path(self) -> Path:
        return self.dir / "case.json"

    def load(self) -> dict:
        return json.loads(self.record_path.read_text())

    def save(self, rec: dict) -> None:
        atomic_json(self.record_path, rec)

    def event(self, kind: str, **data) -> None:
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps({"t": utcnow(), "event": kind, **data}, default=str) + "\n")

    def events(self) -> list[dict]:
        p = self.dir / "events.jsonl"
        records = []
        if p.exists():
            for line in p.read_text().splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    records.append({"event": "unreadable_log_record", "warning": "Interrupted or damaged event record"})
        return records

    def runs_dir(self) -> Path:
        return self.dir / "runs"


def create_case(image: str | Path, *, notes: str = "", examiner: str = "", label: str = "",
                cases_dir: Path | None = None, compute_hash: bool = True) -> tuple[Case, dict]:
    img = validate_image(image)
    root = (cases_dir or get_settings().ensure().cases_dir)
    cid = safe_identifier(new_case_id())
    d = root / cid
    d.mkdir(parents=True)
    case = Case(d)
    rec = {
        "case_id": cid, "created_at": utcnow(), "label": label[:200], "notes": notes[:5000],
        "examiner": examiner[:200], "image_path": str(img), "image_size": img.stat().st_size,
        "image_sha256_initial": sha256_file(img) if compute_hash else None,
        "status": "validated", "runs": [],
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
    }
    case.save(rec)
    case.event("case_created", image=str(img), sha256=rec["image_sha256_initial"])
    return case, rec


def list_cases(cases_dir: Path | None = None) -> list[dict]:
    root = cases_dir or get_settings().ensure().cases_dir
    out = []
    for p in sorted(root.glob("*/case.json"), reverse=True):
        try:
            if p.parent.is_symlink() or p.is_symlink():
                continue
            record = json.loads(p.read_text())
            if not isinstance(record, dict) or record.get("case_id") != p.parent.name:
                continue
            out.append(record)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def open_case(case_id: str, cases_dir: Path | None = None) -> Case:
    root = cases_dir or get_settings().ensure().cases_dir
    root = root.resolve()
    d = root / safe_identifier(case_id)
    if d.is_symlink() or d.resolve().parent != root:
        raise ValueError("Case directory must not escape the case root")
    if (d / "case.json").is_symlink():
        raise ValueError("Case record must not be a symbolic link")
    if not (d / "case.json").exists():
        raise FileNotFoundError(case_id)
    return Case(d)


def build_manifest(case: Case) -> dict:
    rec = case.load()
    runs = rec.get("runs", [])
    return {
        "manifest_version": "1",
        "disclaimer": "Supports auditability; does not by itself establish chain of custody or legal admissibility.",
        "case_id": rec["case_id"], "generated_at": utcnow(),
        "source": {"path": rec["image_path"], "size": rec["image_size"],
                   "sha256_initial": rec["image_sha256_initial"]},
        "runs": [{
            "run_id": r["run_id"], "method": r["method"], "status": r["status"],
            "started_at": r["started_at"], "finished_at": r["finished_at"],
            "warnings": r.get("warnings", []), "error": r.get("error"), "settings": r.get("settings", {}), "strategy_used": r["selection"]["strategy_used"],
            "selection": r["selection"], "features": r.get("features"), "sha256_before": r["image_sha256_before"],
            "sha256_after": r["image_sha256_after"], "source_unchanged": r["source_unchanged"],
            "engines": [{"warnings": e.get("warnings", []), **{k: e[k] for k in ("engine", "run_id", "status", "tool_version", "output_dir", "error")}}
                        | {"commands": [{"args": c["args"], "returncode": c["returncode"],
                                         "started_at": c["started_at"], "elapsed_s": c["elapsed_s"]}
                                        for c in e["commands"]]}
                        for e in r["engine_runs"]],
            "results": [{k: f[k] for k in ("recovery_id", "engine", "relative_path", "size", "sha256",
                                           "integrity_state", "ground_truth_id", "duplicate_group")}
                        for e in r["engine_runs"] for f in e["files"]],
        } for r in runs],
        "events": case.events(),
    }
