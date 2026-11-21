"""Oracle-derived training labels (spec §10).

Pre-registered objective (frozen in config/objective.json before any test-set
evaluation):
  1. q_s = exact recall of strategy s on the image (median over repeats is not
     needed: recall is deterministic per image; verified in tests).
  2. eligible = { s : q_s >= max_s q_s - tolerance }
  3. label = argmin over eligible of median end-to-end time;
     ties (|dt| < tie_epsilon_s) broken by fixed order tsk < photorec < combined.
If every strategy has q = 0, all are eligible and the fastest wins — documented
as the 'nothing recoverable' fallback. Labels are training targets only; they are
never available at prediction time."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

ORDER = ["tsk", "photorec", "combined"]
DEFAULT_OBJECTIVE = {"tolerance": 0.05, "tie_epsilon_s": 0.0}


def load_objective(path: str | Path | None = None) -> dict:
    if path and Path(path).exists():
        return {**DEFAULT_OBJECTIVE, **json.loads(Path(path).read_text())}
    return dict(DEFAULT_OBJECTIVE)


def derive_label(per_strategy: dict[str, dict], objective: dict | None = None) -> dict:
    """per_strategy: {strategy: {"recall": float, "times": [float, ...]}}"""
    obj = objective or DEFAULT_OBJECTIVE
    qs = {s: (v["recall"] or 0.0) for s, v in per_strategy.items()}
    ts = {s: median(v["times"]) for s, v in per_strategy.items()}
    best = max(qs.values())
    eligible = [s for s in ORDER if s in qs and qs[s] >= best - obj["tolerance"] - 1e-12]
    eligible.sort(key=lambda s: (ts[s], ORDER.index(s)))
    fastest = ts[eligible[0]]
    tied = [s for s in eligible if ts[s] <= fastest + obj["tie_epsilon_s"]]
    label = min(tied, key=ORDER.index)
    tie = any(s != label and abs(ts[s] - ts[label]) <= obj["tie_epsilon_s"] for s in eligible)
    return {"label": label, "eligible": eligible, "best_recall": best, "tie": tie,
            "fallback_nothing_recoverable": best == 0.0}
