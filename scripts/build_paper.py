#!/usr/bin/env python3
"""Render reports/research/paper.md from reports/research/paper_template.md,
filling every {{placeholder}} from saved experiment records. Any number in the
Results section therefore traces to workspace/experiments/<exp>/*.json(l).

  python3 scripts/build_paper.py --exp workspace/experiments/exp1"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--exp", type=Path, required=True)
a = ap.parse_args()
exp = a.exp.resolve()
an = json.loads((exp / "analysis.json").read_text())
cfg = json.loads((exp / "experiment_config.json").read_text())
tr = json.loads((exp / "training_report.json").read_text())
ds = json.loads((Path(cfg["dataset_dir"]) / "manifest.json").read_text())
imgs = ds["images"]
split = Counter(m["split"] for m in imgs)
tools = {t["engine"]: t["version"] for t in cfg["tools"]}

S = an["summary"]
C = an["comparisons_cart_vs"]


def f3(x):
    return f"{x:.3f}"


def pfmt(p):
    return "n/a" if p is None else (f"{p:.2g}" if p < 0.001 else f"{p:.3f}")


summary_rows = ["| Method | Median of per-image median time (s) | IQR (s) | Mean recall | Pooled recall | Images within tolerance | Mean false-candidate rate | Strategies used |",
                "|---|---|---|---|---|---|---|---|"]
names = {"tsk": "TSK only", "photorec": "PhotoRec only", "combined": "Combined (TSK→PhotoRec)",
         "rule": "Rule-based (rule-v1)", "cart": "CART-selected (RecoverX)"}
for m in ["tsk", "photorec", "combined", "rule", "cart"]:
    s = S[m]
    summary_rows.append(f"| {names[m]} | {f3(s['median_of_image_medians_s'])} | {f3(s['iqr_s'])} | {f3(s['mean_recall'])} | "
                        f"{f3(s['pooled_recall'])} | {s['images_acceptable_quality']}/{s['n_images']} | "
                        f"{f3(s['mean_false_candidate_rate'])} | {', '.join(f'{k}:{v}' for k, v in s['strategies_used'].items())} |")

cmp_rows = ["| CART vs | Median Δtime (s) | CART faster on | Wilcoxon p (time) | Holm-adjusted p | Rank-biserial r | Mean Δrecall | Images CART lower / higher recall | Wilcoxon p (recall) |",
            "|---|---|---|---|---|---|---|---|---|"]
for k in ["tsk", "photorec", "combined", "rule"]:
    c = C[k]
    cmp_rows.append(f"| {names[k]} | {c['median_time_diff_s']:+.4f} | {c['cart_faster_on']}/{c['n_pairs']} | {pfmt(c['wilcoxon_p_time'])} | "
                    f"{pfmt(c['holm_adjusted_p_time'])} | {c['rank_biserial_time']:+.2f} | {c['mean_recall_diff']:+.3f} | "
                    f"{c['images_cart_lower_recall']} / {c['images_cart_higher_recall']} | {pfmt(c['wilcoxon_p_recall'])} |")

scen = an["stratified_recall"]["scenario"]
scen_rows = ["| Scenario | " + " | ".join(names[m] for m in ["tsk", "photorec", "combined", "rule", "cart"]) + " |",
             "|---|---|---|---|---|---|"]
for sc in ["delete", "overwrite", "format", "fragmented"]:
    scen_rows.append(f"| {sc} | " + " | ".join(f3(scen[m][sc]) for m in ["tsk", "photorec", "combined", "rule", "cart"]) + " |")
fsr = an["stratified_recall"]["fs"]
fs_rows = ["| Filesystem | " + " | ".join(names[m] for m in ["tsk", "photorec", "combined", "rule", "cart"]) + " |",
           "|---|---|---|---|---|---|"]
for fs in ["ext4", "fat16", "fat32"]:
    fs_rows.append(f"| {fs} | " + " | ".join(f3(fsr[m][fs]) for m in ["tsk", "photorec", "combined", "rule", "cart"]) + " |")


def cm_table(m):
    cm = an["selector_vs_oracle"][m]["confusion_matrix"]
    rows = ["| oracle \\ predicted | " + " | ".join(cm["labels"]) + " |", "|---" * (len(cm["labels"]) + 1) + "|"]
    for lab, r in zip(cm["labels"], cm["matrix"]):
        rows.append(f"| {lab} | " + " | ".join(map(str, r)) + " |")
    return "\n".join(rows)


sens_rows = ["| Tolerance | Label distribution (all 96 images) | CART agreement with re-derived test labels |", "|---|---|---|"]
for t, v in an["label_sensitivity"].items():
    sens_rows.append(f"| {t} | {v['label_distribution_all']} | {f3(v['cart_agreement_on_test'])} |")

vals = {
    "n_images": len(imgs), "n_train": split["train"], "n_val": split["val"], "n_test": split["test"],
    "n_targets": sum(m["observed"]["n_targets"] for m in imgs),
    "n_fragmented": sum(m["observed"]["n_fragmented_targets"] for m in imgs),
    "n_overwritten": sum(m["observed"]["n_overwritten_targets"] for m in imgs),
    "tsk_version": tools.get("tsk"), "photorec_version": tools.get("photorec"),
    "python": cfg["python"], "platform": cfg["platform"], "cpu_count": cfg["cpu_count"],
    "repeats": cfg["repeats"], "tolerance": cfg["objective"]["tolerance"],
    "n_phase1_runs": sum(1 for _ in open(exp / "runs.jsonl")), "n_test_runs": sum(1 for _ in open(exp / "test_runs.jsonl")),
    "label_dist": an["label_distribution"], "label_ties": an["label_ties"],
    "nondet": an["nondeterministic_recall_cells"],
    "selected_hp": tr["selected"], "tree": tr["tree"].strip(),
    "train_dist": tr["train_class_distribution"], "val_dist": tr["val_class_distribution"],
    "summary_table": "\n".join(summary_rows), "comparison_table": "\n".join(cmp_rows),
    "scenario_table": "\n".join(scen_rows), "fs_table": "\n".join(fs_rows),
    "cm_cart": cm_table("cart"), "cm_rule": cm_table("rule"),
    "acc_cart": f3(an["selector_vs_oracle"]["cart"]["accuracy"]), "acc_rule": f3(an["selector_vs_oracle"]["rule"]["accuracy"]),
    "elig_cart": f3(an["selector_vs_oracle"]["cart"]["predicted_eligible_rate"]),
    "elig_rule": f3(an["selector_vs_oracle"]["rule"]["predicted_eligible_rate"]),
    "sens_table": "\n".join(sens_rows),
    "ovh_analysis_ms": f"{an['selector_overhead']['median_analysis_s'] * 1000:.1f}",
    "ovh_inference_ms": f"{an['selector_overhead']['median_inference_s'] * 1000:.2f}",
    "cart_vs_comb_dt_ms": f"{C['combined']['median_time_diff_s'] * 1000:+.1f}",
    "cart_vs_pr_dt_ms": f"{C['photorec']['median_time_diff_s'] * 1000:+.1f}",
    "cart_vs_tsk_dt_ms": f"{C['tsk']['median_time_diff_s'] * 1000:+.1f}",
    "cart_vs_rule_dt_ms": f"{C['rule']['median_time_diff_s'] * 1000:+.1f}",
    "cart_vs_comb_dr": f"{C['combined']['mean_recall_diff']:+.3f}",
    "cart_acceptable": S["cart"]["images_acceptable_quality"], "comb_acceptable": S["combined"]["images_acceptable_quality"],
    "exp_name": exp.name, "all_unchanged": all(S[m]["all_source_unchanged"] for m in S),
}
tpl = (ROOT / "reports" / "research" / "paper_template.md").read_text()
missing = sorted(set(re.findall(r"{{(\w+)}}", tpl)) - set(vals))
if missing:
    sys.exit(f"template placeholders without data: {missing}")
out = re.sub(r"{{(\w+)}}", lambda m: str(vals[m.group(1)]), tpl)
(ROOT / "reports" / "research" / "paper.md").write_text(out)
print("wrote reports/research/paper.md")
