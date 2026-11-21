"""RecoverX v0.4 Quick Recovery — the single main workflow.

  1 Select source   2 Recovery method   3 Output folder   4 Start + live progress   5 Results

Every value shown comes from live device queries, persisted case records or
the running pipeline's events. Controls only exist when they do something.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import __version__
from ..config import get_settings
from ..diagnostics import run_diagnostics
from ..exceptions import RecoverXError
from ..forensic.case_store import build_manifest, list_cases, open_case
from ..forensic.image_validator import safe_join, validate_image
from ..ml.model_install import bundled_model_dir, install_bundled_model
from ..ml.selector import latest_model_dir
from ..recovery.validation import validate_file
from ..reporting.exports import csv_inventory
from ..reporting.pdf_report import generate_case_pdf
from ..usb import devices, win32
from ..usb.devices import human_size
from ..usb.imaging import validate_destination
from ..workflow import PIPELINE_STAGES, classify_outcome, current_quick_job, known_hashes_to_ground_truth, start_quick_job
from . import pickers
from .theme import CSS, bar_html, banner_html, e, header_html, kv_html, pipeline_html, stats_html, step_html

METHODS = [
    ("smart", "Smart Recovery",
     "CART chooses the first engine (rule-v1 if no model). If it fails or finds nothing, the other engine runs."),
    ("tsk", "TSK only", "The Sleuth Kit follows filesystem metadata: original names and folders. PhotoRec does not run."),
    ("photorec", "PhotoRec only", "Signature carving of unallocated space when metadata is gone. Names are not kept. TSK does not run."),
    ("combined", "TSK + PhotoRec", "Both engines run one after the other; results are merged by SHA-256. Most thorough."),
    ("cart", "Automatic (CART only)",
     "The trained CART model recommends a strategy. Preservation policy runs both engines; the recommendation is logged."),
    ("rule", "Automatic (rule-v1 only)",
     "The frozen rule-v1 selector recommends a strategy. Preservation policy runs both engines; the recommendation is logged."),
]
METHOD_LABEL = {k: label for k, label, _ in METHODS}
SOURCE_USB, SOURCE_IMAGE = "USB drive", "Disk image file"
IMAGE_NEW, IMAGE_CASE = "New image file", "Image from a previous case"
STAGE_LABELS = {"acquire": "Acquire image", "register": "Register evidence", "analyze": "Analyze filesystem",
                "recover": "Recover files", "verify": "Verify evidence", "export": "Export results"}
OUTCOME_TITLES = {"success": "Recovery complete", "partial": "Recovery partially complete", "no_files": "No files recovered",
                  "failed": "Recovery failed", "blocked": "Blocked for safety", "cancelled": "Cancelled",
                  "disconnected": "Device disconnected", "acquired_with_errors": "Image has unreadable sectors"}


def default_output_dir() -> str:
    docs = Path.home() / "Documents"
    return str((docs if docs.is_dir() else Path.home()) / "RecoverX Output")


@st.cache_data(ttl=90, show_spinner=False)
def _diagnostics() -> dict:
    d = run_diagnostics()
    return {"engines": {x["engine"]: bool(x["available"]) for x in d["engines"]},
            "versions": {x["engine"]: x["version"] for x in d["engines"]}}


def _chips(diag: dict) -> list[tuple[str, str]]:
    eng = diag["engines"]
    model = latest_model_dir(get_settings().models_dir)
    chips = [(f"TSK {diag['versions'].get('tsk') or ''}".strip() if eng.get("tsk") else "TSK missing",
              "ok" if eng.get("tsk") else "bad"),
             (("PhotoRec " + (diag["versions"].get("photorec") or "")).strip() if eng.get("photorec")
              else "PhotoRec unavailable", "ok" if eng.get("photorec") else "warn"),
             ("CART model ready" if model else "No CART model", "ok" if model else "warn")]
    if win32.IS_WINDOWS:
        chips.append(("Administrator" if win32.is_admin() else "Standard user · UAC for USB",
                      "ok" if win32.is_admin() else "warn"))
    return chips


# ------------------------------------------------------------------ step 1
def _load_devices(force: bool = False):
    if force or "rx_devices" not in st.session_state:
        try:
            st.session_state["rx_devices"] = devices.list_devices()
            st.session_state["rx_devices_error"] = None
        except OSError as exc:
            st.session_state["rx_devices"] = []
            st.session_state["rx_devices_error"] = str(exc)
        st.session_state["rx_devices_at"] = time.strftime("%H:%M:%S")
    return st.session_state["rx_devices"]


def _device_card(d: devices.DiskInfo) -> str:
    vols = ", ".join(f"{v.letter} {v.filesystem or 'RAW'}{(' “' + v.label + '”') if v.label else ''}" for v in d.volumes) \
        or "no mounted volume"
    why = f'<div class="why">⛔ {e(d.protected_reasons[0])}</div>' if d.protected_reasons else ""
    return (f'<div class="rx-dev{" blocked" if not d.selectable else ""}"><b>{e(d.name)}</b><br>'
            f'<span class="m">Disk {d.number} · {e(d.bus_type)} · {e(human_size(d.size))}</span><br>'
            f'<span class="m">{e(vols)}</span>{why}</div>')


def _step_source() -> dict:
    src: dict = {"ready": False}
    with st.container(key="rx-step-1"):
        head = st.empty()
        st.session_state.setdefault("rx_source", SOURCE_USB)
        kind = st.segmented_control("Source type", [SOURCE_USB, SOURCE_IMAGE], key="rx_source",
                                    label_visibility="collapsed") or SOURCE_USB
        src["kind"] = kind
        if kind == SOURCE_USB:
            _usb_source(src)
        else:
            _image_source(src)
        head.markdown(step_html(1, "Select source", "Recover from a connected USB flash drive, or from an existing raw disk image.",
                                done=bool(src.get("ready"))), unsafe_allow_html=True)
    return src


def _usb_source(src: dict):
    if not win32.IS_WINDOWS:
        _linux_capture()
        return
    c1, c2 = st.columns([5, 1.3], vertical_alignment="bottom")
    refresh = c2.button("Refresh", icon=":material/refresh:", width="stretch", help="Scan connected disks again")
    devs = _load_devices(force=refresh)
    c1.caption(f"Scanned at {st.session_state.get('rx_devices_at')} · only removable USB disks that are not "
               "system, boot or RecoverX disks can be selected.")
    if st.session_state.get("rx_devices_error"):
        st.error("Device discovery failed: " + st.session_state["rx_devices_error"])
    usable = [d for d in devs if d.selectable]
    if not usable:
        st.markdown('<div class="rx-empty">No eligible USB storage device found. Connect the USB flash drive '
                    'and press <b>Refresh</b>.</div>', unsafe_allow_html=True)
    else:
        by_number = {d.number: d for d in usable}
        if st.session_state.get("rx_disk") not in by_number:
            st.session_state["rx_disk"] = next(iter(by_number))
        with st.container(key="rx-pick-disk"):
            choice = st.radio("USB device", list(by_number), key="rx_disk", label_visibility="collapsed",
                              format_func=lambda n: f"{by_number[n].name} — {human_size(by_number[n].size)}",
                              captions=[f"Disk {d.number} · {d.bus_type} · "
                                        + (", ".join(f"{v.letter} {v.filesystem or 'RAW'}" for v in d.volumes) or "no drive letter")
                                        + (f" · S/N {d.serial}" if d.serial else "") for d in usable])
        disk = by_number.get(choice)
        if disk:
            src.update(ready=True, disk=disk)
            with st.expander(f"Device details · Disk {disk.number}", icon=":material/info:"):
                st.markdown(kv_html([("Physical disk", win32.physical_drive_path(disk.number)),
                                     ("Model", disk.name), ("Vendor / product", f"{disk.vendor} {disk.product}".strip() or "—"),
                                     ("Serial", disk.serial or "not reported"), ("Bus", disk.bus_type),
                                     ("Capacity", f"{human_size(disk.size)} ({disk.size:,} bytes)"),
                                     ("Logical sector", f"{disk.sector_size} bytes"), ("Partition style", disk.partition_style),
                                     ("Volumes", ", ".join(f"{v.letter} {v.filesystem} {human_size(v.size)}" for v in disk.volumes) or "none"),
                                     ("Partitions", "; ".join(f"#{p['number']} @ {p['offset']:,} B · {human_size(p['size'])}"
                                                              for p in disk.partitions if p.get('offset') is not None) or "not reported")]),
                            unsafe_allow_html=True)
    blocked = [d for d in devs if not d.selectable]
    if blocked:
        with st.expander(f"Protected storage ({len(blocked)}) — cannot be selected", icon=":material/shield:"):
            st.markdown('<div class="rx-grid">' + "".join(_device_card(d) for d in blocked) + "</div>",
                        unsafe_allow_html=True)


def _linux_capture():
    from ..acquisition import AcquisitionError, candidate_devices, capture_device
    st.info("On Linux, RecoverX images an unmounted, non-system device through polkit, then recovers from the "
            "image. Direct USB discovery with drive letters is the Windows workflow.")
    if st.button("Find unmounted devices", icon=":material/search:"):
        try:
            st.session_state["quick_devices"] = candidate_devices()
        except (AcquisitionError, OSError, ValueError) as exc:
            st.error(str(exc))
    found = st.session_state.get("quick_devices", [])
    if found:
        labels = {f"{x['path']} — {x['size'] / 2**30:.2f} GiB — {x['fstype']} ({x['type']})": x["path"] for x in found}
        chosen = st.selectbox("Unmounted source device (never the system disk)", list(labels))
        ok = st.checkbox("I am authorized to examine this device and confirmed it is not my system disk.",
                         key="rx_linux_auth")
        if st.button("Capture read-only image", disabled=not ok):
            try:
                with st.spinner("Creating a byte-for-byte image. Do not disconnect the source…"):
                    img = capture_device(labels[chosen])
                st.session_state["quick_img"] = str(img)
                st.success(f"Image captured: {img}. Switch the source to “Disk image file” to recover from it.")
            except AcquisitionError as exc:
                st.error(str(exc))


def _image_source(src: dict):
    cases = list_cases()
    modes = [IMAGE_NEW, IMAGE_CASE] if cases else [IMAGE_NEW]
    if st.session_state.get("rx_image_mode") not in modes:
        st.session_state["rx_image_mode"] = IMAGE_NEW
    mode = st.radio("Image", modes, horizontal=True, key="rx_image_mode",
                    label_visibility="collapsed")
    if mode == IMAGE_NEW:
        c1, c2 = st.columns([5, 1.3], vertical_alignment="bottom")
        with c2:
            if st.button("Browse…", icon=":material/folder_open:", width="stretch", key="rx_browse_img"):
                chosen = pickers.pick_image_file()
                if chosen:
                    st.session_state["quick_img"] = chosen
                    st.rerun()
                st.toast("File picker cancelled or unavailable — paste the full path instead.")
        with c1:
            path = st.text_input("Disk image path (.img / .dd / .raw / .bin / .001)", key="quick_img",
                                 placeholder=r"C:\Evidence\usb-copy.img" if os.name == "nt" else "/home/user/usb-copy.img")
        if path.strip():
            try:
                img = validate_image(path.strip())
                st.caption(f"✓ {img.name} · {human_size(img.stat().st_size)} · the image is only read, never modified.")
                src.update(ready=True, image_path=str(img))
            except RecoverXError as exc:
                st.error(str(exc))
        st.caption("A single photo or folder is not a disk image. Use a raw image of the whole USB drive or partition.")
    else:
        labels = {c["case_id"]: f"{c.get('label') or Path(c['image_path']).name} · {c['case_id']} · {len(c.get('runs', []))} run(s)"
                  for c in cases}
        if st.session_state.get("rx_case") not in labels:
            st.session_state["rx_case"] = next(iter(labels))
        cid = st.selectbox("Previous case", list(labels), format_func=labels.get, key="rx_case")
        rec = next(c for c in cases if c["case_id"] == cid)
        st.caption(f"Image {rec['image_path']} · baseline SHA-256 {str(rec.get('image_sha256_initial'))[:16]}… "
                   "The image is re-hashed and must match before any new run.")
        src.update(ready=True, case_id=cid, previous=True)


# ------------------------------------------------------------------ step 2
def _step_method(diag: dict) -> dict:
    with st.container(key="rx-step-2"):
        head = st.empty()
        with st.container(key="rx-pick-method"):
            method = st.radio("Recovery method", [k for k, _, _ in METHODS], key="rx_method",
                              format_func=METHOD_LABEL.get, captions=[c for _, _, c in METHODS],
                              label_visibility="collapsed")
        eng = diag["engines"]
        need = {"tsk": ["tsk"], "photorec": ["photorec"]}.get(method, ["tsk", "photorec"])
        missing = [n for n in need if not eng.get(n)]
        blocked = None
        if method in ("tsk", "photorec") and missing:
            blocked = f"{METHOD_LABEL[method]} needs {missing[0].upper()}, which is not available."
            st.error(blocked + (" Run SETUP_WINDOWS.cmd." if missing[0] == "tsk" else
                                " Install testdisk in your default WSL Ubuntu (see the installation guide)."))
        elif missing and len(missing) == len(need):
            blocked = "No recovery engine is available. Run SETUP_WINDOWS.cmd."
            st.error(blocked)
        elif missing:
            st.warning(f"{', '.join(m.upper() for m in missing)} unavailable: this method will run the remaining engine "
                       "and the run will be reported as incomplete.")
        model = latest_model_dir(get_settings().models_dir)
        if method == "cart" and not model:
            blocked = "Automatic (CART only) needs the trained CART model."
            st.warning(blocked)
            if bundled_model_dir() and st.button("Install the bundled CART model", icon=":material/download:"):
                with st.spinner("Re-evaluating bundled training records and installing the JSON model…"):
                    install_bundled_model()
                st.rerun()
        elif method == "smart" and not model:
            st.info("No CART model installed: Smart Recovery will use rule-v1 for the first choice (logged as a fallback).")
        head.markdown(step_html(2, "Recovery method", "All six RecoverX strategies. Every decision and engine run is logged.",
                                done=not blocked), unsafe_allow_html=True)
    return {"method": method, "blocked": blocked}


# ------------------------------------------------------------------ step 3
def _step_output(src: dict) -> dict:
    out = {"ready": False}
    with st.container(key="rx-step-3"):
        head = st.empty()
        head.markdown(step_html(3, "Choose output folder",
                                "Recovered files, reports and (for USB) the disk image are saved here — never on the source."),
                      unsafe_allow_html=True)
        st.session_state.setdefault("rx_output", default_output_dir())
        c1, c2 = st.columns([5, 1.3], vertical_alignment="bottom")
        with c2:
            if st.button("Browse…", icon=":material/folder:", width="stretch", key="rx_browse_out"):
                chosen = pickers.pick_folder()
                if chosen:
                    st.session_state["rx_output"] = chosen
                    st.rerun()
                st.toast("Folder picker cancelled or unavailable — type the folder path instead.")
        with c1:
            path = st.text_input("Output folder", key="rx_output")
        p = Path(path.strip()).expanduser() if path.strip() else None
        if not p:
            st.error("Choose an output folder.")
            return out
        disk = src.get("disk")
        required = disk.size if disk else 0
        problems = validate_destination(p / "disk-images" if disk else p, required_bytes=required,
                                        source_disk=disk.number if disk else None) if p.is_absolute() else \
            ["Choose an absolute folder path (for example C:\\RecoverX Output)."]
        if src.get("image_path"):
            img = Path(src["image_path"]).resolve()
            if p.resolve() == img.parent or img.parent in p.resolve().parents:
                st.caption("Note: the output folder is next to the evidence image; outputs go into separate subfolders.")
        if problems:
            for prob in problems:
                st.error(prob)
            return out
        probe = p if p.exists() else next((q for q in p.parents if q.exists()), p)
        import shutil
        free = shutil.disk_usage(probe).free
        info = [("Free space", human_size(free))]
        if disk:
            try:
                dest_disks = sorted(win32.disks_for_path(str(probe)))
                info.append(("Destination disk", ", ".join(f"Disk {d}" for d in dest_disks)))
            except OSError:
                pass
            info.append(("Image size", human_size(disk.size)))
        st.markdown(stats_html(info), unsafe_allow_html=True)
        out.update(ready=True, path=str(p))
        head.markdown(step_html(3, "Choose output folder",
                                "Recovered files, reports and (for USB) the disk image are saved here — never on the source.",
                                done=True), unsafe_allow_html=True)
    return out


# ------------------------------------------------------------------ step 4
@st.dialog("Confirm read-only USB acquisition", width="large")
def _confirm_usb(params: dict):
    disk = params["disk"]
    with st.spinner("Re-checking the device…"):
        try:
            live = devices.find_disk(disk.number, devices.list_devices(extra_protected_paths=[params["output_dir"]]))
        except OSError as exc:
            st.error(f"Device discovery failed: {exc}")
            return
    problem = devices.identity_mismatch(disk.identity(), live)
    if problem:
        st.error(problem)
        if st.button("Close"):
            st.session_state.pop("rx_devices", None)
            st.rerun()
        return
    st.markdown(kv_html([("Device", win32.physical_drive_path(live.number)), ("Model", live.name),
                         ("Serial", live.serial or "not reported"), ("Bus", live.bus_type),
                         ("Capacity", f"{human_size(live.size)} ({live.size:,} bytes)"),
                         ("Volumes", ", ".join(f"{v.letter} {v.filesystem}" for v in live.volumes) or "none"),
                         ("Image saved to", str(Path(params["output_dir"]) / "disk-images")),
                         ("Method after imaging", METHOD_LABEL[params["method"]])]), unsafe_allow_html=True)
    st.warning("RecoverX reads this disk with read-only access and never formats, initialises or writes to it. "
               "Read-only access cannot stop Windows or other programs from writing to its mounted volumes: "
               "close Explorer windows and other programs using the drive, and do not unplug it during imaging. "
               "Use a hardware write blocker when write protection must be guaranteed.")
    if not win32.is_admin():
        st.info("Windows will show an administrator permission prompt (UAC). Only the imaging worker is elevated; "
                "if you decline, nothing is read or written.")
    ok = st.checkbox(f"Yes — image Disk {live.number} ({live.name}, {human_size(live.size)}"
                     f"{', S/N ' + live.serial if live.serial else ''}). I own it or am authorized to examine it.")
    c1, c2 = st.columns(2)
    if c1.button("Start read-only imaging", type="primary", disabled=not ok, icon=":material/play_arrow:", width="stretch"):
        try:
            start_quick_job(**{**params, "disk": live, "confirmed_identity": live.identity()})
            st.session_state.pop("rx_seen_job", None)
            st.rerun()
        except (RecoverXError, ValueError, OSError) as exc:
            st.error(str(exc))
    if c2.button("Go back", width="stretch"):
        st.rerun()


def _step_start(src: dict, meth: dict, out: dict):
    job = current_quick_job()
    active = bool(job and not job.done.is_set())
    with st.container(key="rx-step-4"):
        st.markdown(step_html(4, "Start recovery", "Live progress comes from the actual imaging and engine events."),
                    unsafe_allow_html=True)
        if not active:
            with st.expander("Case details and known originals (optional)", icon=":material/badge:"):
                c1, c2 = st.columns(2)
                c1.text_input("Case label", key="rx_label", placeholder="e.g. Holiday USB stick")
                c2.text_input("Examiner", key="rx_examiner")
                st.text_area("Known original SHA-256 hashes (one per line)", key="rx_hashes", height=90,
                             help="If you have the originals' hashes, matching outputs are marked as verified exact matches.")
                if src.get("kind") == SOURCE_USB:
                    st.checkbox("After imaging, read the USB drive a second time to confirm it did not change "
                                "(doubles imaging time)", key="rx_reread")
            if not src.get("previous"):
                st.checkbox("I own this media or am authorized to examine it, and it is designated for analysis.",
                            key="rx_authorized")
            hashes_ok = True
            try:
                known_hashes_to_ground_truth(st.session_state.get("rx_hashes", ""))
            except ValueError as exc:
                st.error(f"Known hashes: {exc}")
                hashes_ok = False
            ready = (src.get("ready") and out.get("ready") and not meth.get("blocked") and hashes_ok
                     and (src.get("previous") or st.session_state.get("rx_authorized")))
            usb = src.get("kind") == SOURCE_USB and src.get("disk")
            label = "Image USB drive & recover" if usb else "Start recovery"
            if st.button(label, type="primary", disabled=not ready, icon=":material/rocket_launch:", key="rx_start"):
                params = {"method": meth["method"], "output_dir": out["path"],
                          "label": st.session_state.get("rx_label", ""), "examiner": st.session_state.get("rx_examiner", ""),
                          "known_hashes": st.session_state.get("rx_hashes", ""),
                          "authorized": bool(st.session_state.get("rx_authorized")) or bool(src.get("previous"))}
                if usb:
                    params.update(source="usb", disk=src["disk"], reread_source=bool(st.session_state.get("rx_reread")))
                    _confirm_usb(params)
                else:
                    if src.get("previous"):
                        params.update(source="case", case_id=src["case_id"])
                    else:
                        params.update(source="image", image_path=src["image_path"])
                    try:
                        start_quick_job(**params)
                        st.session_state.pop("rx_seen_job", None)
                        st.rerun()
                    except (RecoverXError, ValueError, OSError) as exc:
                        st.error(str(exc))
            if not ready:
                missing = [m for m, ok in (("a source", src.get("ready")), ("a valid output folder", out.get("ready")),
                                           ("an available method", not meth.get("blocked")),
                                           ("authorization", src.get("previous") or st.session_state.get("rx_authorized")))
                           if not ok]
                st.caption("To start, provide " + ", ".join(missing) + "." if missing else "")
        if job:
            _live_progress()


def _pipeline_states(snap: dict) -> list[tuple[str, str]]:
    stages = [s for s in PIPELINE_STAGES if s != "acquire" or snap["params"].get("source") == "usb"]
    current = snap["stage"] if snap["stage"] in stages else stages[0]
    idx = stages.index(current)
    out = []
    for i, s in enumerate(stages):
        if snap["done"]:
            if snap["outcome"] in ("success",) or i < idx:
                state = "done"
            elif i == idx:
                state = "done" if snap["outcome"] in ("no_files", "partial") else "fail"
            else:
                state = ""
        else:
            state = "done" if i < idx else "active" if i == idx else ""
        out.append((STAGE_LABELS[s], state))
    return out


@st.fragment(run_every=1.0)
def _live_progress():
    job = current_quick_job()
    if job is None:
        return
    snap = job.snapshot()
    if snap["done"]:
        if st.session_state.get("rx_seen_job") != id(job):
            st.session_state["rx_seen_job"] = id(job)
            if snap["case_id"]:
                st.session_state["quick_last_case_id"] = snap["case_id"]
            st.rerun()
        st.markdown(pipeline_html(_pipeline_states(snap)), unsafe_allow_html=True)
        if snap["run"] is None:
            st.markdown(banner_html(snap["outcome"], OUTCOME_TITLES.get(snap["outcome"], snap["outcome"]),
                                    " " + snap["message"]), unsafe_allow_html=True)
        else:
            st.caption(f"Finished at {snap['finished_at'][11:19]} UTC — see Recovery results below.")
        acq = snap.get("acquisition")
        if acq and snap["outcome"] == "acquired_with_errors":
            st.markdown(stats_html([("Image", acq.get("image_path")), ("Unreadable", f"{acq.get('unreadable_bytes', 0):,} bytes")]),
                        unsafe_allow_html=True)
            def use_image(path=acq.get("image_path")):
                st.session_state.update(rx_source=SOURCE_IMAGE, rx_image_mode=IMAGE_NEW, quick_img=path)
            st.button("Use this image as the source", icon=":material/arrow_forward:", on_click=use_image)
        with st.expander("Operation log", icon=":material/list_alt:"):
            st.dataframe(pd.DataFrame(snap["events"]), hide_index=True, width="stretch")
        return
    st.markdown(pipeline_html(_pipeline_states(snap)), unsafe_allow_html=True)
    elapsed = _elapsed(snap["started_at"])
    if snap["stage"] == "acquire":
        a = snap.get("acquisition_status") or {}
        stage = a.get("stage", "starting")
        if stage in ("waiting_for_permission", "starting", "verifying_identity"):
            st.markdown(bar_html(None), unsafe_allow_html=True)
            st.caption("Waiting for administrator approval in the Windows permission prompt…"
                       if stage == "waiting_for_permission" else "Verifying the disk identity and destination…")
        else:
            done, total = int(a.get("bytes_done") or 0), int(a.get("bytes_total") or 0)
            rate = float(a.get("rate_bps") or 0)
            st.markdown(bar_html(done / total if total else None), unsafe_allow_html=True)
            label = {"imaging": "Reading the USB drive", "verifying_image": "Verifying the image on the destination disk",
                     "rereading_source": "Re-reading the USB drive to confirm it did not change"}.get(stage, stage)
            eta = f"{(total - done) / rate:,.0f} s" if rate > 0 and stage == "imaging" and total else "—"
            st.markdown(stats_html([("Stage", label), ("Copied" if stage == "imaging" else "Processed",
                                                       f"{human_size(done)} of {human_size(total)}"),
                                    ("Throughput", f"{rate / 2**20:,.1f} MiB/s" if stage == "imaging" else "—"),
                                    ("Remaining", eta), ("Unreadable", f"{int(a.get('unreadable_bytes') or 0):,} B"),
                                    ("Elapsed", elapsed)]), unsafe_allow_html=True)
    else:
        events = snap["events"]
        last = next((ev for ev in reversed(events) if ev.get("event") or ev.get("detail")), {})
        planned = next((ev.get("initial_engines") for ev in reversed(events) if ev.get("event") == "strategy_selected"), None)
        finished = [ev for ev in events if ev.get("event") == "engine_finished"]
        running = next((ev for ev in reversed(events) if ev.get("event") == "engine_started"), None)
        st.markdown(bar_html(None), unsafe_allow_html=True)
        detail = last.get("detail") or (last.get("event") or "").replace("_", " ")
        items = [("Now", detail or "Working"), ("Elapsed", elapsed)]
        if planned:
            items.append(("Engines finished", f"{len(finished)} of {max(len(planned), len(finished) + (1 if running and len(finished) < len(planned) else 0))}"))
        if running and (not finished or finished[-1].get("t", "") < running.get("t", "")):
            items.append(("Running", f"{running.get('engine', '').upper()} (the tool does not report byte progress)"))
        st.markdown(stats_html(items), unsafe_allow_html=True)
        if finished:
            st.dataframe(pd.DataFrame([{"engine": f.get("engine"), "status": f.get("engine_status"), "files": f.get("files"),
                                        "error": f.get("error")} for f in finished]), hide_index=True, width="stretch")
    if st.button("Cancel safely", icon=":material/stop_circle:", disabled=snap["cancelling"], key="rx_cancel"):
        job.request_cancel()
        st.toast("Cancelling — the current tool is stopped and partial output is preserved.")
    if snap["cancelling"]:
        st.caption("Cancellation requested. Waiting for the current step to stop cleanly…")
    with st.expander("Live operation log", icon=":material/terminal:"):
        st.dataframe(pd.DataFrame(snap["events"][-60:]), hide_index=True, width="stretch")


def _elapsed(started: str) -> str:
    from datetime import datetime, timezone
    try:
        s = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
        return f"{int(s // 60)}m {int(s % 60):02d}s"
    except ValueError:
        return "—"


# ------------------------------------------------------------------ step 5
def _export_files(run: dict) -> dict | None:
    exp = run.get("export")
    if not exp:
        return None
    p = Path(exp.get("output_dir", "")) / "export.json"
    try:
        return json.loads(p.read_text()) if p.is_file() else {**exp, "files": []}
    except (OSError, json.JSONDecodeError):
        return {**exp, "files": []}


MATCH_LABELS = {"verified_exact_match": "✓ exact match", "known_allocated_file": "allocated original",
                "unverified": "no match", "ground_truth_unavailable": "not checked", "invalid_or_unreadable": "unreadable"}


def _result_rows(run: dict, export: dict | None) -> list[dict]:
    if export and export.get("files"):
        return [{"name": f.get("original_name") or f.get("recovered_name"), "engine": f.get("engine"),
                 "type": (f.get("validation") or {}).get("format"), "size": f.get("size"),
                 "validation": (f.get("validation") or {}).get("state"), "detail": (f.get("validation") or {}).get("reason"),
                 "match": MATCH_LABELS.get(f.get("integrity_state"), f.get("integrity_state")), "copied": f.get("copy_verified"), "duplicates": len(f.get("duplicates") or []),
                 "sha256": f.get("sha256"), "path": f.get("exported_path")} for f in export["files"]]
    rows, seen = [], set()
    for er in run.get("engine_runs", []):
        for f in er.get("files", []):
            if f["sha256"] in seen:
                continue
            seen.add(f["sha256"])
            try:
                path = safe_join(er["output_dir"], f["relative_path"])
            except RecoverXError:
                continue
            v = validate_file(path) if path.is_file() else {"state": "invalid", "format": f.get("extension"), "reason": "missing"}
            rows.append({"name": f.get("original_name") or f.get("recovered_name"), "engine": f.get("engine"),
                         "type": v.get("format"), "size": f.get("size"), "validation": v["state"], "detail": v["reason"],
                         "match": MATCH_LABELS.get(f.get("integrity_state"), f.get("integrity_state")), "copied": None, "duplicates": 0, "sha256": f["sha256"],
                         "path": str(path)})
    return rows


def _preview(path: Path, fmt: str | None):
    if not path.is_file() or path.is_symlink():
        st.caption("File not available for preview.")
        return
    size = path.stat().st_size
    if fmt in ("jpeg", "png", "gif") and size <= 25 * 2**20:
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 60_000_000
            with Image.open(path) as im:
                im.thumbnail((640, 480))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, format="PNG")
            st.image(buf.getvalue(), width=360,
                     caption="Safe preview: decoded and re-encoded thumbnail (original bytes are not rendered)")
        except Exception as exc:  # damaged images are common in recovery
            st.caption(f"Preview unavailable: the image data could not be decoded ({type(exc).__name__}).")
    elif fmt in ("txt", "text", "csv", "log") and size <= 5 * 2**20:
        with open(path, "rb") as f:
            st.code(f.read(4096).decode("utf-8", errors="replace"), language="text")
    else:
        st.caption("No inline preview for this type. RecoverX never opens or executes recovered documents.")


def _step_results(src: dict):
    with st.container(key="rx-step-5"):
        st.markdown(step_html(5, "Recovery results", "Recovered files, integrity verification, reports and audit trail."),
                    unsafe_allow_html=True)
        job = current_quick_job()
        if job and not job.done.is_set():
            st.markdown('<div class="rx-empty">Results will appear here when the current operation finishes.</div>',
                        unsafe_allow_html=True)
            return
        case_id = src.get("case_id") if src.get("previous") else st.session_state.get("quick_last_case_id")
        if not case_id:
            st.markdown('<div class="rx-empty">No results yet. Complete steps 1–4 to recover files.</div>',
                        unsafe_allow_html=True)
            return
        try:
            case = open_case(case_id)
            rec = case.load()
        except (RecoverXError, FileNotFoundError, ValueError) as exc:
            st.error(f"Cannot open case {case_id}: {exc}")
            return
        if not rec.get("runs"):
            st.markdown('<div class="rx-empty">This case has no recovery runs yet.</div>', unsafe_allow_html=True)
            _audit_expanders(case, rec, None)
            return
        run = rec["runs"][-1]
        export = _export_files(run)
        outcome, message = classify_outcome(run, export)
        st.markdown(banner_html(outcome, OUTCOME_TITLES.get(outcome, outcome), " " + message), unsafe_allow_html=True)
        rows = _result_rows(run, export)
        sel = run.get("selection") or {}
        c = st.columns(5)
        c[0].metric("Distinct files", len(rows))
        c[1].metric("Structurally valid", sum(1 for r in rows if r["validation"] == "valid"))
        c[2].metric("Duplicates merged", run["metrics"].get("duplicate_outputs", 0))
        c[3].metric("Outputs (all engines)", run["metrics"].get("outputs", 0))
        c[4].metric("Evidence unchanged", "Yes" if run.get("source_unchanged") else "NO")
        if run["metrics"].get("ground_truth"):
            st.success(f"Known-original check: {run['metrics'].get('exact_recovered', 0)} of {run['metrics'].get('gt_files', 0)} "
                       "supplied hashes matched a recovered file exactly.")
        if export:
            out_dir = export.get("output_dir")
            st.markdown(stats_html([("Saved to", out_dir),
                                    ("Copies verified", f"{export.get('copied_ok')} of {export.get('distinct_files')}"),
                                    ("Engines", " → ".join(e.upper() for e in sel.get("engines_attempted") or []) or "none")]),
                        unsafe_allow_html=True)
        b = st.columns(3)
        if export and Path(export.get("output_dir", "")).is_dir():
            if b[0].button("Open output folder", icon=":material/folder_open:", width="stretch"):
                if not pickers.open_folder(export["output_dir"]):
                    st.toast("Could not open the folder automatically.")
        pdf_key = f"rx_pdf_{case.id}_{run['run_id']}"
        if pdf_key not in st.session_state:
            st.session_state[pdf_key] = generate_case_pdf(case)
        b[1].download_button("PDF forensic report", st.session_state[pdf_key], file_name=f"{case.id}_RecoverX_report.pdf",
                             mime="application/pdf", icon=":material/picture_as_pdf:", width="stretch")
        b[2].download_button("JSON manifest", json.dumps(build_manifest(case), indent=2, default=str),
                             file_name=f"{case.id}_manifest.json", mime="application/json", icon=":material/data_object:",
                             width="stretch")
        if rows:
            df = pd.DataFrame(rows)
            f1, f2, f3 = st.columns([2, 2, 3])
            types = f1.multiselect("Type", sorted(df["type"].fillna("unknown").unique()), placeholder="All types")
            states = f2.multiselect("Validation", sorted(df["validation"].fillna("unknown").unique()), placeholder="All")
            q = f3.text_input("Search name or SHA-256", placeholder="e.g. IMG_ or 3fa2…")
            view = df
            if types:
                view = view[view["type"].fillna("unknown").isin(types)]
            if states:
                view = view[view["validation"].fillna("unknown").isin(states)]
            if q:
                ql = q.lower()
                view = view[view.apply(lambda r: ql in f"{r['name']} {r['sha256']}".lower(), axis=1)]
            st.dataframe(view.drop(columns=["path"]), hide_index=True, width="stretch",
                         column_config={"size": st.column_config.NumberColumn("size (bytes)", format="%d"),
                                        "sha256": st.column_config.TextColumn("SHA-256", width="medium")})
            st.download_button("Export inventory (CSV)", csv_inventory(view.drop(columns=["path"]).to_dict("records")),
                               file_name=f"{run['run_id']}_inventory.csv", mime="text/csv", icon=":material/table:")
            if len(view):
                idx = st.selectbox("Inspect a recovered file", list(view.index),
                                   format_func=lambda i: f"{df.loc[i, 'name']} · {df.loc[i, 'engine']} · {df.loc[i, 'size']:,} B")
                row = df.loc[idx]
                path = Path(row["path"]) if row["path"] else None
                i1, i2 = st.columns([3, 2])
                with i1:
                    st.markdown(kv_html([("Name", row["name"]), ("Engine", row["engine"]), ("Type", row["type"]),
                                         ("Validation", f"{row['validation']} — {row['detail']}"),
                                         ("Known-original match", row["match"]), ("SHA-256", row["sha256"]),
                                         ("Saved at", row["path"] or "—")]), unsafe_allow_html=True)
                    if path and path.is_file() and path.stat().st_size <= 32 * 2**20:
                        st.download_button("Download this file", path.read_bytes(), file_name=Path(str(row["name"])).name,
                                           mime="application/octet-stream", icon=":material/download:")
                    st.caption("Recovered files can contain malicious content. RecoverX never executes them.")
                with i2:
                    if path and st.toggle("Show safe preview", key=f"rx_prev_{idx}"):
                        _preview(path, row["type"])
        _audit_expanders(case, rec, run)


def _audit_expanders(case, rec: dict, run: dict | None):
    if run:
        sel = run.get("selection") or {}
        with st.expander("Strategy, model prediction and fallbacks", icon=":material/psychology:"):
            st.markdown(kv_html([("Requested method", METHOD_LABEL.get(run["method"], run["method"])),
                                 ("Recommended strategy", sel.get("recommended") or "— (fixed strategy)"),
                                 ("Applied strategy", sel.get("strategy_used")), ("Selector", sel.get("model_version") or "none"),
                                 ("Rationale", sel.get("rationale")), ("Initial engines", ", ".join(sel.get("initial_engines") or [])),
                                 ("Engines attempted", " → ".join(sel.get("engines_attempted") or [])),
                                 ("Selector fallback", sel.get("fallback") or "none"),
                                 ("Engine fallback (Smart)", sel.get("engine_fallback") or "none"),
                                 ("Safety override", sel.get("safety_override") or "none"),
                                 ("Reliability", sel.get("reliability") or "—")]), unsafe_allow_html=True)
            if run.get("features"):
                st.dataframe(pd.DataFrame([run["features"]]).T.rename(columns={0: "value"}), width="stretch")
            if sel.get("leaf_class_fractions"):
                st.caption("Training-leaf class fractions (not a confidence or recovery probability)")
                st.json(sel["leaf_class_fractions"])
        with st.expander("Engine logs", icon=":material/terminal:"):
            for er in run.get("engine_runs", []):
                st.markdown(f"**{er['engine'].upper()}** · {er['status']} · {len(er['files'])} outputs · "
                            f"{er['elapsed_s']:.1f}s · version {er.get('tool_version') or 'unknown'}")
                if er.get("error"):
                    st.error(er["error"])
                for w in er.get("warnings") or []:
                    st.warning(w)
                for cmd in er.get("commands", []):
                    st.code(" ".join(cmd["args"]) + f"\n# exit {cmd['returncode']} · {cmd['elapsed_s']}s\n"
                            + (cmd.get("stderr") or "")[-1500:], language="bash")
            for w in run.get("warnings") or []:
                st.warning(w)
        a = run.get("analysis")
        with st.expander("Partitions and filesystem analysis", icon=":material/storage:"):
            if a:
                st.markdown(kv_html([("Status", a["status"]), ("Filesystem", a.get("fs_type") or "not detected"),
                                     ("Sector offset used", a.get("sector_offset")),
                                     ("Deleted entries (metadata)", len(a.get("deleted_entries") or []))]), unsafe_allow_html=True)
                if a.get("partitions"):
                    st.dataframe(pd.DataFrame(a["partitions"]), hide_index=True, width="stretch")
                if a.get("fsstat_excerpt"):
                    st.code(a["fsstat_excerpt"], language="text")
            else:
                st.caption("No analysis recorded for this run.")
    acq = rec.get("acquisition")
    if acq:
        with st.expander("USB acquisition record", icon=":material/usb:"):
            disk = acq.get("disk") or {}
            st.markdown(kv_html([("Source", f"Disk {disk.get('number')} · {disk.get('name')} · {disk.get('bus_type')}"),
                                 ("Serial", disk.get("serial") or "not reported"), ("Status", acq.get("status")),
                                 ("Bytes copied", f"{acq.get('bytes_copied', 0):,} of {acq.get('size', 0):,}"),
                                 ("Source-stream SHA-256", acq.get("source_stream_sha256")),
                                 ("Image SHA-256 (destination re-read)", acq.get("image_sha256")),
                                 ("Destination verified", "yes" if acq.get("image_verified") else "NO"),
                                 ("Source re-read", acq.get("source_reread_sha256") or "not performed"),
                                 ("Unreadable bytes", acq.get("unreadable_bytes", 0)),
                                 ("Throughput", f"{acq.get('throughput_mib_s')} MiB/s"),
                                 ("Partition scheme", (acq.get("partition_layout") or {}).get("scheme")),
                                 ("Record file", acq.get("record_path"))]), unsafe_allow_html=True)
            layout = (acq.get("partition_layout") or {}).get("partitions")
            if layout:
                st.dataframe(pd.DataFrame(layout), hide_index=True, width="stretch")
            for line in acq.get("limitations") or []:
                st.caption(line)
    with st.expander("Evidence integrity and audit trail", icon=":material/verified_user:"):
        st.markdown(kv_html([("Case", rec["case_id"]), ("Image", rec["image_path"]),
                             ("Baseline SHA-256", rec.get("image_sha256_initial")),
                             ("SHA-256 before run", (run or {}).get("image_sha256_before") or "—"),
                             ("SHA-256 after run", (run or {}).get("image_sha256_after") or "—"),
                             ("Last check", json.dumps(rec.get("last_hash_check") or {}))]), unsafe_allow_html=True)
        ev = case.events()
        if ev:
            st.dataframe(pd.DataFrame(ev), hide_index=True, width="stretch")


# ------------------------------------------------------------------ page
def render():
    st.markdown(CSS, unsafe_allow_html=True)
    diag = _diagnostics()
    st.markdown(header_html(__version__, _chips(diag)), unsafe_allow_html=True)
    src = _step_source()
    meth = _step_method(diag)
    out = _step_output(src)
    _step_start(src, meth, out)
    _step_results(src)
