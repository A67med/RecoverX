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

import time
import uuid
from pathlib import Path

from .. import STRATEGIES
from ..config import PHOTOREC_TIMEOUT, TSK_TIMEOUT, get_settings
from ..engines.engine_registry import get_engine
from ..forensic.case_store import Case
from ..forensic.filesystem_analyzer import analyze_image
from ..forensic.hashing import sha256_file
from ..ml.features import extract_features
from ..ml.selector import CartSelector, latest_model_dir, rule_select
from ..models import utcnow
from .integrity import apply_ground_truth, assign_duplicate_groups, canonical_view, recovery_metrics

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


def run_recovery(case: Case, method: str, *, ground_truth: dict | None = None,
                 analyze: bool | None = None, model_dir: Path | None = None,
                 timeouts: dict | None = None, label: str = "") -> dict:
    rec = case.load()
    image = Path(rec["image_path"])
    run_id = time.strftime("R%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    run_dir = case.runs_dir() / run_id
    timeouts = {"tsk": TSK_TIMEOUT, "photorec": PHOTOREC_TIMEOUT, **(timeouts or {})}
    needs_analysis = method in ("rule", "cart") or method.startswith("manual:")
    analyze = needs_analysis if analyze is None else (analyze or needs_analysis)
    timing: dict = {}
    case.event("run_started", run_id=run_id, method=method)

    T0 = time.perf_counter()
    t = time.perf_counter(); sha_before = sha256_file(image); timing["hash_initial_s"] = time.perf_counter() - t

    analysis = features = None
    offset = 0
    if analyze:
        t = time.perf_counter(); analysis = analyze_image(image); timing["analysis_s"] = time.perf_counter() - t
        offset = analysis.sector_offset
        t = time.perf_counter(); features = extract_features(analysis); timing["features_s"] = time.perf_counter() - t

    t = time.perf_counter()
    selection = _select(method, features, model_dir)
    timing["selection_s"] = time.perf_counter() - t
    timing["inference_s"] = selection.get("inference_s", 0.0)
    case.event("strategy_selected", run_id=run_id, **{k: selection[k] for k in ("method", "recommended", "strategy_used", "fallback")})

    engine_runs = []
    for name in ENGINE_PLAN[selection["strategy_used"]]:
        er = get_engine(name).run(image, run_dir / name, sector_offset=offset, timeout=timeouts[name],
                                  run_id=f"{run_id}-{name}")
        timing[f"engine_{name}_s"] = er.elapsed_s
        case.event("engine_finished", run_id=run_id, engine=name, status=er.status, files=len(er.files), error=er.error)
        engine_runs.append(er)

    files = [f for er in engine_runs for f in er.files]
    t = time.perf_counter(); apply_ground_truth(files, ground_truth); timing["verify_s"] = time.perf_counter() - t
    t = time.perf_counter(); assign_duplicate_groups(files); canonical = canonical_view(files); timing["dedup_s"] = time.perf_counter() - t
    metrics = recovery_metrics(files, ground_truth)

    t = time.perf_counter(); sha_after = sha256_file(image); timing["hash_final_s"] = time.perf_counter() - t
    timing["total_s"] = time.perf_counter() - T0
    timing = {k: round(v, 6) for k, v in timing.items()}

    run = {
        "run_id": run_id, "label": label, "method": method, "started_at": rec.get("created_at"),
        "finished_at": utcnow(), "selection": selection,
        "analysis": analysis.to_dict() if analysis else None, "features": features,
        "engine_runs": [er.to_dict() for er in engine_runs], "canonical_files": canonical,
        "metrics": metrics, "timing": timing,
        "image_sha256_before": sha_before, "image_sha256_after": sha_after,
        "source_unchanged": sha_before == sha_after == (rec["image_sha256_initial"] or sha_before),
        "status": "completed" if all(er.status == "completed" for er in engine_runs) else "incomplete",
    }
    rec["runs"].append(run)
    if analysis:
        rec["status"] = analysis.status
    rec["last_hash_check"] = {"at": utcnow(), "unchanged": run["source_unchanged"]}
    case.save(rec)
    case.event("run_finished", run_id=run_id, status=run["status"], source_unchanged=run["source_unchanged"],
               total_s=timing["total_s"])
    return run
