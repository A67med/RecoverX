"""RecoverX Streamlit dashboard. Every number and chart is read from persisted
case / experiment records; nothing here is illustrative or simulated.
Recovered file contents are never rendered or executed — only metadata is shown."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from recoverx.ui import quick_app
from recoverx.reporting.pdf_report import generate_case_pdf
from recoverx.demo import create_demo_case
from recoverx import STRATEGIES, __version__
from recoverx.config import PROJECT_ROOT, get_settings
from recoverx.diagnostics import run_diagnostics
from recoverx.exceptions import RecoverXError
from recoverx.forensic.case_store import build_manifest, create_case, list_cases, open_case, verify_case_evidence
from recoverx.forensic.filesystem_analyzer import analyze_image
from recoverx.forensic.hashing import sha256_file
from recoverx.ml.features import FEATURE_DOCS, extract_features
from recoverx.ml.selector import RULE_POLICY_TEXT, CartSelector, latest_model_dir
from recoverx.models import utcnow
from recoverx.recovery.jobs import current_job, start_recovery
from recoverx.recovery.orchestrator import validate_ground_truth
from recoverx.reporting.exports import case_report, csv_inventory
from recoverx.forensic.storage import operation_lock
from recoverx.forensic.image_validator import safe_identifier, safe_join

NAVY, TEAL, SLATE = "#6ca8ff", "#31d5bc", "#9aaec9"
PAGES = ["Quick Recovery", "Overview", "Case Management", "Forensic Analysis", "Intelligent Recovery", "Recovered Files",
         "Model Training", "Benchmark Laboratory", "Evidence & Audit", "Settings & Diagnostics"]

CSS = """
<style>
[data-testid="stSidebar"] { background: #0b1422; border-right: 1px solid #203148; }
.block-container { padding-top: 2.3rem; padding-bottom: 4rem; max-width: 1450px; }
h1,h2,h3 { letter-spacing: -.035em; font-weight: 650; }
h1 { font-size: 2.3rem !important; }
[data-testid="stMetric"] { background: linear-gradient(135deg,#142236,#101b2c); border: 1px solid #263a51;
  border-radius: 14px; padding: 18px 20px; min-height: 114px; }
[data-testid="stMetricLabel"] { color: #9aaec9; font-size: .8rem; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid #263a51; }
[data-testid="stForm"] { background: #101b2bcc; border: 1px solid #263a51; border-radius: 16px; }
button[kind="primary"] { color:#06211d; font-weight:700; border-radius:9px; }
.rx-eyebrow { color:#31d5bc; text-transform:uppercase; letter-spacing:.2em; font-size:.7rem; font-weight:700; }
.rx-hero { border:1px solid #2b435c; border-radius:18px; padding:26px 30px; margin:0 0 26px;
 background:linear-gradient(115deg,#132a3d,#112031 65%,#153f40); }
.rx-hero h2 { margin:8px 0; color:#edf6ff; font-size:1.65rem; }
.rx-hero p { color:#a9bdd2; margin:0; max-width:800px; }
.rx-badge { display:inline-block; padding:4px 9px; border-radius:6px; font-size:.72rem; font-weight:650; }
.rx-ok { background:#123e38; color:#68e9ca; } .rx-bad { background:#422931; color:#ffa6b1; }
.rx-warn { background:#3c3322; color:#f0ca80; } .rx-muted { color:#9aaec9; font-size:.8rem; }
[data-testid="stSidebar"] label { line-height:1.8; }
@media(max-width:700px) { .block-container { padding:1rem; } .rx-hero { padding:18px; } }
</style>
"""


def badge(ok: bool | None, yes="OK", no="Missing", warn=None):
    if ok is None:
        return f'<span class="rx-badge rx-warn">{warn or "Not yet measured"}</span>'
    return f'<span class="rx-badge {"rx-ok" if ok else "rx-bad"}">{yes if ok else no}</span>'


def not_measured(msg="Not yet measured"):
    st.info(f"**{msg}.** Nothing is shown until real records exist.")


# ------------------------------------------------------------------ data access
def experiments() -> list[Path]:
    d = get_settings().ensure().experiments_dir
    return sorted([p for p in d.glob("*") if (p / "experiment_config.json").exists()], reverse=True)


def include_historical_experiment(exps: list[Path]) -> None:
    archive = PROJECT_ROOT / "research" / "results" / "exp1"
    if (archive / "experiment_config.json").is_file() and st.checkbox("Include historical results"):
        exps.append(archive)


def read_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def active_model_dir() -> Path | None:
    return latest_model_dir(get_settings().models_dir)


def case_picker(key: str):
    cases = list_cases()
    if not cases:
        not_measured("No cases yet — create one in Case Management")
        return None, None
    labels = {f"{c['case_id']} · {Path(c['image_path']).name} {('· ' + c['label']) if c.get('label') else ''}": c["case_id"]
              for c in cases}
    choice = st.selectbox("Case", list(labels), key=key)
    case = open_case(labels[choice])
    return case, case.load()


# ------------------------------------------------------------------ pages
def page_overview():
    st.title("Investigation overview")
    st.markdown('<div class="rx-hero"><div class="rx-eyebrow">RECOVERX / FORENSIC OPERATIONS</div>'
                '<h2>Recover with evidence. Report with confidence.</h2>'
                '<p>Metadata recovery, signature carving and interpretable strategy selection in one auditable workspace. '
                'Every count below comes from your recorded cases.</p></div>', unsafe_allow_html=True)
    cases = list_cases()
    runs = [r for c in cases for r in c.get("runs", [])]
    outputs = sum(r["metrics"]["outputs"] for r in runs)
    exact = sum(sum(1 for cf in r["canonical_files"] if cf["integrity_state"] == "verified_exact_match") for r in runs)
    failed = sum(r["status"] != "completed" for r in runs)
    hash_issues = sum(not r["source_unchanged"] for r in runs)
    c = st.columns(5)
    c[0].metric("Cases", len(cases))
    c[1].metric("Recovery runs", len(runs))
    c[2].metric("Recovered outputs", outputs)
    c[3].metric("Verified exact matches", exact, help="distinct contents matching supplied ground truth")
    c[4].metric("Incomplete runs / hash changes", f"{failed} / {hash_issues}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Recent cases")
        if cases:
            st.dataframe(pd.DataFrame([{"case": x["case_id"], "image": Path(x["image_path"]).name,
                                        "status": x["status"], "runs": len(x.get("runs", [])),
                                        "created": x["created_at"][:19]} for x in cases[:10]]),
                         hide_index=True, width="stretch")
        else:
            not_measured("No cases yet")
    with right:
        st.subheader("System status")
        d = run_diagnostics()
        for e in d["engines"]:
            st.markdown(f"{badge(e['available'])} **{e['engine']}** {e['version'] or ''}", unsafe_allow_html=True)
        md = active_model_dir()
        st.markdown(f"{badge(bool(md), 'Installed', 'None')} **CART model** {md.name if md else '— conservative combined recovery available'}",
                    unsafe_allow_html=True)
        exps = experiments()
        if exps and (exps[0] / "analysis.json").exists():
            st.markdown(f"**Latest benchmark** `{exps[0].name}`")
            st.caption(read_json(exps[0] / "analysis.json")["headline"])
        else:
            st.markdown(badge(None) + " **Benchmark**", unsafe_allow_html=True)


def page_cases():
    st.title("Case Management")
    with st.expander("Safe demo — generate a synthetic FAT16 image", expanded=False):
        st.caption("Creates a 48 MiB synthetic disk image with deleted files, a ground-truth manifest "
                   "and a new case. Needs mkfs.vfat, mtools and Sleuth Kit; no real device is modified.")
        if st.button("Generate demo image and create case"):
            with st.spinner('Generating and validating synthetic evidence…'):
                try:
                    demo_case, demo_rec = create_demo_case()
                    st.success(f"Demo case created: {demo_case.id}")
                    st.code(demo_rec['image_path'])
                    st.caption(f"Ground-truth JSON: {demo_rec['demo_ground_truth_path']}")
                except Exception as e:
                    st.error(f"Demo generation failed; confirm system tools are installed: {e}")
    with st.form("new_case"):
        st.subheader("Create case")
        path = st.text_input("Authorized disk image path (raw .img/.dd/.raw)", placeholder="/path/to/image.img")
        c1, c2 = st.columns(2)
        label = c1.text_input("Label")
        examiner = c2.text_input("Examiner")
        notes = st.text_area("Notes")
        authorized = st.checkbox("I confirm I am authorized to examine this image and it is a copy designated for analysis.")
        if st.form_submit_button("Create case (computes SHA-256)", type="primary"):
            if not authorized:
                st.error("Authorization confirmation is required.")
            else:
                try:
                    case, rec = create_case(path.strip(), notes=notes, examiner=examiner, label=label)
                    st.success(f"Case {rec['case_id']} created · SHA-256 {rec['image_sha256_initial']}")
                except (RecoverXError, OSError, ValueError) as e:
                    st.error(str(e))
    st.subheader("Cases")
    case, rec = case_picker("cm_case")
    if not case:
        return
    c = st.columns(3)
    c[0].metric("Status", rec["status"])
    c[1].metric("Image size", f"{rec['image_size'] / 2**20:.1f} MiB")
    c[2].metric("Runs", len(rec["runs"]))
    st.markdown(f"**Image** `{rec['image_path']}`  \n**Initial SHA-256** `{rec['image_sha256_initial']}`")
    if rec.get("notes"):
        st.markdown(f"**Notes:** {rec['notes']}")
    st.download_button("Export evidence manifest (JSON)", json.dumps(build_manifest(case), indent=2),
                       file_name=f"{rec['case_id']}_manifest.json", mime="application/json")


def page_analysis():
    st.title("Forensic Analysis")
    case, rec = case_picker("fa_case")
    if not case:
        return
    if st.button("Run pre-recovery analysis (mmls / fsstat / fls, read-only)", type="primary"):
        try:
            with operation_lock(case.dir), st.spinner("Running TSK inspection…"):
                verify_case_evidence(case, operation="analysis")
                a = analyze_image(rec["image_path"])
                rec = case.load()
                rec["analysis"] = {**a.to_dict(), "features": extract_features(a), "at": utcnow()}
                rec["status"] = a.status
                case.save(rec)
                case.event("analysis", status=a.status, fs_type=a.fs_type, deleted=len(a.deleted_entries))
        except (RecoverXError, OSError, ValueError) as exc:
            st.error(str(exc))
    a = rec.get("analysis")
    if not a:
        not_measured("Analysis not run for this case")
        return
    c = st.columns(4)
    c[0].metric("Status", a["status"])
    c[1].metric("Filesystem", a["fs_type"] or "not detected")
    c[2].metric("Deleted entries", len(a["deleted_entries"]))
    c[3].metric("Analysis time", f"{a['elapsed_s']:.3f}s")
    st.markdown(f"Sector offset used: **{a['sector_offset']}** · Partitions: **{len(a['partitions']) or 'none (no volume system)'}**")
    if a["partitions"]:
        st.dataframe(pd.DataFrame(a["partitions"]), hide_index=True)
    st.subheader("Deleted entries (metadata claims, not proof of recoverability)")
    if a["deleted_entries"]:
        st.dataframe(pd.DataFrame(a["deleted_entries"]), hide_index=True, width="stretch")
    else:
        st.caption("No deleted entries reported by fls.")
    with st.expander("fsstat excerpt"):
        st.code(a["fsstat_excerpt"] or "—")
    with st.expander("Commands and errors"):
        st.json({"commands": [{k: c[k] for k in ("args", "returncode", "elapsed_s", "stderr")} for c in a["commands"]],
                 "errors": a["errors"]})


def page_recovery():
    st.title("Recovery workspace")
    st.caption("01 Select evidence  /  02 Configure strategy  /  03 Recover  /  04 Verify & review")
    case, rec = case_picker("ir_case")
    if not case:
        return
    md = active_model_dir()
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Evidence size", f"{rec['image_size'] / 2**20:,.1f} MiB")
        c2.metric("Registered", "SHA-256" if rec["image_sha256_initial"] else "No initial digest")
        c3.metric("CART model", "Installed" if md else "Not installed")
        st.text(Path(rec["image_path"]).name)
    mode = st.radio("Strategy selection", ["CART (automatic)", "Rule-based baseline (rule-v1)",
                                            "Fixed strategy", "Manual override"], horizontal=True)
    method = {"CART (automatic)": "cart", "Rule-based baseline (rule-v1)": "rule"}.get(mode)
    if mode == "Fixed strategy":
        method = st.selectbox("Fixed strategy", STRATEGIES, index=2)
    elif mode == "Manual override":
        method = "manual:" + st.selectbox("Strategy chosen by examiner", STRATEGIES, index=2)
    if method in ("cart", "rule"):
        st.info("Preservation mode: the selector explains its recommendation; both engines run sequentially. "
                "A model prediction does not prove that another engine has nothing to recover.")
    elif method not in ("combined", "manual:combined"):
        st.warning("Single-engine selection can miss files that the other engine could recover.")
    with st.expander("Verification & runtime settings"):
        gt_path = st.text_input("Optional ground-truth manifest (JSON with deleted/allocated SHA-256 lists)")
        c1, c2 = st.columns(2)
        tsk_timeout = c1.number_input("TSK timeout (seconds)", min_value=1, max_value=86400, value=600)
        photorec_timeout = c2.number_input("PhotoRec timeout (seconds)", min_value=1, max_value=86400, value=1800)
    job = current_job()
    active = bool(job and not job.done.is_set())
    if st.button("Start recovery", type="primary", disabled=active, icon=":material/play_arrow:"):
        try:
            gt = None
            if gt_path.strip():
                path = Path(gt_path.strip()).expanduser()
                if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
                    raise ValueError("Ground truth must be a JSON file smaller than 5 MiB")
                gt = json.loads(path.read_text())
                validate_ground_truth(gt)
            start_recovery(case, method, ground_truth=gt, model_dir=md,
                           timeouts={"tsk": tsk_timeout, "photorec": photorec_timeout})
            st.rerun()
        except (RecoverXError, OSError, ValueError) as exc:
            st.error(str(exc))
    if active and job.case_id != case.id:
        st.warning(f"Recovery is active for case {job.case_id}. Select that case to monitor or cancel it.")
    _live_recovery(case.id)


@st.fragment(run_every="1s")
def _live_recovery(case_id):
    case = open_case(case_id)
    job = current_job()
    if job and job.case_id == case_id:
        snapshot = job.snapshot()
        if not snapshot["done"]:
            events = snapshot["events"]
            stage = events[-1].get("detail") or events[-1]["stage"] if events else "Starting worker"
            st.info(f"In progress · {stage}")
            st.caption("Stages and completed-engine file counts are measured. These tools do not provide a reliable percentage. "
                       "Cancellation waits for the current hash/inventory operation to finish; active tool processes are stopped.")
            completed = [e for e in events if e["stage"] == "engine_finished"]
            if completed:
                st.dataframe(pd.DataFrame(completed)[["engine", "engine_status", "files"]], hide_index=True)
            if st.button("Cancel safely", disabled=snapshot["cancelling"], icon=":material/stop_circle:"):
                job.cancel.set()
                st.rerun(scope="fragment")
            with st.expander("Live operation log"):
                st.json(events)
            return
        if st.session_state.get("completed_job") != id(job):
            st.session_state["completed_job"] = id(job)
            st.rerun()
        if snapshot["error"]:
            st.error(snapshot["error"])
    rec = case.load()
    checkpoint = read_json(case.dir / "active_run.json")
    if checkpoint and checkpoint.get("stage") != "run_finished" and not (job and job.case_id == case_id and not job.done.is_set()):
        st.warning("An unfinished operation checkpoint exists. A worker may have stopped or may be running in another process. "
                   "Partial output is preserved; a new run will use a fresh directory and must acquire the case lock.")
    if not rec["runs"]:
        not_measured("No recovery runs for this case")
        return
    run = rec["runs"][-1]
    sel = run["selection"]
    st.subheader("Latest operation")
    (st.success if run["status"] == "completed" else st.warning)(f"{run['run_id']} · {run['status']}")
    if run.get("error"):
        st.error(run["error"])
    c = st.columns(4)
    c[0].metric("Applied strategy", sel["strategy_used"] or "Blocked")
    c[1].metric("Output files", run["metrics"]["outputs"])
    c[2].metric("Elapsed", f"{run['timing']['total_s']:.2f}s")
    c[3].metric("Evidence hash", "Unchanged" if run["source_unchanged"] else "CHECK FAILED")
    st.write("Recommendation:", sel.get("recommended") or "Examiner-selected", "·", sel["rationale"])
    for warning in [sel.get("fallback"), sel.get("safety_override"), *run.get("warnings", [])]:
        if warning:
            st.warning(warning)
    if not run["source_unchanged"]:
        st.error("Evidence integrity verification failed. Do not treat this run as verified evidence.")
    with st.expander("Selection inputs and measured engine results"):
        if run.get("features"):
            st.dataframe(pd.DataFrame([run["features"]]).T.rename(columns={0: "value"}))
        if sel.get("leaf_class_fractions"):
            st.write("Training-leaf class fractions (not confidence or recovery probability)")
            st.json(sel["leaf_class_fractions"])
        st.dataframe(pd.DataFrame([{"engine": e["engine"], "status": e["status"], "version": e["tool_version"],
                                    "files": len(e["files"]), "seconds": e["elapsed_s"], "error": e["error"]}
                                   for e in run["engine_runs"]]), hide_index=True)
        st.json(run["metrics"])
    st.caption("Open Recovered Files for the inventory, or Evidence & Audit for reports and hashes.")


def page_files():
    st.title("Recovered Files")
    st.caption("Metadata only. Recovered contents are never opened, rendered or executed by RecoverX.")
    case, rec = case_picker("rf_case")
    if not case:
        return
    if not rec["runs"]:
        not_measured("No recovery runs for this case")
        return
    rid = st.selectbox("Run", [r["run_id"] for r in reversed(rec["runs"])])
    run = next(r for r in rec["runs"] if r["run_id"] == rid)
    rows = [f for e in run["engine_runs"] for f in e["files"]]
    if not rows:
        st.info("This run produced no outputs.")
        return
    df = pd.DataFrame(rows)[["recovery_id", "engine", "original_name", "recovered_name", "relative_path", "extension",
                             "detected_type", "size", "sha256", "integrity_state", "duplicate_group", "ground_truth_id"]]
    c = st.columns(3)
    eng = c[0].multiselect("Engine", sorted(df.engine.unique()), default=sorted(df.engine.unique()))
    states = c[1].multiselect("Integrity", sorted(df.integrity_state.unique()), default=sorted(df.integrity_state.unique()))
    q = c[2].text_input("Search name / hash")
    f = df[df.engine.isin(eng) & df.integrity_state.isin(states)]
    if q:
        f = f[f.apply(lambda r: q.lower() in f"{r.original_name} {r.recovered_name} {r.sha256}".lower(), axis=1)]
    totals = st.columns(3)
    totals[0].metric("Matching outputs", len(f))
    totals[1].metric("Content size", f"{f['size'].sum() / 2**20:,.2f} MiB")
    totals[2].metric("Exact hash matches", int((f.integrity_state == "verified_exact_match").sum()))
    st.dataframe(f, hide_index=True, width="stretch")
    st.caption("A file type or original name is a metadata hint. Only matching supplied ground truth earns an exact-match label.")
    st.download_button("Export CSV", csv_inventory(f.to_dict("records")), file_name=f"{rid}_files.csv", mime="text/csv")
    st.subheader("Distinct contents (deduplicated by SHA-256, provenance kept)")
    st.dataframe(pd.DataFrame(run["canonical_files"]), hide_index=True, width="stretch")


def page_training():
    st.title("Model Training")
    exps = experiments()
    include_historical_experiment(exps)
    if not exps:
        not_measured("No experiment with labels yet — run Benchmark Laboratory phase 1")
        return
    exp = st.selectbox("Experiment", exps, format_func=lambda p: f"{p.name} (historical, read-only)" if p.parent == PROJECT_ROOT / "research" / "results" else p.name)
    labels = read_json(exp / "labels.json")
    rep = read_json(exp / "training_report.json")
    st.subheader("Feature definitions (all pre-recovery)")
    st.dataframe(pd.DataFrame([{"feature": k, "definition": v[0], "source": v[1]} for k, v in FEATURE_DOCS.items()]),
                 hide_index=True, width="stretch")
    if not labels:
        not_measured("Labels not derived yet")
        return
    st.subheader("Oracle-derived training labels")
    st.caption(f"Objective: {json.dumps(labels['objective'])} — labels use measured outcomes and are never available at prediction time.")
    ds = read_json(Path(read_json(exp / "experiment_config.json")["dataset_dir"]) / "manifest.json")
    split = {m["image_id"]: m["split"] for m in ds["images"]} if ds else {}
    ldf = pd.DataFrame([{"image": k, "split": split.get(k), "label": v["label"]} for k, v in labels["labels"].items()])
    st.plotly_chart(px.histogram(ldf, x="label", color="split", barmode="group",
                                 color_discrete_sequence=[NAVY, TEAL, "#e9c46a"]), width="stretch")
    if not rep:
        not_measured("Model not trained yet")
    else:
        st.subheader(f"Trained model · {rep['model_version']}")
        st.markdown(f"Selected hyperparameters: `{rep['selected']}`")
        st.dataframe(pd.DataFrame(rep["grid"]), hide_index=True)
        c1, c2 = st.columns(2)
        c1.code(rep["tree"], language="text")
        imp = pd.Series(rep["feature_importance"]).sort_values()
        c2.plotly_chart(px.bar(imp, orientation="h", labels={"value": "Gini importance (model-specific, not causal)",
                                                            "index": ""}, color_discrete_sequence=[TEAL]),
                        width="stretch")
    st.subheader("Actions")
    c1, c2 = st.columns(2)
    if c1.button("Retrain (phase 2: train/val only)", disabled=exp.parent == PROJECT_ROOT / "research" / "results"):
        from recoverx.benchmarking.experiment import Experiment
        cfg = read_json(exp / "experiment_config.json")
        Experiment(exp, Path(cfg["dataset_dir"])).phase2(progress=lambda s: None)
        st.rerun()
    if rep and c2.button("Install this model as the active application model", disabled=exp.parent == PROJECT_ROOT / "research" / "results"):
        import shutil
        source = exp / "models" / rep["model_version"]
        CartSelector.load(source)
        dst = get_settings().models_dir / source.name
        if not dst.exists():
            dst.mkdir()
            for name in ("model.json", "meta.json"):
                shutil.copy2(source / name, dst / name)
        st.success(f"Installed {dst.name}")
    st.caption(RULE_POLICY_TEXT.replace("\n", "  \n"))


def page_benchmark():
    st.title("Benchmark Laboratory")
    exps = experiments()
    include_historical_experiment(exps)
    with st.expander("Launch / resume a benchmark (runs in background)"):
        name = st.text_input("Experiment folder name", value="exp1")
        dataset = st.text_input("Dataset directory", value=str(get_settings().datasets_dir / "v1"))
        reps = st.number_input("Repeats per method", 1, 10, 3)
        if st.button("Launch all phases"):
            try:
                exp_dir = safe_join(get_settings().experiments_dir, safe_identifier(name))
                if not (Path(dataset) / "manifest.json").is_file():
                    raise ValueError("Dataset manifest not found")
                exp_dir.mkdir(parents=True, exist_ok=True)
                with open(exp_dir / "launch.log", "a") as log:
                    subprocess.Popen([sys.executable, str(PROJECT_ROOT / "scripts" / "run_benchmarks.py"), "--exp", str(exp_dir),
                                      "--dataset", dataset, "--repeats", str(reps), "all"], stdout=log, stderr=log,
                                     cwd=PROJECT_ROOT, start_new_session=os.name != "nt")
                st.success("Worker launched. An experiment lock prevents overlapping runs. Check the log for startup errors.")
            except (RecoverXError, OSError, ValueError) as exc:
                st.error(str(exc))
    if not exps:
        not_measured("No experiments recorded")
        return
    exp = st.selectbox("Experiment", exps, format_func=lambda p: f"{p.name} (historical, read-only)" if p.parent == PROJECT_ROOT / "research" / "results" else p.name, key="bl_exp")
    cfg = read_json(exp / "experiment_config.json")
    p1, p3 = read_jsonl(exp / "runs.jsonl"), read_jsonl(exp / "test_runs.jsonl")
    c = st.columns(4)
    c[0].metric("Images", cfg["n_images"])
    c[1].metric("Phase-1 runs", len(p1))
    c[2].metric("Test runs", len(p3))
    c[3].metric("Source-hash changes", sum(not r["source_unchanged"] for r in p1 + p3))
    if (exp / "launch.log").exists():
        with st.expander("Launch log (tail)"):
            st.code("\n".join((exp / "launch.log").read_text().splitlines()[-15:]))
    with st.expander("Saved configuration (replayable)"):
        st.json(cfg)
        st.download_button("Download configuration", json.dumps(cfg, indent=2), file_name=f"{exp.name}_config.json")
    if p3 and st.button("Recompute analysis from saved records", disabled=exp.parent == PROJECT_ROOT / "research" / "results"):
        from recoverx.benchmarking.analysis import analyze_experiment
        analyze_experiment(exp)
    res = read_json(exp / "analysis.json")
    if not res or "summary" not in res:
        not_measured("Held-out test results not available yet")
        return
    st.success(res["headline"])
    st.subheader("Held-out test results (per-image medians over repeats)")
    summ = pd.DataFrame(res["summary"]).T
    st.dataframe(summ, width="stretch")
    per = pd.read_csv(exp / "per_image_results.csv")
    c1, c2 = st.columns(2)
    c1.plotly_chart(px.box(per, x="method", y="median_time_s", points="all", title="End-to-end time per test image",
                           color_discrete_sequence=[NAVY]), width="stretch")
    c2.plotly_chart(px.box(per, x="method", y="recall", points="all", title="Exact-file recall per test image",
                           color_discrete_sequence=[TEAL]), width="stretch")
    agg = per.groupby("method")[["median_time_s", "recall"]].mean().reset_index()
    st.plotly_chart(px.scatter(agg, x="median_time_s", y="recall", text="method",
                               title="Quality vs time trade-off (means over test images)",
                               color_discrete_sequence=[NAVY]).update_traces(textposition="top center"),
                    width="stretch")
    st.subheader("Recall by scenario")
    st.plotly_chart(px.bar(per.groupby(["scenario", "method"]).recall.mean().reset_index(), x="scenario", y="recall",
                           color="method", barmode="group"), width="stretch")
    st.subheader("Paired comparisons: CART vs others")
    st.dataframe(pd.DataFrame(res["comparisons_cart_vs"]).T, width="stretch")
    st.subheader("Selector agreement with oracle labels (test images)")
    for m in ("cart", "rule"):
        cm = res["selector_vs_oracle"][m]["confusion_matrix"]
        st.plotly_chart(px.imshow(cm["matrix"], x=cm["labels"], y=cm["labels"], text_auto=True,
                                  labels={"x": "predicted", "y": "oracle label"}, color_continuous_scale="Blues",
                                  title=f"{m} — accuracy {res['selector_vs_oracle'][m]['accuracy']:.2f}"),
                        width="stretch")
    st.download_button("Export per-image results CSV", per.to_csv(index=False), file_name=f"{exp.name}_per_image.csv")


def page_audit():
    st.title("Evidence & Audit")
    case, rec = case_picker("ea_case")
    if not case:
        return
    st.markdown(f"**Initial SHA-256** `{rec['image_sha256_initial']}`")
    if st.button("Re-hash source image now"):
        cur = sha256_file(rec["image_path"])
        ok = cur == rec["image_sha256_initial"]
        case.event("manual_hash_check", sha256=cur, unchanged=ok)
        (st.success if ok else st.error)(f"Current SHA-256 {cur} — {'unchanged' if ok else 'CHANGED'}")
    ev = case.events()
    st.subheader("Event log")
    st.dataframe(pd.DataFrame(ev), hide_index=True, width="stretch")
    st.subheader("Runs")
    if rec["runs"]:
        st.dataframe(pd.DataFrame([{"run": r["run_id"], "method": r["method"], "strategy": r["selection"]["strategy_used"],
                                    "status": r["status"], "sha_before": (r["image_sha256_before"] or "unavailable")[:16] + "…",
                                    "sha_after": (r["image_sha256_after"] or "unavailable")[:16] + "…", "unchanged": r["source_unchanged"],
                                    "tools": ", ".join(f"{e['engine']} {e['tool_version']}" for e in r["engine_runs"])}
                                   for r in rec["runs"]]), hide_index=True, width="stretch")
    man = build_manifest(case)
    st.caption(man["disclaimer"])
    st.download_button("Export forensic report (PDF)", generate_case_pdf(case),
                       file_name=f"{case.id}_report.pdf", mime="application/pdf")
    st.download_button("Export forensic report (Markdown)", case_report(case),
                       file_name=f"{rec['case_id']}_report.md", mime="text/markdown")
    st.download_button("Export evidence manifest (JSON)", json.dumps(man, indent=2), file_name=f"{rec['case_id']}_manifest.json")


def page_diagnostics():
    st.title("Settings & Diagnostics")
    d = run_diagnostics()
    st.markdown(f"RecoverX {__version__} · Python {d['python']} · data home `{d['home']}`")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Engines")
        for e in d["engines"]:
            st.markdown(f"{badge(e['available'])} **{e['engine']}** version {e['version']} · "
                        + ", ".join(f"`{k}`" for k, v in e["executables"].items() if v), unsafe_allow_html=True)
        st.subheader("Python packages")
        st.dataframe(pd.DataFrame([{"package": k, "version": v or "MISSING"} for k, v in d["packages"].items()]), hide_index=True)
    with c2:
        st.subheader("Dataset-generation tools")
        st.dataframe(pd.DataFrame([{"tool": k, "path": v or "missing"} for k, v in d["dataset_tools"].items()]), hide_index=True)
        st.subheader("Storage")
        st.dataframe(pd.DataFrame([{"dir": k, **v} for k, v in d["directories"].items()]), hide_index=True)
        st.markdown(f"{badge(not d['disk_warning'], 'Disk OK', 'Low disk')} {d['disk_free_gb']} GB free", unsafe_allow_html=True)
        st.markdown(f"Model: `{d['model'] or 'none'}`  \nDatasets: {d['datasets'] or 'none'}  \nExperiments: {d['experiments'] or 'none'}")


ADVANCED_PAGES = {"Overview": page_overview, "Case Management": page_cases, "Forensic Analysis": page_analysis,
                  "Intelligent Recovery": page_recovery, "Recovered Files": page_files, "Model Training": page_training,
                  "Benchmark Laboratory": page_benchmark, "Evidence & Audit": page_audit,
                  "Settings & Diagnostics": page_diagnostics}


def main():
    icon = PROJECT_ROOT / "assets" / "recoverx.png"
    st.set_page_config(page_title="RecoverX — Quick Recovery", page_icon=str(icon) if icon.is_file() else "🛡️",
                       layout="wide", initial_sidebar_state="collapsed")
    try:
        quick_app.render()
    except (OSError, ValueError, RecoverXError) as exc:
        st.error(f"Unable to complete this operation: {exc}")
        st.caption("Existing case data is preserved. Check the selected paths and the installation guide.")
    # Expert tools stay available on the same page (no sidebar, no separate main workflow).
    if st.toggle("Advanced workspace — case management, research laboratory and diagnostics", key="rx_advanced"):
        st.markdown(CSS, unsafe_allow_html=True)
        page = st.selectbox("Advanced tool", list(ADVANCED_PAGES), key="rx_advanced_page")
        try:
            ADVANCED_PAGES[page]()
        except (OSError, ValueError, RecoverXError) as exc:
            st.error(f"Unable to complete this operation: {exc}")
            st.caption("Check the selected path, file permissions and Settings & Diagnostics. Existing case data is preserved.")
    st.markdown(f'<div class="rx-foot">RecoverX v{__version__} · local-only · evidence is opened read-only · '
                'recovered files are never executed</div>', unsafe_allow_html=True)
