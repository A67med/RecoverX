"""End-to-end pipeline (spec §11).

method ∈ {tsk, photorec, combined, rule, cart, manual:<strategy>}
Combined policy (fixed): TSK first, then PhotoRec, sequentially, against the same
read-only image, into separate directories; outputs merged by SHA-256 without
deleting anything. Sequential execution keeps timing comparable and avoids
concurrent disk contention.

Timing boundary (spec §9/§11): total_s covers initial hash → final hash, including
analysis, feature extraction, inference, engines, inventory hashing,
ground-truth verification and deduplication. Fixed methods skip analysis unless
analyze=True; selector methods cannot skip it and are charged for it."""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from .. import STRATEGIES
from ..config import PHOTOREC_TIMEOUT, TSK_TIMEOUT, get_settings
from ..engines.engine_registry import get_engine
from ..forensic.case_store import Case
from ..forensic.filesystem_analyzer import analyze_image
from ..forensic.hashing import sha256_file
from ..forensic.image_validator import validate_image
from ..forensic.storage import atomic_json, operation_lock
from ..engines.photorec_engine import PhotoRecEngine, DEFAULT_SCRIPT
from ..ml.features import extract_features
from ..ml.selector import CartSelector, latest_model_dir, rule_select
from ..models import utcnow
from .integrity import apply_ground_truth, canonical_view, recovery_metrics

ENGINE_PLAN = {"tsk": ["tsk"], "photorec": ["photorec"], "combined": ["tsk", "photorec"]}


def _select(method: str, features: dict | None, model_dir: Path | None) -> dict:
    sel = {"method": method, "recommended": None, "strategy_used": None, "rationale": "",
           "model_version": None, "fallback": None, "inference_s": 0.0}
    if method in STRATEGIES:
        sel.update(strategy_used=method, rationale="fixed strategy")
    elif method.startswith("manual:"):
        s = method.split(":", 1)[1]
        if s not in STRATEGIES:
            raise ValueError(f"unknown manual strategy {s}")
        if features is not None:
            sel["recommended"] = rule_select(features)[0]
        sel.update(strategy_used=s, rationale="manual override by examiner")
    elif method == "rule":
        s, why = rule_select(features)
        sel.update(recommended=s, strategy_used=s, rationale=why, model_version="rule-v1")
    elif method == "cart":
        mdir = model_dir or latest_model_dir(get_settings().models_dir)
        try:
            if mdir is None:
                raise FileNotFoundError("no trained model")
            model = CartSelector.load(mdir)
            p = model.predict(features)
            sel.update(recommended=p["strategy"], strategy_used=p["strategy"], model_version=model.meta["version"],
                       rationale=" → ".join(p["decision_path"]) or "single-leaf tree",
                       inference_s=p["inference_s"], leaf_class_fractions=p["leaf_class_fractions"],
                       out_of_training_range=p["out_of_training_range"])
        except Exception as e:  # transparent fallback (spec §11)
            s, why = rule_select(features)
            sel.update(strategy_used=s, fallback=f"CART unavailable ({e}); rule-v1 used",
                       rationale=why, model_version="rule-v1")
    else:
        raise ValueError(f"unknown method {method}")
    return sel


def validate_ground_truth(gt: dict | None) -> None:
    if gt is None:
        return
    import re
    if not isinstance(gt, dict):
        raise ValueError("Ground truth must be an object with deleted/allocated lists")
    groups = []
    for kind in ("deleted", "allocated"):
        entries = gt.get(kind, [])
        if not isinstance(entries, list):
            raise ValueError(f"Ground truth {kind} must be a list")
        hashes = set()
        for entry in entries:
            if not isinstance(entry, dict) or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
                raise ValueError("Ground truth requires lowercase SHA-256 digests")
            if kind == "deleted" and not isinstance(entry.get("id"), str):
                raise ValueError("Deleted ground-truth entries require string IDs")
            hashes.add(entry["sha256"])
        groups.append(hashes)
    if groups[0] & groups[1]:
        raise ValueError("A ground-truth digest cannot be both deleted and allocated")


def run_recovery(case: Case, method: str, *, ground_truth: dict | None = None,
                 analyze: bool | None = None, model_dir: Path | None = None,
                 timeouts: dict | None = None, label: str = "",
                 cancel_event: threading.Event | None = None, progress=None,
                 conservative: bool = True) -> dict:
    """Run under a case lock. Automatic modes default to both engines.

    conservative=False is an explicit research opt-in, recorded in every run.
    It cannot override incomplete analysis or out-of-range CART predictions.
    """
    validate_ground_truth(ground_truth)
    if method not in (*STRATEGIES, "rule", "cart") and method not in [f"manual:{s}" for s in STRATEGIES]:
        raise ValueError(f"unknown method {method}")
    with operation_lock(case.dir):
        return _run_locked(case, method, ground_truth=ground_truth, analyze=analyze,
                           model_dir=model_dir, timeouts=timeouts, label=label,
                           cancel_event=cancel_event, progress=progress, conservative=conservative)


def _run_locked(case, method, *, ground_truth, analyze, model_dir, timeouts, label,
                cancel_event, progress, conservative):
    rec = case.load()
    image = Path(rec["image_path"])
    run_id = time.strftime("R%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    run_dir = case.runs_dir() / run_id
    timeouts = {"tsk": TSK_TIMEOUT, "photorec": PHOTOREC_TIMEOUT, **(timeouts or {})}
    # All production runs inspect the volume system. Research callers can opt out.
    analyze = True if analyze is None else analyze or method in ("rule", "cart") or method.startswith("manual:")
    started_at, t0 = utcnow(), time.perf_counter()
    timing, engine_runs, warnings = {}, [], []
    analysis = features = None
    before = after = None
    error, status = None, "running"
    selection = {"method": method, "recommended": None, "strategy_used": None,
                 "rationale": "Not selected", "fallback": None, "model_version": None,
                 "conservative": conservative}

    def notify(stage, **extra):
        snapshot = {"run_id": run_id, "stage": stage, "started_at": started_at,
                    "updated_at": utcnow(), "status": status,
                    "engines": [er.to_dict() for er in engine_runs], **extra}
        atomic_json(case.dir / "active_run.json", snapshot)
        case.event(stage, run_id=run_id, **extra)
        if progress:
            progress({"stage": stage, **extra})

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    notify("run_started", method=method)
    try:
        validate_image(image)
        notify("hashing_source", detail="Streaming SHA-256 before recovery")
        t = time.perf_counter()
        before = sha256_file(image)
        timing["hash_initial_s"] = time.perf_counter() - t
        if rec["image_sha256_initial"] and before != rec["image_sha256_initial"]:
            status = "blocked"
            error = "Source SHA-256 differs from case registration; no recovery tools were started"
        elif cancelled():
            status = "cancelled"
        else:
            if analyze:
                notify("analyzing", detail="Read-only partition and filesystem inspection")
                t = time.perf_counter()
                analysis = analyze_image(image, cancel_event=cancel_event)
                timing["analysis_s"] = time.perf_counter() - t
                t = time.perf_counter()
                features = extract_features(analysis)
                timing["features_s"] = time.perf_counter() - t
            selection = {**_select(method, features, model_dir), "conservative": conservative}
            automatic = method in ("rule", "cart")
            reasons = []
            if automatic and conservative:
                reasons.append("Automatic preservation policy runs both engines; recommendation is advisory")
            if automatic and analysis and analysis.status != "analysis_completed":
                reasons.append("Incomplete filesystem analysis cannot justify omitting an engine")
            if automatic and selection.get("out_of_training_range"):
                reasons.append("CART inputs outside training range: " + ", ".join(selection["out_of_training_range"]))
            if automatic and selection.get("fallback"):
                reasons.append("No usable CART model; rule-v1 advice is not evidence of equivalent recoverability")
            if reasons:
                selection["safety_override"] = "; ".join(reasons)
                selection["strategy_used"] = "combined"
            selection["reliability"] = "Advisory only; leaf frequencies are not recovery probabilities"
            notify("strategy_selected", **selection)
            offsets = [0]
            if analysis:
                offsets = list(dict.fromkeys(p.start_sector for p in analysis.partitions)) or [analysis.sector_offset]
            for name in ENGINE_PLAN[selection["strategy_used"]]:
                scopes = offsets if name == "tsk" else [0]
                for offset in scopes:
                    if cancelled():
                        status = "cancelled"
                        break
                    suffix = f"{name}-sector-{offset}" if name == "tsk" and (len(scopes) > 1 or offset) else name
                    engine = get_engine(name)
                    if name == "photorec" and analysis and (analysis.partitions or not analysis.fs_type):
                        engine = PhotoRecEngine(script=DEFAULT_SCRIPT.replace(",freespace", ""))
                        warnings.append("PhotoRec scans the whole image because a single verified filesystem scope is unavailable; allocated files may be included")
                    notify("engine_started", engine=name, sector_offset=offset,
                           detail=f"{name}: recovering; byte progress is unavailable")
                    er = engine.run(image, run_dir / suffix, sector_offset=offset,
                                    timeout=timeouts[name], cancel_event=cancel_event, run_id=f"{run_id}-{suffix}")
                    engine_runs.append(er)
                    timing[f"engine_{suffix}_s"] = er.elapsed_s
                    notify("engine_finished", engine=name, engine_status=er.status,
                           files=len(er.files), error=er.error)
                    if er.status == "cancelled":
                        status = "cancelled"
                        break
                if status == "cancelled":
                    break
            if status != "cancelled":
                status = "completed" if engine_runs and all(e.status == "completed" for e in engine_runs) else "incomplete"
    except Exception as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        notify("verifying", detail="Hashing source and classifying output digests")
        t = time.perf_counter()
        try:
            after = sha256_file(image)
        except OSError as exc:
            error = f"{error or ''}; final source verification failed: {exc}".strip("; ")
            status = "failed"
        timing["hash_final_s"] = time.perf_counter() - t

    files = [f for er in engine_runs for f in er.files]
    apply_ground_truth(files, ground_truth)
    canonical = canonical_view(files)
    unchanged = before is not None and before == after and (not rec["image_sha256_initial"] or before == rec["image_sha256_initial"])
    if not unchanged and engine_runs:
        status = "integrity_failed"
        warnings.append("Source changed or could not be verified; results must not be treated as verified evidence")
    if not rec["image_sha256_initial"]:
        warnings.append("Case was registered without a digest; equality is only verified within this run")
    timing["total_s"] = time.perf_counter() - t0
    run = {"run_id": run_id, "label": label, "method": method, "started_at": started_at,
           "finished_at": utcnow(), "selection": selection,
           "analysis": analysis.to_dict() if analysis else None, "features": features,
           "engine_runs": [er.to_dict() for er in engine_runs], "canonical_files": canonical,
           "metrics": recovery_metrics(files, ground_truth), "timing": {k: round(v, 6) for k, v in timing.items()},
           "image_sha256_before": before, "image_sha256_after": after,
           "source_unchanged": unchanged, "status": status, "error": error, "warnings": warnings,
           "settings": {"timeouts": timeouts, "conservative": conservative, "analysis_requested": analyze}}
    rec["runs"].append(run)
    if analysis:
        rec["status"] = analysis.status
    rec["last_hash_check"] = {"at": utcnow(), "unchanged": unchanged}
    case.save(rec)
    notify("run_finished", source_unchanged=unchanged, total_s=timing["total_s"], error=error)
    return run
