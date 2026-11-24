"""Publication figures from saved run records (vector PDF, IEEE column width).

usage: rx_figures.py --res RESULTS_DIR --code CODE --out FIGDIR
Reads e1/, e2/, e3_256/, e3_1024/ under RESULTS_DIR and stats.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("pdf")
import matplotlib.pyplot as plt
import numpy as np

METHODS = ["tsk", "photorec", "combined", "rule", "cart"]
LABEL = {"tsk": "Metadata (TSK)", "photorec": "Carving (PhotoRec)", "combined": "Hybrid (both)",
         "rule": "Rule-v1", "cart": "CART", "oracle": "Oracle"}
# Okabe-Ito palette (colour-blind safe) + distinct markers for greyscale print
COL = {"tsk": "#0072B2", "photorec": "#E69F00", "combined": "#009E73", "rule": "#CC79A7", "cart": "#D55E00",
       "oracle": "#000000"}
MRK = {"tsk": "s", "photorec": "^", "combined": "D", "rule": "v", "cart": "o", "oracle": "*"}
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times", "Nimbus Roman", "DejaVu Serif"],
                     "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 6.5, "xtick.labelsize": 7,
                     "ytick.labelsize": 7, "pdf.fonttype": 42, "axes.linewidth": 0.6,
                     "lines.linewidth": 0.9, "figure.dpi": 300})
W1 = 3.45  # IEEE single column width (in)


def read(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines()] if Path(p).exists() else []


def per_image(runs, field):
    g = defaultdict(lambda: defaultdict(list))
    for r in runs:
        if r.get(field) is not None:
            g[r["method"]][r["image_id"]].append(r[field])
    return {m: {i: median(v) for i, v in d.items()} for m, d in g.items()}


def fig_tradeoff(res, stats, out):
    """Recall vs time on E2 (largest held-out set), single column."""
    fig, ax = plt.subplots(figsize=(W1, 2.0))
    ms = stats["E2"]["methods"]
    for m in METHODS:
        s = ms[m]
        r, lo, hi = s["recall_mean_ci"]
        t, tlo, thi = s["total_s_mean_ci"]
        ax.errorbar(t, r, yerr=[[r - lo], [hi - r]], xerr=[[t - tlo], [thi - t]], fmt=MRK[m], color=COL[m],
                    ms=4.5, capsize=1.5, elinewidth=0.6, label=LABEL[m])
    o = stats["E2"]["oracle"]
    r, lo, hi = o["recall_mean_ci"]; t, tlo, thi = o["time_mean_ci"]
    ax.errorbar(t, r, yerr=[[r - lo], [hi - r]], xerr=[[t - tlo], [thi - t]], fmt="*", color="k", ms=6,
                capsize=1.5, elinewidth=0.6, label="Oracle selector")
    ax.set_xlabel("Mean per-image end-to-end time (s)")
    ax.set_ylabel("Mean exact-file recall")
    ax.grid(alpha=0.25, lw=0.4)
    ax.legend(loc="lower right", frameon=False, ncol=2)
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig_tradeoff.pdf")


def fig_confusion(res, out):
    from sklearn.metrics import confusion_matrix
    cls = ["tsk", "photorec", "combined"]
    fig, axes = plt.subplots(1, 2, figsize=(W1, 1.7))
    labels = json.loads((res / "e2" / "labels.json").read_text())["labels"]
    test = read(res / "e2" / "test_runs.jsonl")
    for ax, m in zip(axes, ("cart", "rule")):
        pred = {r["image_id"]: r["strategy_used"] for r in test if r["method"] == m and r["repeat"] == 0}
        ids = sorted(pred)
        cm = confusion_matrix([labels[i]["label"] for i in ids], [pred[i] for i in ids], labels=cls)
        ax.pcolormesh(np.arange(4) - 0.5, np.arange(4) - 0.5, cm, cmap="Greys", vmin=0, vmax=cm.max() * 1.6, edgecolors="white", linewidth=0.5)
        ax.set_xlim(-0.5, 2.5); ax.set_ylim(2.5, -0.5); ax.set_aspect("equal")
        for (a, b), v in np.ndenumerate(cm):
            ax.text(b, a, str(v), ha="center", va="center", fontsize=7)
        ax.set_xticks(range(3)); ax.set_yticks(range(3))
        ax.set_xticklabels(["TSK", "PR", "Hyb"]); ax.set_yticklabels(["TSK", "PR", "Hyb"])
        ax.set_xlabel("Selected"); ax.set_title(LABEL[m] + " (E2)", fontsize=7.5)
    axes[0].set_ylabel("Oracle label")
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig_confusion.pdf")


def fig_scenario(res, out):
    test = read(res / "e2" / "test_runs.jsonl")
    scen = ["delete", "overwrite", "format", "fragmented"]
    fss = ["fat16", "fat32", "ext4"]
    rows = [(f, s) for f in fss for s in scen]
    pr = defaultdict(lambda: defaultdict(list))
    for r in test:
        if r["repeat"] == 0:
            pr[(r["fs"], r["scenario"])][r["method"]].append(r["recall"])
    M = np.array([[np.mean(pr[k][m]) for m in METHODS] for k in rows])
    fig, ax = plt.subplots(figsize=(W1, 2.35))
    im = ax.imshow(M, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    for (a, b), v in np.ndenumerate(M):
        ax.text(b, a, f"{v:.2f}", ha="center", va="center", fontsize=6, color="w" if v < 0.55 else "k")
    ax.set_xticks(range(len(METHODS))); ax.set_xticklabels(["TSK", "PhotoRec", "Hybrid", "Rule", "CART"])
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([f"{f}/{s}" for f, s in rows])
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02); cb.set_label("Mean exact recall")
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig_scenario.pdf")


def fig_time_breakdown(res, out):
    test = read(res / "e2" / "test_runs.jsonl")
    comps = [("hash_initial_s", "Initial hash"), ("analysis_s", "Metadata analysis"),
             ("features_s", "Features+inference"), ("engine_tsk_s", "TSK engine"),
             ("engine_photorec_s", "PhotoRec engine"), ("hash_final_s", "Final hash")]
    cols = ["#999999", "#56B4E9", "#CC79A7", "#0072B2", "#E69F00", "#555555"]
    fig, ax = plt.subplots(figsize=(W1, 1.9))
    left = np.zeros(len(METHODS))
    for (k, lab), c in zip(comps, cols):
        vals = []
        for m in METHODS:
            per = defaultdict(list)
            for r in test:
                if r["method"] == m:
                    v = r["timing"].get(k, 0.0)
                    if k == "features_s":
                        v += r["timing"].get("selection_s", 0.0)
                    per[r["image_id"]].append(v)
            vals.append(np.mean([median(v) for v in per.values()]))
        ax.barh(range(len(METHODS)), vals, left=left, color=c, label=lab, height=0.6, edgecolor="none")
        left += np.array(vals)
    ax.set_yticks(range(len(METHODS))); ax.set_yticklabels([LABEL[m] for m in METHODS])
    ax.invert_yaxis(); ax.set_xlabel("Mean per-image time (s), E2")
    ax.legend(ncol=3, fontsize=5.8, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.32))
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig_time_breakdown.pdf")


def fig_scaling(res, out):
    sizes = []
    pts = defaultdict(dict)
    for sz, d in ((256, "e3_256"), (1024, "e3_1024")):
        runs = read(res / d / "test_runs.jsonl")
        if not runs:
            continue
        sizes.append(sz)
        t = per_image(runs, "total_s"); rc = per_image(runs, "recall")
        for m in METHODS:
            pts[m][sz] = (np.mean(list(t[m].values())), np.mean(list(rc[m].values())))
    if not sizes:
        return
    fig, axes = plt.subplots(1, 2, figsize=(W1 * 2.0, 1.8))
    for m in METHODS:
        xs = sorted(pts[m])
        axes[0].plot(xs, [pts[m][x][0] for x in xs], marker=MRK[m], color=COL[m], ms=4, label=LABEL[m])
        axes[1].plot(xs, [pts[m][x][1] for x in xs], marker=MRK[m], color=COL[m], ms=4, label=LABEL[m])
    for ax in axes:
        ax.set_xscale("log", base=2); ax.set_xticks(sizes); ax.set_xticklabels([str(s) for s in sizes])
        ax.set_xlabel("Image size (MiB)"); ax.grid(alpha=0.25, lw=0.4)
    axes[0].set_ylabel("Mean end-to-end time (s)"); axes[1].set_ylabel("Mean exact recall")
    axes[1].legend(frameon=False, fontsize=6, loc="lower left", ncol=2)
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig_scaling.pdf")


def fig_tree(res, code, out):
    """Write the trained CART tree as TikZ (vector) with Gini, samples and class counts."""
    sys.path.insert(0, str(Path(code) / "src"))
    from recoverx.ml.selector import CartSelector
    rep = json.loads((res / "e1" / "training_report.json").read_text())
    sel = CartSelector.load(res / "e1" / "models" / rep["model_version"])
    m, t = sel.model, sel.model.tree_
    names = sel.meta["feature_names"]
    short = {"combined": "Hyb", "photorec": "PR", "tsk": "TSK"}
    BS = "\\"

    def stats(i):
        n = int(t.n_node_samples[i])
        counts = [int(round(v * n)) for v in t.value[i][0]]
        cnt = ", ".join(f"{short[c]} {k}" for c, k in zip(m.classes_, counts))
        return f"$G$={t.impurity[i]:.3f}, $n$={n}{BS}{BS} {cnt}"

    def node(i, depth):
        ind = "  " * (depth + 1)
        if t.children_left[i] == -1:
            lab = m.classes_[int(np.argmax(t.value[i][0]))]
            return f"node[leaf] {{{BS}textbf{{{short[lab]}}}{BS}{BS} {stats(i)}}}"
        f = names[t.feature[i]].replace("_", BS + "_")
        return (f"node[split] {{{BS}texttt{{{f}}} $" + BS + f"le$ {t.threshold[i]:.1f}{BS}{BS} {stats(i)}}}\n"
                f"{ind}child {{{node(t.children_left[i], depth + 1)} edge from parent node[left,font={BS}tiny] {{yes}}}}\n"
                f"{ind}child {{{node(t.children_right[i], depth + 1)} edge from parent node[right,font={BS}tiny] {{no}}}}")
    tikz = ("% generated by experiments/rx_figures.py from E1 model " + rep["model_version"] + "\n"
            + BS + "begin{tikzpicture}[font=" + BS + "scriptsize, level distance=14mm, sibling distance=38mm,\n"
            "  split/.style={draw, rounded corners=1pt, align=center, fill=blue!6, inner sep=2pt},\n"
            "  leaf/.style={draw, align=center, fill=gray!10, inner sep=2pt}]\n"
            + BS + node(0, 0) + ";\n" + BS + "end{tikzpicture}\n")
    (out / "tree.tex").write_text(tikz)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", required=True); ap.add_argument("--code", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res, out = Path(a.res), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = json.loads((res / "stats.json").read_text())
    fig_tradeoff(res, stats, out); fig_confusion(res, out); fig_scenario(res, out)
    fig_time_breakdown(res, out); fig_scaling(res, out); fig_tree(res, a.code, out)
    print("figures written to", out)


if __name__ == "__main__":
    main()
