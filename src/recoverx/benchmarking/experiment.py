"""Benchmark pipeline (spec §10, §12). Three phases, each persisted:

  phase1  every image (all splits): pre-recovery analysis + features, then the
          three fixed strategies x R repeats in randomised order  -> runs.jsonl
          -> labels.json (oracle-derived training targets)
  phase2  CART hyperparameter selection on train/val (grouped by image), refit on
          train+val, save model                                   -> model/
  phase3  held-out test images only: tsk, photorec, combined, rule, cart
          x R repeats, randomised order, real end-to-end runs      -> test_runs.jsonl
Every figure later reported is computed from these files."""
from __future__ import annotations

import json
import platform
import random
import sys
import time
from pathlib import Path
from statistics import median


from .. import STRATEGIES, __version__
from ..config import PROJECT_ROOT
from ..datasets.generator import ground_truth_for
from ..engines.engine_registry import all_capabilities
from ..forensic.case_store import Case, create_case
from ..forensic.filesystem_analyzer import analyze_image
from ..ml.features import FEATURE_NAMES, extract_features
from ..ml.labeling import derive_label, load_objective
from ..ml.selector import RULE_POLICY_TEXT
from ..models import utcnow
from ..recovery.orchestrator import run_recovery

OBJECTIVE_PATH = PROJECT_ROOT / "config" / "objective.json"


def _append(path: Path, rec: dict):
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def _run_record(m: dict, run: dict, case: Case, repeat: int, order: int, phase: str) -> dict:
    mt = run["metrics"]
    return {
        "phase": phase, "image_id": m["image_id"], "split": m["split"], "fs": m["fs"],
        "scenario": m["scenario"], "method": run["method"],
        "strategy_used": run["selection"]["strategy_used"], "fallback": run["selection"].get("fallback"),
        "decision_path": run["selection"].get("rationale"), "repeat": repeat, "order_in_block": order,
        "case_id": case.id, "run_id": run["run_id"], "finished_at": run["finished_at"],
        "status": run["status"], "source_unchanged": run["source_unchanged"],
        "recall": mt.get("recall"), "exact_recovered": mt.get("exact_recovered"), "gt_files": mt.get("gt_files"),
        "outputs": mt["outputs"], "duplicate_outputs": mt["duplicate_outputs"],
        "unverified_outputs": mt.get("unverified_outputs"), "known_allocated_outputs": mt.get("known_allocated_outputs"),
        "false_candidate_rate": mt.get("false_candidate_rate"), "timing": run["timing"],
        "total_s": run["timing"]["total_s"],
    }


class Experiment:
    def __init__(self, exp_dir: Path, dataset_dir: Path, repeats: int = 3, seed: int = 2026):
        self.dir, self.dataset_dir, self.repeats, self.seed = exp_dir, dataset_dir, repeats, seed
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir = self.dir / "cases"
        self.cases_dir.mkdir(exist_ok=True)
        self.ds = json.loads((dataset_dir / "manifest.json").read_text())
        self.objective = load_objective(OBJECTIVE_PATH)
        cfg = self.dir / "experiment_config.json"
        if cfg.exists():
            existing = json.loads(cfg.read_text())
            if existing.get("recoverx_version") != __version__:
                raise ValueError("Experiment belongs to a different pipeline version; use a new experiment folder")
            if (Path(existing["dataset_dir"]).resolve() != dataset_dir.resolve()
                    or existing["repeats"] != repeats or existing["order_seed"] != seed
                    or existing["objective"] != self.objective):
                raise ValueError("Resume settings differ from saved experiment configuration")
        if not cfg.exists():
            cfg.write_text(json.dumps({
                "created_at": utcnow(), "recoverx_version": __version__, "dataset_dir": str(dataset_dir),
                "dataset_version": self.ds["dataset_version"], "n_images": len(self.ds["images"]),
                "repeats": repeats, "order_seed": seed, "objective": self.objective,
                "rule_policy": RULE_POLICY_TEXT, "feature_names": FEATURE_NAMES,
                "tools": all_capabilities(), "python": sys.version.split()[0],
                "platform": platform.platform(), "cpu_count": __import__("os").cpu_count(),
                "cache_policy": "no cache dropping (unprivileged-safe); run order randomised per image block; "
                                "first run of each block is not discarded but repeats are summarised by median",
            }, indent=2))

    def images(self, splits=("train", "val", "test")):
        return [m for m in self.ds["images"] if m["split"] in splits]

    def _case(self, m) -> Case:
        case, _ = create_case(self.dataset_dir / m["image_file"], label=m["image_id"], cases_dir=self.cases_dir,
                              notes="benchmark case (controlled synthetic image)")
        return case

    # ---------------- phase 1
    def phase1(self, progress=print):
        runs_path, feats_path = self.dir / "runs.jsonl", self.dir / "features.jsonl"
        done = {(r["image_id"], r["method"], r["repeat"]) for r in read_jsonl(runs_path) if r["status"] == "completed" and r["source_unchanged"]}
        feats_done = {r["image_id"] for r in read_jsonl(feats_path)}
        rng = random.Random(self.seed)
        for m in self.images():
            img = self.dataset_dir / m["image_file"]
            if m["image_id"] not in feats_done:
                t0 = time.perf_counter()
                a = analyze_image(img)
                f = extract_features(a)
                _append(feats_path, {"image_id": m["image_id"], "split": m["split"], "features": f,
                                     "analysis_status": a.status, "fs_type": a.fs_type,
                                     "analysis_s": time.perf_counter() - t0})
            case = None
            gt = ground_truth_for(m)
            for rep in range(self.repeats):
                order = list(STRATEGIES)
                rng.shuffle(order)
                for k, s in enumerate(order):
                    if (m["image_id"], s, rep) in done:
                        continue
                    case = case or self._case(m)
                    run = run_recovery(case, s, ground_truth=gt, analyze=False)
                    _append(runs_path, _run_record(m, run, case, rep, k, "phase1"))
            progress(f"phase1 {m['image_id']}")
        self.derive_labels()

    def derive_labels(self, tolerance: float | None = None, write: bool = True) -> dict:
        obj = dict(self.objective)
        if tolerance is not None:
            obj["tolerance"] = tolerance
        attempts = {(r["image_id"], r["method"], r["repeat"]): r
                    for r in read_jsonl(self.dir / "runs.jsonl") if r["phase"] == "phase1"}
        runs = [r for r in attempts.values() if r["status"] == "completed"
                and r["source_unchanged"] and r["recall"] is not None]
        per: dict[str, dict] = {}
        for r in runs:
            d = per.setdefault(r["image_id"], {}).setdefault(r["strategy_used"], {"recalls": [], "times": []})
            d["recalls"].append(r["recall"])
            d["times"].append(r["total_s"])
        labels = {}
        for iid, d in per.items():
            if set(d) != set(STRATEGIES) or any(len(v["times"]) < self.repeats for v in d.values()):
                continue
            for s, v in d.items():
                if len(set(v["recalls"])) > 1:
                    v["recall_nondeterministic"] = True
                v["recall"] = median(v["recalls"])
            labels[iid] = {**derive_label(d, obj),
                           "per_strategy": {s: {"recall": v["recall"], "median_time": median(v["times"]),
                                                "recall_nondeterministic": v.get("recall_nondeterministic", False)}
                                            for s, v in d.items()}}
        if write:
            (self.dir / "labels.json").write_text(json.dumps({"objective": obj, "labels": labels}, indent=1))
        return labels

    # ---------------- phase 2
    def _xy(self, splits, labels):
        feats = {r["image_id"]: r["features"] for r in read_jsonl(self.dir / "features.jsonl")}
        ids = [m["image_id"] for m in self.images(splits)]
        X = [[feats[i][k] for k in FEATURE_NAMES] for i in ids]
        y = [labels[i]["label"] for i in ids]
        return ids, X, y

    def phase2(self, progress=print) -> dict:
        from ..ml.evaluation import evaluate_records
        final, report = evaluate_records(self.dir, self.dataset_dir / "manifest.json",
                                          self.objective.get("hyperparameter_grid"))
        version = "cart-" + time.strftime("%Y%m%d-%H%M%S-") + str(time.time_ns() % 1000000000)
        mdir = final.save(self.dir / "models", version)
        report.update(model_version=version, model_dir=str(mdir))
        (self.dir / "training_report.json").write_text(json.dumps(report, indent=2))
        progress(f"phase2 selected {report['selected']}; model {version}")
        return report

    # ---------------- phase 3
    def phase3(self, progress=print):
        rep = json.loads((self.dir / "training_report.json").read_text())
        mdir = Path(rep["model_dir"])
        path = self.dir / "test_runs.jsonl"
        done = {(r["image_id"], r["method"], r["repeat"]) for r in read_jsonl(path) if r["status"] == "completed" and r["source_unchanged"]}
        rng = random.Random(self.seed + 1)
        methods = ["tsk", "photorec", "combined", "rule", "cart"]
        for m in self.images(("test",)):
            case, gt = None, ground_truth_for(m)
            for rep_i in range(self.repeats):
                order = methods[:]
                rng.shuffle(order)
                for k, meth in enumerate(order):
                    if (m["image_id"], meth, rep_i) in done:
                        continue
                    case = case or self._case(m)
                    run = run_recovery(case, meth, ground_truth=gt, model_dir=mdir if meth == "cart" else None, conservative=False)
                    _append(path, _run_record(m, run, case, rep_i, k, "phase3"))
            progress(f"phase3 {m['image_id']}")
