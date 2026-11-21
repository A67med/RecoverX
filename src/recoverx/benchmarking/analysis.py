"""Statistical analysis computed only from saved experiment records (spec §12)."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.metrics import classification_report, confusion_matrix

from .experiment import Experiment, read_jsonl

METHODS = ["tsk", "photorec", "combined", "rule", "cart"]


def _iqr(x):
    q1, q3 = np.percentile(x, [25, 75])
    return float(q3 - q1)


def _rank_biserial(diffs: np.ndarray) -> float:
    d = diffs[diffs != 0]
    if len(d) == 0:
        return 0.0
    ranks = pd.Series(np.abs(d)).rank().to_numpy()
    return float((ranks[d > 0].sum() - ranks[d < 0].sum()) / ranks.sum())


def _holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def per_image_table(runs: list[dict]) -> pd.DataFrame:
    rows = []
    g = defaultdict(list)
    for r in runs:
        g[(r["image_id"], r["method"])].append(r)
    for (iid, meth), rs in g.items():
        rows.append({
            "image_id": iid, "fs": rs[0]["fs"], "scenario": rs[0]["scenario"], "method": meth,
            "strategy_used": Counter(r["strategy_used"] for r in rs).most_common(1)[0][0],
            "n_repeats": len(rs), "median_time_s": median(r["total_s"] for r in rs),
            "recall": median(r["recall"] for r in rs),
            "recall_varies": len({r["recall"] for r in rs}) > 1,
            "exact_recovered": median(r["exact_recovered"] for r in rs), "gt_files": rs[0]["gt_files"],
            "false_candidate_rate": median(r["false_candidate_rate"] for r in rs),
            "duplicate_outputs": median(r["duplicate_outputs"] for r in rs),
            "analysis_s": median(r["timing"].get("analysis_s", 0) for r in rs),
            "features_s": median(r["timing"].get("features_s", 0) for r in rs),
            "inference_s": median(r["timing"].get("inference_s", 0) for r in rs),
            "all_source_unchanged": all(r["source_unchanged"] for r in rs),
            "all_completed": all(r["status"] == "completed" for r in rs),
        })
    return pd.DataFrame(rows)


def analyze_experiment(exp_dir: Path) -> dict:
    exp_dir = Path(exp_dir)
    labels_doc = json.loads((exp_dir / "labels.json").read_text())
    labels = labels_doc["labels"]
    raw_runs = read_jsonl(exp_dir / "test_runs.jsonl")
    runs = list({(r["image_id"], r["method"], r["repeat"]): r for r in raw_runs}.values())
    if not runs:
        return {"headline": "No test runs recorded yet — results not measured."}
    if any(r["status"] != "completed" or not r["source_unchanged"] or r["recall"] is None for r in runs):
        raise ValueError("Cannot publish benchmark statistics from failed or integrity-invalid runs; resume incomplete trials")
    by_image = defaultdict(set)
    for run in runs:
        by_image[run["image_id"]].add(run["method"])
    if any(methods != set(METHODS) for methods in by_image.values()):
        raise ValueError("Incomplete benchmark: every test image needs all five methods")
    if any(image_id not in labels for image_id in by_image):
        raise ValueError("Missing oracle labels for test images")
    t = per_image_table(runs)
    t.to_csv(exp_dir / "per_image_results.csv", index=False)
    piv_time = t.pivot(index="image_id", columns="method", values="median_time_s")
    piv_rec = t.pivot(index="image_id", columns="method", values="recall")
    images = sorted(piv_time.index)

    # acceptable quality: within tolerance of best FIXED strategy on that image (measured in phase 3)
    tol = labels_doc["objective"]["tolerance"]
    best_fixed = piv_rec[["tsk", "photorec", "combined"]].max(axis=1)
    summary = {}
    for meth in METHODS:
        if meth not in piv_time:
            continue
        sub = t[t.method == meth]
        tot_gt = int(sub.gt_files.sum())
        summary[meth] = {
            "n_images": int(len(sub)),
            "median_of_image_medians_s": float(piv_time[meth].median()),
            "mean_of_image_medians_s": float(piv_time[meth].mean()),
            "iqr_s": _iqr(piv_time[meth]), "sum_time_s": float(piv_time[meth].sum()),
            "mean_recall": float(piv_rec[meth].mean()),
            "pooled_recall": float(sub.exact_recovered.sum() / tot_gt) if tot_gt else None,
            "images_acceptable_quality": int(((piv_rec[meth] >= best_fixed - tol - 1e-12)).sum()),
            "mean_false_candidate_rate": float(sub.false_candidate_rate.mean()),
            "all_source_unchanged": bool(sub.all_source_unchanged.all()),
            "all_completed": bool(sub.all_completed.all()),
            "strategies_used": dict(Counter(sub.strategy_used)),
        }

    # paired comparisons CART vs others
    comparisons, p_time = {}, {}
    for other in ["tsk", "photorec", "combined", "rule"]:
        if "cart" not in piv_time or other not in piv_time:
            continue
        dt = (piv_time["cart"] - piv_time[other]).to_numpy()
        dr = (piv_rec["cart"] - piv_rec[other]).to_numpy()
        try:
            p = float(wilcoxon(dt).pvalue) if np.any(dt != 0) else 1.0
        except ValueError:
            p = None
        try:
            pr = float(wilcoxon(dr).pvalue) if np.any(dr != 0) else 1.0
        except ValueError:
            pr = None
        p_time[other] = p if p is not None else 1.0
        comparisons[other] = {
            "n_pairs": int(len(dt)), "median_time_diff_s": float(np.median(dt)),
            "mean_time_diff_s": float(np.mean(dt)), "cart_faster_on": int((dt < 0).sum()),
            "wilcoxon_p_time": p, "rank_biserial_time": _rank_biserial(dt),
            "mean_recall_diff": float(np.mean(dr)), "images_cart_lower_recall": int((dr < -1e-12).sum()),
            "images_cart_higher_recall": int((dr > 1e-12).sum()), "wilcoxon_p_recall": pr,
        }
    for k, v in _holm(p_time).items():
        comparisons[k]["holm_adjusted_p_time"] = v

    # selector classification vs oracle labels (phase-1 derived)
    sel = {}
    for meth in ("cart", "rule"):
        sub = t[t.method == meth].set_index("image_id")
        y_true = [labels[i]["label"] for i in images]
        y_pred = [sub.loc[i, "strategy_used"] for i in images]
        cls = ["tsk", "photorec", "combined"]
        sel[meth] = {
            "accuracy": float(np.mean([a == b for a, b in zip(y_true, y_pred)])),
            "confusion_matrix": {"labels": cls, "matrix": confusion_matrix(y_true, y_pred, labels=cls).tolist()},
            "report": classification_report(y_true, y_pred, labels=cls, output_dict=True, zero_division=0),
            "predicted_eligible_rate": float(np.mean([p in labels[i]["eligible"] for i, p in zip(images, y_pred)])),
        }

    # stratified recall by fs / scenario
    strat = {dim: t.pivot_table(index=dim, columns="method", values="recall", aggfunc="mean").round(4).to_dict()
             for dim in ("fs", "scenario")}
    strat_time = t.pivot_table(index="scenario", columns="method", values="median_time_s", aggfunc="median").round(4).to_dict()

    # label distribution + sensitivity (phase-1 data, all splits)
    exp = Experiment.__new__(Experiment)
    exp.dir = exp_dir
    exp.objective = labels_doc["objective"]
    exp.repeats = json.loads((exp_dir / "experiment_config.json").read_text())["repeats"]
    sens = {}
    for tol_s in [0.0, 0.05, 0.10, 0.20]:
        lab = exp.derive_labels(tolerance=tol_s, write=False)
        test_lab = [lab[i]["label"] for i in images]
        cart_pred = [t[(t.method == "cart") & (t.image_id == i)].strategy_used.iloc[0] for i in images]
        sens[str(tol_s)] = {"label_distribution_all": dict(Counter(v["label"] for v in lab.values())),
                            "cart_agreement_on_test": float(np.mean([a == b for a, b in zip(test_lab, cart_pred)]))}

    cart_rows = t[t.method == "cart"]
    overhead = {"median_analysis_s": float(cart_rows.analysis_s.median()),
                "median_features_s": float(cart_rows.features_s.median()),
                "median_inference_s": float(cart_rows.inference_s.median())}
    nondet = sum(v["per_strategy"][s]["recall_nondeterministic"] for v in labels.values() for s in v["per_strategy"])

    res = {"n_test_images": len(images), "summary": summary, "comparisons_cart_vs": comparisons,
           "selector_vs_oracle": sel, "stratified_recall": strat, "median_time_by_scenario": strat_time,
           "label_sensitivity": sens, "selector_overhead": overhead,
           "label_distribution": dict(Counter(v["label"] for v in labels.values())),
           "label_ties": sum(v["tie"] for v in labels.values()),
           "nondeterministic_recall_cells": nondet}
    c = summary.get("cart", {})
    res["headline"] = (
        f"Test images: {len(images)}. CART median per-image time {c.get('median_of_image_medians_s', float('nan')):.3f}s, "
        f"mean recall {c.get('mean_recall', float('nan')):.3f}, acceptable-quality images "
        f"{c.get('images_acceptable_quality')}/{len(images)}. "
        + "; ".join(f"vs {k}: median Δt {v['median_time_diff_s']:+.3f}s (Holm p={v.get('holm_adjusted_p_time')}), "
                    f"mean Δrecall {v['mean_recall_diff']:+.3f}" for k, v in comparisons.items()))
    (exp_dir / "analysis.json").write_text(json.dumps(res, indent=1, default=float))
    return res
