"""Leakage checks and measured CART evaluation from existing synthetic records.

No evidence or pickle models are loaded. The held-out test split is never used
for selection. Grouped cross-validation is diagnostic on train seeds only.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold
from .selector import CartSelector, rule_select
from .features import validate_features

CLASSES = ["tsk", "photorec", "combined"]


def balanced_score(y, predictions):
    y, predictions = np.asarray(y), np.asarray(predictions)
    return float(np.mean([np.mean(predictions[y == label] == label) for label in np.unique(y)]))


def score(y, predictions):
    return {"accuracy": float(accuracy_score(y, predictions)),
            "balanced_accuracy": balanced_score(y, predictions),
            "confusion_matrix": {"labels": CLASSES, "matrix": confusion_matrix(y, predictions, labels=CLASSES).tolist()},
            "per_class": classification_report(y, predictions, labels=CLASSES, output_dict=True, zero_division=0)}


def evaluate_records(exp_dir: Path, manifest_path: Path, grid: dict | None = None):
    images = json.loads(manifest_path.read_text())["images"]
    rows = [json.loads(line) for line in (exp_dir / "features.jsonl").read_text().splitlines() if line.strip()]
    labels = json.loads((exp_dir / "labels.json").read_text())["labels"]
    if len({m["image_id"] for m in images}) != len(images) or len({r["image_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate image identifiers in manifest/features")
    by_id = {r["image_id"]: r for r in rows}
    seen_seeds, seen_hashes = {}, {}
    for image in images:
        iid, split = image["image_id"], image["split"]
        if split not in ("train", "val", "test") or iid not in labels or iid not in by_id:
            raise ValueError("Missing labels/features or unknown split")
        if by_id[iid]["split"] != split:
            raise ValueError("Feature split disagrees with dataset manifest")
        if labels[iid]["label"] not in CLASSES:
            raise ValueError("Unknown target strategy")
        for store, key in ((seen_seeds, image["seed"]), (seen_hashes, image["image_sha256"])):
            if key in store and store[key] != split:
                raise ValueError("Train/test leakage: seed or image digest occurs in multiple splits")
            store[key] = split
        validate_features(by_id[iid]["features"])

    def subset(split):
        selected = [m for m in images if m["split"] in split]
        if not selected:
            raise ValueError(f"No samples in {split}")
        return (selected, np.array([validate_features(by_id[m["image_id"]]["features"]) for m in selected]),
                np.array([labels[m["image_id"]]["label"] for m in selected]))

    train, Xtr, ytr = subset(("train",))
    val, Xva, yva = subset(("val",))
    test, Xte, yte = subset(("test",))
    grid = grid or {"max_depth": [1, 2, 3, 4, 5], "min_samples_leaf": [1, 2, 4]}
    results = []
    for depth in grid["max_depth"]:
        for leaf in grid["min_samples_leaf"]:
            for weight in (None, "balanced"):
                model = CartSelector.train(Xtr, ytr, max_depth=depth, min_samples_leaf=leaf, class_weight=weight)
                pred = model.model.predict(Xva)
                results.append({"max_depth": depth, "min_samples_leaf": leaf, "class_weight": weight,
                                "val_balanced_accuracy": balanced_score(yva, pred),
                                "val_accuracy": float(accuracy_score(yva, pred))})
    best = sorted(results, key=lambda r: (-r["val_balanced_accuracy"], r["max_depth"], -r["min_samples_leaf"], bool(r["class_weight"])))[0]
    params = {k: best[k] for k in ("max_depth", "min_samples_leaf", "class_weight")}
    groups = np.array([m["seed"] for m in train])
    n_splits = min(5, len(set(groups)), min(Counter(ytr).values()))
    folds = []
    if n_splits >= 2:
        cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=2026)
        for tr, va in cv.split(Xtr, ytr, groups):
            model = CartSelector.train(Xtr[tr], ytr[tr], **params)
            folds.append({"train_seeds": sorted(set(groups[tr].tolist())),
                          "validation_seeds": sorted(set(groups[va].tolist())),
                          **score(ytr[va], model.model.predict(Xtr[va]))})
    all_rows, Xall, yall = subset(("train", "val"))
    final = CartSelector.train(Xall, yall, **params,
        extra_meta={"training_splits": ["train", "val"], "class_distribution": dict(Counter(yall)),
                    "selected_on": "validation balanced accuracy", "training_ids": [m["image_id"] for m in all_rows]})
    predictions = final.model.predict(Xte)
    majority = Counter(yall).most_common(1)[0][0]
    baselines = {"majority": score(yte, [majority] * len(yte)),
                 "rule-v1": score(yte, [rule_select(by_id[m["image_id"]]["features"])[0] for m in test])}
    baselines.update({s: score(yte, [s] * len(yte)) for s in CLASSES})
    report = {"grid": results, "selected": best,
              "train_class_distribution": dict(Counter(ytr)), "val_class_distribution": dict(Counter(yva)),
              "test_class_distribution": dict(Counter(yte)),
              "split_sizes": {"train": len(train), "val": len(val), "test": len(test)},
              "cross_validation": {"method": "StratifiedGroupKFold on training seeds only", "folds": folds,
                                   "note": "Diagnostic for the validation-selected configuration, not a nested unbiased model-selection estimate"},
              "held_out": score(yte, predictions), "baselines": baselines,
              "test_eligible_rate": float(np.mean([p in labels[m["image_id"]]["eligible"] for m, p in zip(test, predictions)])),
              "tree": final.tree_text(), "feature_importance": final.importances(),
              "limitations": ["Only small synthetic FAT16/FAT32/ext4 images; no real-world accuracy claim",
                              "Timing-derived oracle labels can be noisy and permit a 0.05 recall tolerance",
                              "Some classes are rare or absent in validation/test; accuracy does not guarantee recoverability",
                              "Evaluation measures strategy-label agreement, not new recovery performance",
                              "Historical feature/label files are trusted research inputs, not independently remeasured here"]}
    return final, report
