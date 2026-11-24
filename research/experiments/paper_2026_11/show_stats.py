"""Print a compact view of stats.json (inspection helper)."""
import json
import sys

s = json.load(open(sys.argv[1]))
for E in ("E1", "E2"):
    print("==", E)
    for m, v in s[E]["methods"].items():
        r = v["recall_mean_ci"]
        print(f"{m:9s} rec {r[0]:.3f} [{r[1]:.3f},{r[2]:.3f}] prec {v['precision_mean_ci'][0]:.3f} "
              f"f1 {v['f1_mean_ci'][0]:.3f} t {v['total_s_mean_ci'][0]:.3f} cpu {v['total_cpu_s_mean_ci'][0]:.3f} "
              f"rssMB {v['engine_peak_rss_kib_sampled_mean_ci'][0] / 1024:.1f} dup {v['duplicate_outputs_mean_ci'][0]:.2f} "
              f"part {v['partial_target_outputs_mean_ci'][0]:.2f} unv {v['distinct_unverified_mean_ci'][0]:.2f} {v['strategies_used']}")
    print("oracle", s[E]["oracle"])
    print("stab", s[E]["label_stability"])
print("E0 stab", s["E0"].get("label_stability"))
g = s["grouped_cv"]
for k, v in g["all_features"].items():
    if isinstance(v, dict):
        print(k, {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "accuracy_ci"})
for k in g:
    if k not in ("all_features", "label_distribution"):
        print(k, {kk: round(vv, 3) for kk, vv in g[k]["cart"].items() if isinstance(vv, float)})
print(g["label_distribution"], s["label_tolerance_sensitivity"])
