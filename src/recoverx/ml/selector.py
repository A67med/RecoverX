"""Strategy selectors: the pre-registered rule-based baseline and the CART model."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import hashlib
import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text

from ..exceptions import ModelError
from .json_tree import JsonTree, export_tree
from ..forensic.image_validator import safe_identifier
from .features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, validate_features

RULE_POLICY_VERSION = "rule-v1"
RULE_POLICY_TEXT = """rule-v1 (frozen before test evaluation; pre-recovery features only)
  if fs_detected == 0            -> photorec   (no metadata to follow)
  elif n_deleted_nonzero == 0    -> photorec   (deleted entries carry no usable size/pointers)
  elif frac_deleted_nonzero < 1 or n_realloc > 0 -> combined (metadata partly damaged)
  else                           -> tsk"""


def rule_select(f: dict) -> tuple[str, str]:
    if f["fs_detected"] == 0:
        return "photorec", "no filesystem detected"
    if f["n_deleted_nonzero"] == 0:
        return "photorec", "no deleted entry with size > 0"
    if f["frac_deleted_nonzero"] < 1 or f["n_realloc"] > 0:
        return "combined", f"partial metadata (frac_nonzero={f['frac_deleted_nonzero']}, realloc={f['n_realloc']:.0f})"
    return "tsk", "all deleted entries retain size metadata"


class CartSelector:
    def __init__(self, model: DecisionTreeClassifier, meta: dict):
        self.model, self.meta = model, meta

    @classmethod
    def train(cls, X: list[list[float]], y: list[str], *, max_depth: int, min_samples_leaf: int,
              seed: int = 0, class_weight=None, extra_meta: dict | None = None) -> "CartSelector":
        clf = DecisionTreeClassifier(criterion="gini", max_depth=max_depth,
                                     min_samples_leaf=min_samples_leaf, random_state=seed, class_weight=class_weight)
        clf.fit(np.asarray(X, dtype=float), np.asarray(y))
        meta = {
            "model_type": "sklearn.tree.DecisionTreeClassifier (CART)",
            "feature_names": FEATURE_NAMES, "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "classes": clf.classes_.tolist(),
            "hyperparameters": {"max_depth": max_depth, "min_samples_leaf": min_samples_leaf, "random_state": seed, "class_weight": class_weight},
            "trained_at": datetime.now(timezone.utc).isoformat(), "n_train": len(y),
            "train_range": {k: [float(np.min(np.asarray(X)[:, i])), float(np.max(np.asarray(X)[:, i]))]
                            for i, k in enumerate(FEATURE_NAMES)},
            **(extra_meta or {}),
        }
        return cls(clf, meta)

    def save(self, directory: str | Path, version: str) -> Path:
        d = Path(directory) / safe_identifier(version)
        d.mkdir(parents=True, exist_ok=False)
        payload = json.dumps(export_tree(self.model), allow_nan=False).encode()
        (d / "model.json").write_bytes(payload)
        meta = {**self.meta, "version": version, "tree_text": self.tree_text(),
                "feature_importance": self.importances(), "serialization": "recoverx-cart-json-v1",
                "model_sha256": hashlib.sha256(payload).hexdigest()}
        (d / "meta.json").write_text(json.dumps(meta, indent=2, allow_nan=False))
        return d

    @classmethod
    def load(cls, directory: str | Path) -> "CartSelector":
        d = Path(directory)
        try:
            if (d / "meta.json").stat().st_size > 1024 * 1024:
                raise ModelError("Model metadata is too large")
            meta = json.loads((d / "meta.json").read_text())
            if meta.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or meta.get("feature_names") != FEATURE_NAMES:
                raise ModelError("model feature schema incompatible with this code version")
            if not (d / "model.json").exists():
                raise ModelError("Legacy pickle/joblib model rejected; retrain from recorded features and labels")
            if (d / "model.json").stat().st_size > 16 * 1024 * 1024:
                raise ModelError("Model is too large")
            payload = (d / "model.json").read_bytes()
            if hashlib.sha256(payload).hexdigest() != meta.get("model_sha256"):
                raise ModelError("Model digest mismatch")
            model = JsonTree(json.loads(payload))
            if set(meta.get("train_range", {})) != set(FEATURE_NAMES):
                raise ModelError("Missing training-domain metadata")
            for bounds in meta["train_range"].values():
                if len(bounds) != 2 or not np.isfinite(bounds).all() or bounds[0] > bounds[1]:
                    raise ModelError("Invalid training-domain metadata")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ModelError(f"Cannot load model from {d}: {exc}") from exc
        return cls(model, meta)

    def tree_text(self) -> str:
        return self.meta.get("tree_text", "") if isinstance(self.model, JsonTree) else export_text(self.model, feature_names=FEATURE_NAMES)

    def importances(self) -> dict[str, float]:
        return {k: round(float(v), 4) for k, v in zip(FEATURE_NAMES, self.model.feature_importances_)}

    def out_of_range(self, f: dict) -> list[str]:
        rng = self.meta.get("train_range", {})
        return [k for k, (lo, hi) in rng.items() if not (lo <= f[k] <= hi)]

    def predict(self, f: dict) -> dict:
        t0 = time.perf_counter()
        x = np.asarray([validate_features(f)], dtype=np.float32)
        pred = str(self.model.predict(x)[0])
        leaf_frac = dict(zip(self.model.classes_.tolist(), self.model.predict_proba(x)[0].round(3).tolist()))
        path = self._decision_path(x)
        return {"strategy": pred, "leaf_class_fractions": leaf_frac, "decision_path": path,
                "out_of_training_range": self.out_of_range(f),
                "inference_s": time.perf_counter() - t0}

    def _decision_path(self, x) -> list[str]:
        t = self.model.tree_
        steps = []
        for node in self.model.decision_path(x).indices:
            if t.children_left[node] == t.children_right[node]:
                continue
            name, thr, val = FEATURE_NAMES[t.feature[node]], t.threshold[node], x[0, t.feature[node]]
            steps.append(f"{name} = {val:g} {'<=' if val <= thr else '>'} {thr:.3f}")
        return steps


def latest_model_dir(models_dir: str | Path) -> Path | None:
    d = Path(models_dir)
    cands = sorted([p for p in d.glob("*") if (p / "meta.json").exists()]) if d.exists() else []
    return cands[-1] if cands else None
