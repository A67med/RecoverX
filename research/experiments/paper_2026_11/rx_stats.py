"""Paper statistics computed only from saved run records.

usage: rx_stats.py --code C --e1 DIR --e2 DIR [--e0 DIR] [--e3 DIR] --out results/stats.json

Outputs (all from runs.jsonl / test_runs.jsonl / features.jsonl / labels.json):
  * per-method summaries on held-out images with image-level (cluster) bootstrap
    95% percentile CIs [Efron 1979], B = 5000, seed 7;
  * oracle selector (per-image label from phase-1 runs, outcome from phase-3 runs);
  * label stability across repeats (labels re-derived from each single repeat);
  * leave-one-seed-out grouped cross-validation over all phase-1 images of E1+E2
    (seed = generation group; all images of one seed are held out together):
    CART (depth chosen by inner grouped CV), majority class, rule-v1,
    and feature ablations; reported with selection regret;
  * resource usage (CPU seconds, peak RSS) per method.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import numpy as np

ORDER = ["tsk", "photorec", "combined"]
METHODS = ["tsk", "photorec", "combined", "rule", "cart"]


def read(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def boot_ci(values_by_image: dict[str, float], stat=np.mean, B=5000, seed=7):
    keys = sorted(values_by_image)
    v = np.array([values_by_image[k] for k in keys], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(B, len(v)))
    bs = np.apply_along_axis(stat, 1, v[idx])
    return [float(stat(v)), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def per_image(runs, field, agg=median):
    g = defaultdict(lambda: defaultdict(list))
    for r in runs:
        val = r.get(field)
        if val is None:
            continue
        g[r["method"]][r["image_id"]].append(val)
    return {m: {i: float(agg(v)) for i, v in d.items()} for m, d in g.items()}


def method_summary(runs):
    out = {}
    fields = {"recall": median, "precision": median, "f1": median, "total_s": median,
              "engine_cpu_user_s": median, "engine_cpu_sys_s": median, "py_cpu_user_s": median,
              "engine_peak_rss_kib_sampled": max, "duplicate_outputs": median, "partial_target_outputs": median,
              "distinct_unverified": median, "outputs": median}
    tabs = {f: per_image(runs, f, agg) for f, agg in fields.items()}
    for m in METHODS:
        if m not in tabs["recall"]:
            continue
        s = {}
        for f in fields:
            d = tabs[f].get(m, {})
            if not d:
                continue
            s[f + "_mean_ci"] = boot_ci(d)
            s[f + "_median"] = float(np.median(list(d.values())))
        rs = [r for r in runs if r["method"] == m]
        gt = defaultdict(int); hit = defaultdict(list)
        for r in rs:
            gt[r["image_id"]] = r["gt_files"]; hit[r["image_id"]].append(r["exact_recovered"])
        s["pooled_recall"] = sum(median(hit[i]) for i in gt) / sum(gt.values())
        s["n_images"] = len(gt)
        s["n_runs"] = len(rs)
        s["all_source_unchanged"] = all(r["source_unchanged"] for r in rs)
        s["all_completed"] = all(r["status"] == "completed" for r in rs)
        s["strategies_used"] = dict(Counter(r["strategy_used"] for r in rs if r["repeat"] == 0))
        cpu = defaultdict(list)
        for r in rs:
            cpu[r["image_id"]].append(r["engine_cpu_user_s"] + r["engine_cpu_sys_s"] + r["py_cpu_user_s"] + r["py_cpu_sys_s"])
        s["total_cpu_s_mean_ci"] = boot_ci({i: median(v) for i, v in cpu.items()})
        out[m] = s
    return out


def labels_from_runs(runs, tolerance=0.05, repeat=None):
    from recoverx.ml.labeling import derive_label
    per = defaultdict(lambda: defaultdict(lambda: {"recalls": [], "times": []}))
    for r in runs:
        if repeat is not None and r["repeat"] != repeat:
            continue
        d = per[r["image_id"]][r["strategy_used"]]
        d["recalls"].append(r["recall"]); d["times"].append(r["total_s"])
    lab = {}
    for iid, d in per.items():
        ps = {s: {"recall": median(v["recalls"]), "times": v["times"]} for s, v in d.items()}
        lab[iid] = derive_label(ps, {"tolerance": tolerance, "tie_epsilon_s": 0.0})
        lab[iid]["per_strategy"] = {s: {"recall": ps[s]["recall"], "time": median(ps[s]["times"])} for s in ps}
    return lab


def label_stability(runs):
    full = labels_from_runs(runs)
    reps = sorted({r["repeat"] for r in runs})
    per_rep = [labels_from_runs(runs, repeat=k) for k in reps]
    ids = sorted(full)
    same_all = sum(len({pr[i]["label"] for pr in per_rep}) == 1 for i in ids)
    agree_full = [np.mean([pr[i]["label"] == full[i]["label"] for i in ids]) for pr in per_rep]
    # how often is the label decided by a time gap smaller than 10 ms / 5 %?
    small_gap = 0
    for i in ids:
        el = full[i]["eligible"]
        if len(el) > 1:
            t = sorted(full[i]["per_strategy"][s]["time"] for s in el)
            if t[1] - t[0] < max(0.01, 0.05 * t[0]):
                small_gap += 1
    return {"n_images": len(ids), "label_identical_in_all_single_repeat_derivations": same_all,
            "single_repeat_agreement_with_median_label": [float(x) for x in agree_full],
            "labels_decided_by_time_gap_lt_max(10ms,5pct)": small_gap,
            "images_with_multiple_eligible": sum(len(full[i]["eligible"]) > 1 for i in ids),
            "label_distribution": dict(Counter(v["label"] for v in full.values()))}


def oracle_eval(test_runs, labels):
    """Oracle selector: label strategy, outcome taken from the phase-3 fixed-strategy runs."""
    pr = per_image(test_runs, "recall")
    pt = per_image(test_runs, "total_s")
    rec, tim = {}, {}
    for i, l in labels.items():
        if i in pr.get(l, {}):
            rec[i], tim[i] = pr[l][i], pt[l][i]
    return {"recall_mean_ci": boot_ci(rec), "time_median": float(np.median(list(tim.values()))),
            "time_mean_ci": boot_ci(tim), "n_images": len(rec)}


def grouped_cv(feats, labels, phase1_table, groups, feature_names, rule_fn, seed=0, overhead=None):
    """Leave-one-seed-out CV. phase1_table[i][s] = (recall, time) from phase-1 runs."""
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.metrics import balanced_accuracy_score
    ids = sorted(labels)
    X = np.array([[feats[i][k] for k in feature_names] for i in ids], float)
    y = np.array([labels[i] for i in ids])
    g = np.array([groups[i] for i in ids])

    overhead = overhead or {}

    def regret(pred_ids, preds, charge=False):
        # charge=True adds the measured pre-recovery analysis time of image i
        # (selector methods must run mmls/fsstat/fls; fixed strategies do not)
        dr, dt, acc_q = [], [], []
        for i, p in zip(pred_ids, preds):
            best = max(v[0] for v in phase1_table[i].values())
            lab = labels[i]
            dr.append(best - phase1_table[i][p][0])
            dt.append(phase1_table[i][p][1] + (overhead.get(i, 0.0) if charge else 0.0) - phase1_table[i][lab][1])
            acc_q.append(phase1_table[i][p][0] >= best - 0.05 - 1e-12)
        return float(np.mean(dr)), float(np.mean(dt)), float(np.mean(acc_q))

    def fit_cart(Xtr, ytr, gtr):
        # inner grouped CV for depth (same grid as the pre-registered protocol)
        best, best_score = None, -1
        for d in [1, 2, 3, 4, 5]:
            for leaf in [1, 2, 4]:
                scores = []
                for gv in np.unique(gtr):
                    tr, va = gtr != gv, gtr == gv
                    if len(set(ytr[tr])) < 1:
                        continue
                    c = DecisionTreeClassifier(max_depth=d, min_samples_leaf=leaf, random_state=seed).fit(Xtr[tr], ytr[tr])
                    scores.append(np.mean(c.predict(Xtr[va]) == ytr[va]))
                sc = float(np.mean(scores))
                if sc > best_score + 1e-12:
                    best, best_score = (d, leaf), sc
        return DecisionTreeClassifier(max_depth=best[0], min_samples_leaf=best[1], random_state=seed).fit(Xtr, ytr), best

    preds = {"cart": [], "majority": [], "rule": [], "always_photorec": [], "always_combined": [], "always_tsk": []}
    chosen_depths = []
    order = []
    for gv in np.unique(g):
        tr, te = g != gv, g == gv
        clf, hp = fit_cart(X[tr], y[tr], g[tr])
        chosen_depths.append(hp)
        preds["cart"] += clf.predict(X[te]).tolist()
        maj = Counter(y[tr]).most_common(1)[0][0]
        preds["majority"] += [maj] * int(te.sum())
        te_ids = [i for i, t in zip(ids, te) if t]
        preds["rule"] += [rule_fn(feats[i])[0] for i in te_ids]
        for s in ("photorec", "combined", "tsk"):
            preds["always_" + s] += [s] * int(te.sum())
        order += te_ids
    ytrue = [labels[i] for i in order]
    res = {}
    for k, p in preds.items():
        r, t, aq = regret(order, p, charge=k in ("cart", "rule"))
        correct = np.array([a == b for a, b in zip(ytrue, p)], float)
        res[k] = {"accuracy": float(correct.mean()),
                  "accuracy_ci": boot_ci(dict(zip(order, correct))),
                  "balanced_accuracy": float(balanced_accuracy_score(ytrue, p)),
                  "mean_recall_regret": r, "mean_time_excess_s": t, "acceptable_quality_rate": aq}
    res["cart"]["chosen_hyperparameters"] = Counter(f"d={d},leaf={l}" for d, l in chosen_depths).most_common()
    res["n_images"] = len(order)
    res["n_groups"] = int(len(np.unique(g)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--e1", required=True); ap.add_argument("--e2", required=True)
    ap.add_argument("--d1", required=True); ap.add_argument("--d2", required=True)
    ap.add_argument("--e0", default=None); ap.add_argument("--e3", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.code) / "src"))
    from recoverx.ml.features import FEATURE_NAMES
    from recoverx.ml.policy import rule_select

    res = {}
    for name, d in (("E0", a.e0), ("E1", a.e1), ("E2", a.e2), ("E3", a.e3)):
        if not d:
            continue
        d = Path(d)
        test = read(d / "test_runs.jsonl")
        p1 = read(d / "runs.jsonl")
        block = {}
        if test:
            if "engine_cpu_user_s" in test[0]:
                block["methods"] = method_summary(test)
            labels = json.loads((d / "labels.json").read_text())["labels"] if (d / "labels.json").exists() else None
            if labels:
                test_ids = {r["image_id"] for r in test}
                block["oracle"] = oracle_eval(test, {i: labels[i]["label"] for i in test_ids if i in labels})
        if p1:
            block["label_stability"] = label_stability(p1)
        res[name] = block

    # grouped CV over E1 + E2 phase-1 images
    feats, labels, groups, table, over = {}, {}, {}, {}, {}
    for d, ds in ((Path(a.e1), Path(a.d1)), (Path(a.e2), Path(a.d2))):
        man = {m["image_id"]: m for m in json.loads((ds / "manifest.json").read_text())["images"]}
        for r in read(d / "features.jsonl"):
            feats[r["image_id"]] = r["features"]
        # selector overhead charged in CV = in-run analysis + features + selection time,
        # measured in phase-3 selector runs (warm cache, same conditions as the fixed
        # strategies' phase-1 times); images without phase-3 runs (E1 train/val) get the
        # median of their (fs, scenario) cell.
        cell_over, img_over = defaultdict(list), defaultdict(list)
        for r in read(d / "test_runs.jsonl"):
            if r["method"] in ("cart", "rule"):
                tm = r["timing"]
                v = tm.get("analysis_s", 0) + tm.get("features_s", 0) + tm.get("selection_s", 0)
                img_over[r["image_id"]].append(v)
                cell_over[(r["fs"], r["scenario"])].append(v)
        p1 = read(d / "runs.jsonl")
        lab = labels_from_runs(p1)
        for i, v in lab.items():
            mi = man[i]
            over[i] = median(img_over[i]) if img_over.get(i) else median(cell_over[(mi["fs"], mi["scenario"])])
            labels[i] = v["label"]
            groups[i] = man[i]["seed"]
            table[i] = {s: (v["per_strategy"][s]["recall"], v["per_strategy"][s]["time"]) for s in v["per_strategy"]}
    res["grouped_cv"] = {"all_features": grouped_cv(feats, labels, table, groups, FEATURE_NAMES, rule_select, overhead=over)}
    ablations = {
        "no_size_or_counts_of_allocated": [f for f in FEATURE_NAMES if f not in ("image_mb", "n_allocated")],
        "metadata_counts_only": ["n_deleted", "n_deleted_named", "n_deleted_nonzero", "frac_deleted_nonzero", "n_realloc"],
        "fs_type_only": ["fs_detected", "fs_fat", "fs_ext", "has_partition_table"],
        "without_n_deleted_named": [f for f in FEATURE_NAMES if f != "n_deleted_named"],
    }
    for k, fl in ablations.items():
        r = grouped_cv(feats, labels, table, groups, fl, rule_select, overhead=over)
        res["grouped_cv"][k] = {"cart": r["cart"]}
    res["grouped_cv"]["label_distribution"] = dict(Counter(labels.values()))
    # tolerance sensitivity of label distribution on pooled phase-1 data
    sens = {}
    for tol in (0.0, 0.05, 0.10, 0.20):
        dist = Counter()
        for d in (Path(a.e1), Path(a.e2)):
            dist.update(v["label"] for v in labels_from_runs(read(d / "runs.jsonl"), tolerance=tol).values())
        sens[str(tol)] = dict(dist)
    res["label_tolerance_sensitivity"] = sens
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps(res["grouped_cv"]["all_features"], indent=1)[:3000])


if __name__ == "__main__":
    main()
