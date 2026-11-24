"""RecoverX research benchmark harness (paper experiments E1-E3).

This harness drives the *unmodified* RecoverX implementation (src/recoverx) and
mirrors the pre-registered protocol of src/recoverx/benchmarking/experiment.py:

  phase1  fixed strategies (tsk, photorec, combined) x R repeats per image,
          randomised order per repeat block          -> runs.jsonl, features.jsonl
  labels  oracle-derived labels with the frozen objective (config/objective.json)
  phase2  CART grid search on train / val, refit on train+val (Experiment.phase2)
  phase3  tsk, photorec, combined, rule, cart x R repeats -> test_runs.jsonl

Additions relative to the in-repo pipeline (measurement only, no change to
recovery behaviour):
  * each recovery run executes in a freshly forked child process so that
    per-run CPU time (getrusage) and peak resident memory of the external
    engines can be attributed to that run;
  * output-level precision, F1, duplicate outputs and "partial target" outputs
    (unverified outputs whose first bytes equal the first bytes of a deleted
    ground-truth file) are computed from the recovered files before the run
    directory is removed to bound disk usage.

Linux only (fork + getrusage). All images are synthetic and disposable.
"""
from __future__ import annotations

import argparse
import inspect
import json
import multiprocessing as mp
import os
import random
import resource
import shutil
import sys
import time
from pathlib import Path

PREFIX_BYTES = 4096


def _load_recoverx(code_root: Path):
    sys.path.insert(0, str(code_root / "src"))
    import recoverx  # noqa: F401
    return recoverx


# ------------------------------------------------------------------ dataset
def cmd_gen(a):
    _load_recoverx(Path(a.code))
    from recoverx.datasets import generator as g
    seeds = _parse_seeds(a.seeds)
    if a.split_label:
        g.split_of = lambda seed: a.split_label  # extension sets are evaluation-only
    sizes = tuple(int(s) for s in a.sizes.split(","))
    t0 = time.time()
    ds = g.generate_dataset(Path(a.out), seeds=seeds, sizes_mb=sizes,
                            filesystems=tuple(a.fs.split(",")), scenarios=tuple(a.scenarios.split(",")))
    ds["generation_wall_s"] = round(time.time() - t0, 1)
    ds["generator_args"] = {k: v for k, v in vars(a).items() if k != "fn"}
    (Path(a.out) / "manifest.json").write_text(json.dumps(ds, indent=1))
    probs = g.validate_dataset(Path(a.out))
    (Path(a.out) / "validation.json").write_text(json.dumps({"problems": probs}, indent=1))
    print(f"generated {len(ds['images'])} images; validation problems: {len(probs)}")


def _parse_seeds(s: str):
    out = []
    for part in s.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out += list(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


# ------------------------------------------------------------------ one run
def _gt_prefixes(dataset: Path, m: dict) -> dict[str, bytes]:
    out = {}
    for d in m["deleted"]:
        p = dataset / "reference" / m["image_id"] / d["name"]
        with open(p, "rb") as f:
            out[d["sha256"]] = f.read(PREFIX_BYTES)
    return out


def _output_metrics(run: dict, prefixes: dict[str, bytes]) -> dict:
    """Distinct-content precision and partial-target outputs (spec in module doc)."""
    states = {}
    paths = {}
    for er in run["engine_runs"]:
        root = Path(er["output_dir"])
        for f in er["files"]:
            states.setdefault(f["sha256"], f["integrity_state"])
            paths.setdefault(f["sha256"], root / f["relative_path"])
    hits = sum(1 for s in states.values() if s == "verified_exact_match")
    unver = [h for h, s in states.items() if s == "unverified"]
    partial = 0
    for h in unver:
        p = paths[h]
        try:
            with open(p, "rb") as fh:
                head = fh.read(PREFIX_BYTES)
        except OSError:
            continue
        if len(head) >= 512 and any(gp[:len(head)] == head[:len(gp)] for gp in prefixes.values()):
            partial += 1
    denom = hits + len(unver)
    precision = hits / denom if denom else None
    rec = run["metrics"].get("recall")
    f1 = (2 * precision * rec / (precision + rec)) if (precision and rec) else 0.0
    return {"distinct_contents": len(states), "distinct_hits": hits, "distinct_unverified": len(unver),
            "distinct_known_allocated": sum(1 for s in states.values() if s == "known_allocated_file"),
            "partial_target_outputs": partial, "precision": precision, "f1": f1}


def _child(conn, code, dataset, case_dir, m, method, model_dir):
    _load_recoverx(Path(code))
    from recoverx.datasets.generator import ground_truth_for
    from recoverx.forensic.case_store import Case
    from recoverx.recovery.orchestrator import run_recovery
    import threading
    import psutil
    peak = {"rss": 0}
    stop = threading.Event()

    def sample():  # sampled peak RSS of external engine processes (2 ms period)
        me = psutil.Process()
        while not stop.is_set():
            try:
                tot = sum(c.memory_info().rss for c in me.children(recursive=True))
                peak["rss"] = max(peak["rss"], tot)
            except psutil.Error:
                pass
            stop.wait(0.002)
    th = threading.Thread(target=sample, daemon=True)
    th.start()
    try:
        case = Case(Path(case_dir))
        # Paper protocol: only selector methods pay for metadata analysis, and the
        # selector's choice is executed as-is (v0.4+ defaults to running both
        # engines for automatic methods; that preservation policy is disabled here).
        kw = {"analyze": method in ("rule", "cart")}
        if "conservative" in inspect.signature(run_recovery).parameters:
            kw["conservative"] = False
        run = run_recovery(case, method, ground_truth=ground_truth_for(m),
                           model_dir=Path(model_dir) if model_dir else None, **kw)
        stop.set(); th.join()
        om = _output_metrics(run, _gt_prefixes(Path(dataset), m))
        rs, rc = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        out = {"ok": True, "run": {k: run[k] for k in ("run_id", "method", "finished_at", "selection", "metrics",
                                                       "timing", "source_unchanged", "status", "features")},
               "out_metrics": om,
               "resources": {"py_cpu_user_s": rs.ru_utime, "py_cpu_sys_s": rs.ru_stime,
                             "engine_cpu_user_s": rc.ru_utime, "engine_cpu_sys_s": rc.ru_stime,
                             "py_maxrss_kib": rs.ru_maxrss, "engine_peak_rss_kib_sampled": peak["rss"] // 1024},
               "engine_runs": [{"engine": e["engine"], "status": e["status"], "n_files": len(e["files"]),
                                "elapsed_s": e["elapsed_s"], "tool_version": e.get("tool_version")}
                               for e in run["engine_runs"]]}
        shutil.rmtree(case.runs_dir() / run["run_id"], ignore_errors=True)
    except Exception as e:  # recorded, never silently dropped
        import traceback
        out = {"ok": False, "error": repr(e), "tb": traceback.format_exc()}
    conn.send(out)
    conn.close()


def run_isolated(code, dataset, case_dir, m, method, model_dir=None) -> dict:
    ctx = mp.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_child, args=(child, code, str(dataset), str(case_dir), m, method, model_dir))
    p.start()
    res = parent.recv()
    p.join()
    return res


def _record(m, res, rep, order, phase) -> dict:
    run, mt = res["run"], res["run"]["metrics"]
    return {
        "phase": phase, "image_id": m["image_id"], "split": m["split"], "fs": m["fs"],
        "scenario": m["scenario"], "size_mb": m["size_mb"], "method": run["method"],
        "strategy_used": run["selection"]["strategy_used"], "fallback": run["selection"].get("fallback"),
        "decision_path": run["selection"].get("rationale"), "repeat": rep, "order_in_block": order,
        "run_id": run["run_id"], "finished_at": run["finished_at"], "status": run["status"],
        "source_unchanged": run["source_unchanged"], "recall": mt.get("recall"),
        "exact_recovered": mt.get("exact_recovered"), "gt_files": mt.get("gt_files"),
        "outputs": mt["outputs"], "duplicate_outputs": mt["duplicate_outputs"],
        "unverified_outputs": mt.get("unverified_outputs"), "known_allocated_outputs": mt.get("known_allocated_outputs"),
        "false_candidate_rate": mt.get("false_candidate_rate"), "timing": run["timing"],
        "total_s": run["timing"]["total_s"], **res["out_metrics"], **res["resources"],
        "engine_runs": res["engine_runs"],
    }


def _append(path: Path, rec: dict):
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _read(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def cmd_run(a):
    _load_recoverx(Path(a.code))
    from recoverx.forensic.case_store import create_case
    from recoverx.forensic.filesystem_analyzer import analyze_image
    from recoverx.ml.features import extract_features
    # pre-import everything the child needs so per-run CPU excludes import cost
    import recoverx.recovery.orchestrator  # noqa: F401
    import recoverx.datasets.generator  # noqa: F401
    import psutil  # noqa: F401
    dataset, exp = Path(a.dataset), Path(a.exp)
    exp.mkdir(parents=True, exist_ok=True)
    cases = exp / "cases"
    cases.mkdir(exist_ok=True)
    ds = json.loads((dataset / "manifest.json").read_text())
    splits = set(a.splits.split(","))
    methods = a.methods.split(",")
    out = exp / ("runs.jsonl" if a.phase == "phase1" else "test_runs.jsonl")
    errs = exp / "errors.jsonl"
    feats_path = exp / "features.jsonl"
    done = {(r["image_id"], r["method"], r["repeat"]) for r in _read(out)}
    feats_done = {r["image_id"] for r in _read(feats_path)}
    rng = random.Random(a.seed + (0 if a.phase == "phase1" else 1))
    imgs = [m for m in ds["images"] if m["split"] in splits]
    for i, m in enumerate(imgs):
        img = dataset / m["image_file"]
        if a.phase == "phase1" and m["image_id"] not in feats_done:
            t0 = time.perf_counter()
            an = analyze_image(img)
            f = extract_features(an)
            _append(feats_path, {"image_id": m["image_id"], "split": m["split"], "features": f,
                                 "analysis_status": an.status, "fs_type": an.fs_type,
                                 "analysis_s": time.perf_counter() - t0})
        case_dir = None
        for rep in range(a.repeats):
            order = methods[:]
            rng.shuffle(order)
            for k, meth in enumerate(order):
                if (m["image_id"], meth, rep) in done:
                    continue
                if case_dir is None:
                    case, _ = create_case(img, label=m["image_id"], cases_dir=cases,
                                          notes="benchmark case (controlled synthetic image)")
                    case_dir = case.dir
                res = run_isolated(a.code, dataset, case_dir, m, meth, a.model if meth == "cart" else None)
                if not res["ok"]:
                    _append(errs, {"image_id": m["image_id"], "method": meth, "repeat": rep, **res})
                    continue
                _append(out, _record(m, res, rep, k, a.phase))
        if case_dir is not None and not a.keep_cases:
            # keep case.json/events (audit trail) but drop nothing else: run dirs are already removed
            pass
        print(f"[{a.phase}] {i + 1}/{len(imgs)} {m['image_id']}", flush=True)


def cmd_env(a):
    import platform
    import subprocess
    rx = _load_recoverx(Path(a.code))
    from recoverx.engines.engine_registry import all_capabilities
    import sklearn, numpy, scipy, pandas
    info = {"recoverx_version": rx.__version__, "python": sys.version.split()[0],
            "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "cpu_model": next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), None),
            "mem_total_kib": int(next(l.split()[1] for l in open("/proc/meminfo") if l.startswith("MemTotal"))),
            "sklearn": sklearn.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__,
            "pandas": pandas.__version__, "tools": all_capabilities(),
            "mtools": subprocess.run(["mtools", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
            "e2fsprogs": subprocess.run(["mkfs.ext4", "-V"], capture_output=True, text=True).stderr.splitlines()[0],
            "dosfstools": subprocess.run(["mkfs.vfat", "--help"], capture_output=True, text=True).stdout.splitlines()[0]}
    Path(a.out).write_text(json.dumps(info, indent=1))
    print(json.dumps(info, indent=1))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--code", required=True); g.add_argument("--out", required=True)
    g.add_argument("--seeds", default="0-7"); g.add_argument("--sizes", default="48,96")
    g.add_argument("--fs", default="fat16,fat32,ext4"); g.add_argument("--scenarios", default="delete,overwrite,format,fragmented")
    g.add_argument("--split-label", default=None)
    g.set_defaults(fn=cmd_gen)
    r = sub.add_parser("run")
    r.add_argument("--code", required=True); r.add_argument("--dataset", required=True); r.add_argument("--exp", required=True)
    r.add_argument("--phase", choices=["phase1", "phase3"], required=True)
    r.add_argument("--splits", default="train,val,test"); r.add_argument("--methods", default="tsk,photorec,combined")
    r.add_argument("--repeats", type=int, default=3); r.add_argument("--seed", type=int, default=2026)
    r.add_argument("--model", default=None); r.add_argument("--keep-cases", action="store_true")
    r.set_defaults(fn=cmd_run)
    e = sub.add_parser("env")
    e.add_argument("--code", required=True); e.add_argument("--out", required=True)
    e.set_defaults(fn=cmd_env)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
