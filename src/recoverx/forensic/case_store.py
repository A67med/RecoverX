"""Case directories, persisted JSON records, event log and evidence manifest.

The evidence manifest supports auditability; it does NOT by itself establish a
legally sufficient chain of custody."""
from __future__ import annotations

import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..exceptions import EvidenceIntegrityError
from ..models import utcnow
from .hashing import sha256_file
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
        tmp = self.record_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2, default=str))
        os.replace(tmp, self.record_path)

    def event(self, kind: str, **data) -> None:
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps({"t": utcnow(), "event": kind, **data}, default=str) + "\n")

    def events(self) -> list[dict]:
        p = self.dir / "events.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

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
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def open_case(case_id: str, cases_dir: Path | None = None) -> Case:
    root = cases_dir or get_settings().ensure().cases_dir
    d = root / safe_identifier(case_id)
    if not (d / "case.json").exists():
        raise FileNotFoundError(case_id)
    return Case(d)


def verify_case_evidence(case: Case, *, current_sha256: str | None = None,
                         operation: str = "operation") -> str:
    """Fail closed before analysis/recovery when the case evidence changed.

    A SHA-256 baseline recorded when the case was created is required for
    subsequent operations. Keep an audit record of failed integrity checks.
    This does not certify chain of custody; it only detects byte changes.
    """
    rec = case.load()
    baseline = rec.get("image_sha256_initial")
    try:
        digest = current_sha256 or sha256_file(Path(rec["image_path"]))
    except OSError as e:
        rec["status"] = "evidence_unavailable"
        rec["last_hash_check"] = {"at": utcnow(), "unchanged": False, "error": str(e)}
        case.save(rec)
        case.event("evidence_check_failed", operation=operation, error=str(e))
        raise EvidenceIntegrityError(f"Evidence image cannot be read: {e}") from e
    ok = bool(baseline) and digest == baseline
    rec["last_hash_check"] = {"at": utcnow(), "unchanged": ok, "sha256": digest}
    if not ok:
        rec["status"] = "evidence_changed" if baseline else "evidence_not_baselined"
        case.save(rec)
        case.event("evidence_check_failed", operation=operation, baseline_sha256=baseline,
                   current_sha256=digest)
        raise EvidenceIntegrityError(
            "Evidence SHA-256 does not match the original case hash. "
            "Recovery/analysis blocked; create a new case for changed evidence."
            if baseline else "No initial evidence hash. Create a new case with SHA-256 enabled."
        )
    case.save(rec)
    return digest


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
            "run_id": r["run_id"], "method": r["method"], "strategy_used": r["selection"]["strategy_used"],
            "selection": r["selection"], "sha256_before": r["image_sha256_before"],
            "sha256_after": r["image_sha256_after"], "source_unchanged": r["source_unchanged"],
            "engines": [{k: e[k] for k in ("engine", "run_id", "status", "tool_version", "output_dir", "error")}
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
