"""RecoverX Streamlit dashboard. Every number and chart is read from persisted
case / experiment records; nothing here is illustrative or simulated.
Recovered file contents are never rendered or executed — only metadata is shown."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from recoverx import STRATEGIES, __version__
from recoverx.config import PROJECT_ROOT, get_settings
from recoverx.diagnostics import run_diagnostics
from recoverx.exceptions import RecoverXError
from recoverx.forensic.case_store import build_manifest, create_case, list_cases, open_case, verify_case_evidence
from recoverx.forensic.filesystem_analyzer import analyze_image
from recoverx.forensic.hashing import sha256_file
from recoverx.forensic.image_validator import safe_identifier, safe_join
from recoverx.ml.features import FEATURE_DOCS, extract_features
from recoverx.quick import guided_recovery
from recoverx.acquisition import candidate_devices, capture_device, AcquisitionError
from recoverx.ml.model_install import bundled_model_dir, install_bundled_model
from recoverx.ml.selector import RULE_POLICY_TEXT, CartSelector, latest_model_dir
from recoverx.models import utcnow
from recoverx.reporting.pdf_report import generate_case_pdf
from recoverx.tool_paths import resolve_tool

NAVY, TEAL, SLATE = "#14213d", "#2a9d8f", "#5c677d"
PAGES = ["Quick Recovery", "Overview", "Case Management", "Forensic Analysis", "Intelligent Recovery", "Recovered Files",
         "Model Training", "Benchmark Laboratory", "Evidence & Audit", "Settings & Diagnostics"]

# Quick Recovery offers explicit engine choices without restoring the sidebar.
# "smart" is the Windows default and preserves the existing automatic fallback.
QUICK_RECOVERY_METHODS = {
    'Smart Recovery (CART + fallback)': 'smart',
    'TSK only': 'tsk',
    'PhotoRec only': 'photorec',
    'TSK + PhotoRec (both)': 'combined',
    'Automatic (CART only)': 'cart',
    'Automatic (rule-v1 only)': 'rule',
}
QUICK_RECOVERY_METHOD_HELP = {
    'smart': 'CART chooses the initial strategy (rule-v1 if unavailable). If a single engine fails or finds no files, the other engine is tried.',
    'tsk': 'Run The Sleuth Kit only. PhotoRec will not run automatically.',
    'photorec': 'Run PhotoRec only. TSK recovery will not run automatically.',
    'combined': 'Run both TSK and PhotoRec, then combine results without changing the source image.',
    'cart': 'Use CART to choose a strategy (rule-v1 if unavailable), without the additional Smart Recovery fallback.',
    'rule': 'Use the rule-v1 selector to choose a strategy, without the additional Smart Recovery fallback.',
}

CSS = f"""
<style>
[data-testid="stSidebar"] {{ background: {NAVY}; }}
[data-testid="stSidebar"] * {{ color: #e8ecf3 !important; }}
.block-container {{ padding-top: 1.6rem; max-width: 1250px; }}
h1, h2, h3 {{ color: {NAVY}; letter-spacing: -0.01em; }}
[data-testid="stMetric"] {{ background: #f6f8fb; border: 1px solid #e3e8ef; border-radius: 8px; padding: 10px 14px; }}
.rx-badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.78rem; font-weight:600; }}
.rx-ok {{ background:#e3f4f1; color:#1d6f65; }} .rx-bad {{ background:#fdecea; color:#9b2c2c; }}
.rx-warn {{ background:#fff4e0; color:#8a5a00; }} .rx-muted {{ color:{SLATE}; font-size:0.85rem; }}
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
    live = sorted([p for p in d.glob("*") if (p / "experiment_config.json").exists()], reverse=True)
    # The supplied repository includes a read-only historical snapshot. Show
    # its real recorded metrics without pretending the original dataset exists.
    archive = PROJECT_ROOT / 'results' / 'exp1'
    if (archive / 'experiment_config.json').exists():
        live.append(archive)
    return live


def archived_experiment(p: Path) -> bool:
    return p.resolve().is_relative_to((PROJECT_ROOT / 'results').resolve())


def experiment_label(p: Path) -> str:
    return f"{p.name}  {'(historical read-only results)' if archived_experiment(p) else '(workspace)'}"


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
    st.title("Overview")
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
        st.markdown(f"{badge(bool(md), 'Installed', 'None')} **CART model** {md.name if md else '— rule-v1 fallback in use'}",
                    unsafe_allow_html=True)
        if not md and bundled_model_dir() and st.button('Install included CART model'):
            try:
                installed = install_bundled_model()
                st.success(f'Installed {installed.name}. CART is available for new runs.')
                st.rerun()
            except RecoverXError as e:
                st.error(str(e))
        exps = experiments()
        if exps and (exps[0] / "analysis.json").exists():
            st.markdown(f"**Benchmark record** `{experiment_label(exps[0])}`")
            st.caption(read_json(exps[0] / "analysis.json")["headline"])
        else:
            st.markdown(badge(None) + " **Benchmark**", unsafe_allow_html=True)


def local_file_picker() -> str | None:
    """Use an OS-native file picker on the local desktop (Windows or Kali)."""
    if os.name == 'nt':
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            try:
                selected = filedialog.askopenfilename(
                    parent=root, title='Select RecoverX disk image',
                    filetypes=[('Disk images', '*.img *.dd *.raw *.bin *.001'),
                               ('All files', '*.*')])
                return selected or None
            finally:
                root.destroy()
        except Exception:
            return None
    if not os.environ.get('DISPLAY'):
        return None
    zenity = shutil.which('zenity')
    kdialog = shutil.which('kdialog')
    if zenity:
        cmd = [zenity, '--file-selection', '--title=Choose forensic disk image',
               '--file-filter=Disk images | *.img *.dd *.raw *.bin *.001',
               '--file-filter=All files | *']
    elif kdialog:
        cmd = [kdialog, '--getopenfilename', str(Path.home()),
               'Disk images (*.img *.dd *.raw *.bin *.001)']
    else:
        return None
    try:
        r = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def page_quick():
    st.title('RecoverX · Quick Recovery')
    st.caption('Choose an existing disk image or case, then run analysis + recovery automatically. '
               'Evidence is read-only. Files are saved to a separate case directory.')

    if os.name != 'nt':
        with st.expander('Optional: Capture an image from an unmounted test disk (Linux)', expanded=False):
            st.warning('This creates a read-only COPY of the selected disk/partition. It never formats, '
                       'deletes, or mounts a device. Always inspect the device path and size, and obtain permission. '
                       'A graphical administrator password prompt may appear.')
            if st.button('Refresh safe unmounted devices'):
                try:
                    st.session_state['quick_devices'] = candidate_devices()
                except (AcquisitionError, OSError, ValueError) as e:
                    st.error(str(e))
            devices = st.session_state.get('quick_devices', [])
            if devices:
                labels = {f"{x['path']} — {x['size']/2**30:.2f} GiB — {x['fstype']} ({x['type']})": x['path']
                          for x in devices}
                chosen = st.selectbox('Unmounted source device (never the system disk)', list(labels))
                permission = st.checkbox('I own or am authorized to examine the selected device, and '
                                         'I confirmed it is NOT my system disk.', key='quick_acquire_authorized')
                if st.button('Capture read-only image', disabled=not permission):
                    try:
                        with st.spinner('Creating a byte-for-byte image on a separate disk. Do not disconnect the source…'):
                            img = capture_device(labels[chosen])
                        st.session_state['quick_img'] = str(img)
                        st.success(f'Image captured: {img}')
                    except AcquisitionError as e:
                        st.error(str(e))
            else:
                st.caption('Press Refresh to discover unmounted non-system devices. '
                           'Mounted devices and disks containing mounted partitions are excluded.')
    if os.name == 'nt':
        missing = [tool for tool in ('tsk_recover', 'fls', 'fsstat', 'mmls', 'photorec')
                   if not resolve_tool(tool)]
        if missing:
            st.error('Recovery tools missing: ' + ', '.join(missing)
                     + '. Run SETUP_WINDOWS.cmd from the RecoverX folder first.')
        st.info('Windows version works with RAW disk images (.img/.dd/.raw/.bin). '
                'It does not directly capture a physical USB or system disk. '
                'Create the image with a trusted disk-imaging tool first, then select it here.')

    existing = list_cases()
    source = st.radio('Source', ['New disk image', 'Existing case'] if existing else ['New disk image'],
                      horizontal=True)
    image_path = None
    case_id = None
    label = examiner = ''
    authorized = False
    if source == 'New disk image':
        c1, c2 = st.columns([4, 1])
        # Render the button before the keyed input: Streamlit otherwise rejects
        # updating that widget's session-state value on the same rerun.
        with c2:
            if st.button('Browse…', help='Opens the local file picker'):
                chosen = local_file_picker()
                if chosen:
                    st.session_state['quick_img'] = chosen
                    st.rerun()
                else:
                    st.info('File picker cancelled or unavailable. Paste the full disk image path.')
        with c1:
            image_path = st.text_input('Disk image path (.img/.dd/.raw)', key='quick_img',
                                       placeholder='C:\\Users\\YourName\\Downloads\\evidence.img' if os.name == 'nt' else '/home/kali/Downloads/evidence.img')
        label = st.text_input('Case label', value='Quick Recovery', key='quick_label')
        examiner = st.text_input('Examiner (optional)', key='quick_examiner')
        authorized = st.checkbox('I confirm this is an authorized evidence copy designated for analysis.',
                                 key='quick_authorized')
        st.caption('A JPEG or folder is not a disk image. To recover a deleted file, supply '
                   'an image containing the original filesystem and deleted-data remnants.')
    else:
        labels = {f"{x['case_id']} — {x.get('label') or Path(x['image_path']).name}": x['case_id']
                  for x in existing}
        case_id = labels[st.selectbox('Existing case', list(labels))]
        st.caption('The saved image baseline will be checked again before analysis/recovery.')

    method_choice = st.selectbox('Recovery strategy', list(QUICK_RECOVERY_METHODS),
                                 key='quick_recovery_method')
    method = QUICK_RECOVERY_METHODS[method_choice]
    st.caption(QUICK_RECOVERY_METHOD_HELP[method])
    if method in ('smart', 'cart') and not active_model_dir():
        st.info('No active CART model. The selector will use rule-v1 instead.')
    st.warning('The run may take time on large disks. Do not close this browser tab during recovery. '
               'Source media and disk image remain unchanged; output is stored separately.')
    if st.button('Analyze + recover', type='primary',
                 disabled=(source == 'New disk image' and (not image_path or not authorized))
                          or (os.name == 'nt' and bool(missing))):
        with st.status('Running guided recovery…', expanded=True) as status:
            try:
                rec, run = guided_recovery(image_path=image_path if source == 'New disk image' else None,
                                           case_id=case_id, authorized=authorized,
                                           examiner=examiner, label=label,
                                           method=method, progress=lambda message: st.write(message))
                status.update(label=f"Recovery {run['status']}",
                              state='complete' if run['status'] == 'completed' else 'error')
                st.session_state['quick_last_case_id'] = rec['case_id']
            except (RecoverXError, OSError, ValueError) as e:
                st.error(f'Quick Recovery could not finish: {e}')
                status.update(label='Quick Recovery stopped', state='error')
    recent_id = st.session_state.get('quick_last_case_id') or case_id
    if recent_id:
        try:
            case = open_case(recent_id)
            rec = case.load()
            if rec['runs']:
                run = rec['runs'][-1]
                st.subheader('Latest recovery results')
                c = st.columns(4)
                c[0].metric('Strategy used', run['selection']['strategy_used'])
                c[1].metric('Total outputs', run['metrics']['outputs'])
                c[2].metric('Distinct contents', len(run['canonical_files']))
                c[3].metric('Image unchanged', 'Yes' if run['source_unchanged'] else 'NO')
                if run['selection'].get('fallback'):
                    st.warning(run['selection']['fallback'])
                st.caption('Recovered outputs are not proof of exact reconstruction unless the original '
                           'hash (or ground truth) is available and matches.')
                all_files = [(engine, f) for engine in run['engine_runs'] for f in engine['files']]
                unique = []
                hashes = set()
                for engine, f in all_files:
                    if f['sha256'] not in hashes:
                        unique.append((engine, f))
                        hashes.add(f['sha256'])
                if unique:
                    st.dataframe(pd.DataFrame([{'engine': f['engine'],
                                                'name': f['recovered_name'],
                                                'size': f['size'], 'sha256': f['sha256'],
                                                'verification': f['integrity_state']}
                                               for _, f in unique]),
                                 hide_index=True, width='stretch')
                    st.subheader('Save a recovered file')
                    st.warning('Recovered files may contain malicious data. Download only files you trust; '
                               'RecoverX never opens or executes their contents.')
                    selected = st.selectbox('Recovered content', range(len(unique)),
                        format_func=lambda i: f"{unique[i][1]['recovered_name']} ({unique[i][1]['engine']}, "
                                              f"{unique[i][1]['size']:,} bytes)", key='quick_download_item')
                    engine, f = unique[selected]
                    path = safe_join(engine['output_dir'], f['relative_path'])
                    if not path.is_symlink() and path.is_file() and path.stat().st_size <= 40 * 1024 * 1024:
                        st.download_button('Download selected file', path.read_bytes(),
                                           file_name=Path(f['recovered_name']).name,
                                           mime='application/octet-stream')
                    else:
                        st.info('This file is unavailable or larger than 40 MiB. '
                                'Find it in the saved case run output folder.')
                st.download_button('Download PDF forensic report', generate_case_pdf(case),
                                   file_name=f"{rec['case_id']}_report.pdf", mime='application/pdf')
                st.info('Recovered files are saved in the case run output directory. '
                        'No automatic writing to the original disk occurs.')
                st.code(str(case.runs_dir() / run['run_id']))
        except (RecoverXError, FileNotFoundError) as e:
            st.error(str(e))


def page_cases():
    st.title("Case Management")
    with st.expander("Safe demo — generate a synthetic FAT16 image", expanded=False):
        st.caption("Creates a 48 MiB synthetic disk image with deleted files, a ground-truth manifest "
                   "and a new case. Needs mkfs.vfat, mtools and Sleuth Kit; no real device is modified.")
        if st.button("Generate demo image and create case"):
            from recoverx.demo import create_demo_case
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
                except RecoverXError as e:
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
    st.download_button("Export forensic case report (PDF)", generate_case_pdf(case),
                       file_name=f"{rec['case_id']}_report.pdf", mime="application/pdf")


def page_analysis():
    st.title("Forensic Analysis")
    case, rec = case_picker("fa_case")
    if not case:
        return
    if st.button("Run pre-recovery analysis (mmls / fsstat / fls, read-only)", type="primary"):
        try:
            with st.spinner("Checking image integrity and running TSK inspection…"):
                verify_case_evidence(case, operation="pre_recovery_analysis")
                a = analyze_image(rec["image_path"])
                verify_case_evidence(case, operation="post_recovery_analysis")
                rec = case.load()
                rec["analysis"] = {**a.to_dict(), "features": extract_features(a), "at": utcnow()}
                rec["status"] = a.status
                case.save(rec)
                case.event("analysis", status=a.status, fs_type=a.fs_type, deleted=len(a.deleted_entries))
        except RecoverXError as e:
            st.error(f"Analysis blocked: {e}")
            return
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
    st.title("Intelligent Recovery")
    case, rec = case_picker("ir_case")
    if not case:
        return
    md = active_model_dir()
    st.markdown(f"Active CART model: **{md.name if md else 'none'}**"
                + ("" if md else " — CART requests will transparently fall back to rule-v1."))
    mode = st.radio("Strategy selection", ["CART (automatic)", "Rule-based baseline (rule-v1)",
                                            "Fixed strategy", "Manual override"], horizontal=True)
    method = {"CART (automatic)": "cart", "Rule-based baseline (rule-v1)": "rule"}.get(mode)
    if mode == "Fixed strategy":
        method = st.selectbox("Fixed strategy", STRATEGIES)
    elif mode == "Manual override":
        method = "manual:" + st.selectbox("Strategy chosen by examiner", STRATEGIES)
    analyze_layout = st.checkbox("Inspect filesystem and partition offset before recovery", value=True,
                                 help="Recommended for interactive use, especially partitioned images. "
                                      "Benchmarks retain their original fixed-method timing configuration.")
    gt_path = st.text_input("Optional ground-truth manifest (JSON with deleted/allocated SHA-256 lists)",
                            value=rec.get('demo_ground_truth_path', ''))
    if gt_path.strip() and gt_path.strip() == rec.get('demo_ground_truth_path'):
        st.caption('Synthetic demo ground truth selected automatically; real evidence normally has no ground truth.')
    st.caption('Partitioned images: TSK supports sector offsets from analysis. PhotoRec uses its own detection; '
               'partition handling may require separate validation.')
    st.warning("Recovery runs real tools against the image (read-only) and may take minutes on large images. "
               "Output goes to a new run directory inside the case folder.")
    if st.button("Start recovery", type="primary"):
        gt = None
        if gt_path.strip():
            try:
                gt = json.loads(Path(gt_path.strip()).read_text())
            except (OSError, json.JSONDecodeError) as e:
                st.error(f"Ground truth not loaded: {e}")
                return
        from recoverx.recovery.orchestrator import run_recovery
        with st.status("Running recovery…", expanded=True) as s:
            try:
                run = run_recovery(case, method, ground_truth=gt, model_dir=md,
                                   analyze=analyze_layout, progress=lambda msg: st.write(msg))
                s.update(label=f"Run {run['run_id']} — {run['status']}",
                         state="complete" if run["status"] == "completed" else "error")
            except RecoverXError as e:
                st.error(f"Recovery blocked: {e}")
                s.update(label='Recovery blocked safely', state='error')
                return
        rec = case.load()
    if not rec["runs"]:
        not_measured("No recovery runs for this case")
        return
    run = rec["runs"][-1]
    sel = run["selection"]
    st.subheader(f"Latest run · {run['run_id']}")
    c = st.columns(4)
    c[0].metric("Method", sel["method"])
    c[1].metric("Strategy actually used", sel["strategy_used"])
    c[2].metric("Total time", f"{run['timing']['total_s']:.3f}s")
    c[3].metric("Source hash unchanged", "yes" if run["source_unchanged"] else "NO")
    if sel.get("fallback"):
        st.warning(sel["fallback"])
    if sel["method"].startswith("manual:"):
        st.info(f"Manual override. Rule-v1 would have recommended: **{sel.get('recommended')}**")
    st.markdown(f"**Rationale / decision path:** {sel['rationale']}")
    if run.get("features"):
        with st.expander("Pre-recovery features used"):
            st.dataframe(pd.DataFrame([run["features"]]).T.rename(columns={0: "value"}))
    st.dataframe(pd.DataFrame([{"engine": e["engine"], "status": e["status"], "version": e["tool_version"],
                                "files": len(e["files"]), "elapsed_s": e["elapsed_s"], "error": e["error"]}
                               for e in run["engine_runs"]]), hide_index=True)
    if run['status'] == 'evidence_changed':
        st.error('The source image changed during recovery. Do not use these outputs without a new evidence review.')
    st.json(run["metrics"])
    st.bar_chart(pd.Series({k: v for k, v in run["timing"].items() if k != "total_s"}, name="seconds"))


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
    st.dataframe(f, hide_index=True, width="stretch")
    st.download_button("Export CSV", f.to_csv(index=False), file_name=f"{rid}_files.csv", mime="text/csv")
    st.subheader("Distinct contents (deduplicated by SHA-256, provenance kept)")
    st.dataframe(pd.DataFrame(run["canonical_files"]), hide_index=True, width="stretch")


def page_training():
    st.title("Model Training")
    exps = experiments()
    if not exps:
        not_measured("No experiment with labels yet — run Benchmark Laboratory phase 1")
        return
    exp = st.selectbox("Experiment", exps, format_func=experiment_label)
    if archived_experiment(exp):
        st.info('Historical archived data: original experiment paths may refer to another machine. '
                'Results are read-only; generate a new local dataset to retrain or reproduce.')
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
    if c1.button("Retrain (phase 2: train/val only)", disabled=archived_experiment(exp)):
        from recoverx.benchmarking.experiment import Experiment
        cfg = read_json(exp / "experiment_config.json")
        Experiment(exp, Path(cfg["dataset_dir"])).phase2(progress=lambda s: None)
        st.rerun()
    if rep and c2.button("Install this model as the active application model"):
        import shutil
        src = Path(rep['model_dir'])
        if not src.is_dir():
            src = exp / 'models' / src.name
        if not (src / 'model.joblib').is_file() or not (src / 'meta.json').is_file():
            st.error('Archived model path is unavailable. Try Install included CART model on Overview.')
        else:
            dst = get_settings().models_dir / src.name
            if not dst.exists():
                shutil.copytree(src, dst)
            st.success(f"Installed {dst.name}")
    st.caption(RULE_POLICY_TEXT.replace("\n", "  \n"))


def page_benchmark():
    st.title("Benchmark Laboratory")
    exps = experiments()
    with st.expander("Launch / resume a benchmark (runs in background)"):
        name = st.text_input("Experiment folder name", value="exp1")
        dataset = st.text_input("Dataset directory", value=str(get_settings().datasets_dir / "v1"))
        reps = st.number_input("Repeats per method", 1, 10, 3)
        if st.button("Launch all phases"):
            try:
                name = safe_identifier(name)
            except RecoverXError as e:
                st.error(str(e))
                return
            exp_dir = get_settings().experiments_dir / name
            exp_dir.mkdir(parents=True, exist_ok=True)
            log = open(exp_dir / "launch.log", "a")
            subprocess.Popen([sys.executable, str(PROJECT_ROOT / "scripts" / "run_benchmarks.py"), "--exp", str(exp_dir),
                              "--dataset", dataset, "--repeats", str(reps), "all"], stdout=log, stderr=log,
                             cwd=PROJECT_ROOT, start_new_session=True)
            st.success("Launched. Progress appears below as records are written (refresh).")
    if not exps:
        not_measured("No experiments recorded")
        return
    exp = st.selectbox("Experiment", exps, format_func=experiment_label, key="bl_exp")
    if archived_experiment(exp):
        st.info('These are the saved, read-only exp1 research results. They have not been rerun on this computer.')
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
    if p3 and st.button("Recompute analysis from saved records", disabled=archived_experiment(exp)):
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
                                    "status": r["status"], "sha_before": r["image_sha256_before"][:16] + "…",
                                    "sha_after": r["image_sha256_after"][:16] + "…", "unchanged": r["source_unchanged"],
                                    "tools": ", ".join(f"{e['engine']} {e['tool_version']}" for e in r["engine_runs"])}
                                   for r in rec["runs"]]), hide_index=True, width="stretch")
    man = build_manifest(case)
    st.caption(man["disclaimer"])
    st.download_button("Export evidence manifest (JSON)", json.dumps(man, indent=2), file_name=f"{rec['case_id']}_manifest.json")
    st.download_button("Export forensic case report (PDF)", generate_case_pdf(case),
                       file_name=f"{rec['case_id']}_report.pdf", mime="application/pdf")


def page_diagnostics():
    st.title("Settings & Diagnostics")
    d = run_diagnostics()
    st.markdown(f"RecoverX {__version__} · Python {d['python']} · data home `{d['home']}`")
    if not active_model_dir() and bundled_model_dir():
        if st.button("Install bundled CART model"):
            try:
                st.success(f"Installed {install_bundled_model().name}")
            except RecoverXError as e:
                st.error(str(e))
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


def main():
    st.set_page_config(page_title="RecoverX", page_icon="🔎", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    # Windows release: surface ONLY Quick Recovery; all research pages remain
    # in the source and case data is still persisted for auditability.
    if os.name == 'nt' or os.environ.get('RECOVERX_SIMPLE_UI') == '1':
        st.markdown('<style>[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] '
                    '{display:none !important;}</style>', unsafe_allow_html=True)
        page_quick()
        return
    with st.sidebar:
        st.markdown("## RecoverX")
        st.caption("Deleted-file recovery strategy selection · TSK + PhotoRec + CART")
        advanced = st.checkbox('Show advanced research pages', value=False)
        choices = PAGES if advanced else [p for p in PAGES if p not in ('Model Training', 'Benchmark Laboratory')]
        page = st.radio("Navigate", choices, label_visibility="collapsed")
    {"Quick Recovery": page_quick, "Overview": page_overview, "Case Management": page_cases, "Forensic Analysis": page_analysis,
     "Intelligent Recovery": page_recovery, "Recovered Files": page_files, "Model Training": page_training,
     "Benchmark Laboratory": page_benchmark, "Evidence & Audit": page_audit,
     "Settings & Diagnostics": page_diagnostics}[page]()
