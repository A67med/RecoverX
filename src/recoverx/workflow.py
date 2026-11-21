"""Quick Recovery pipeline: [USB acquisition] → case → recovery → verified export.

One pipeline per server process runs in a background thread; Streamlit reruns
only read ``snapshot()``. Every stage reported to the UI comes from a real
event (acquisition byte counters, orchestrator stage callbacks, export
results). Nothing is estimated or simulated.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_settings
from .exceptions import RecoverXError
from .forensic.case_store import create_case, open_case
from .ml.selector import latest_model_dir
from .models import utcnow
from .recovery.export import export_run
from .recovery.orchestrator import run_recovery, validate_ground_truth

METHODS = ("smart", "tsk", "photorec", "combined", "cart", "rule")
PIPELINE_STAGES = ["acquire", "register", "analyze", "recover", "verify", "export"]


def known_hashes_to_ground_truth(text: str) -> dict | None:
    import re
    hashes = sorted({h.lower() for h in re.findall(r"\b[0-9a-fA-F]{64}\b", text or "")})
    if not hashes:
        return None
    gt = {"deleted": [{"id": f"known-{i + 1}", "sha256": h} for i, h in enumerate(hashes)], "allocated": []}
    validate_ground_truth(gt)
    return gt


@dataclass
class QuickJob:
    params: dict
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    events: list[dict] = field(default_factory=list)
    stage: str = "starting"
    acquisition: dict | None = None
    acquisition_progress: dict | None = None
    case_id: str | None = None
    run: dict | None = None
    export: dict | None = None
    outcome: str = "running"
    message: str = ""
    error: str | None = None
    started_at: str = field(default_factory=utcnow)
    finished_at: str | None = None
    acq_job: Any = None

    def log(self, stage: str, **data):
        with self.lock:
            self.stage = stage if stage in PIPELINE_STAGES else self.stage
            self.events.append({"t": utcnow(), "stage": stage, **data})
            self.events[:] = self.events[-300:]

    def snapshot(self) -> dict:
        with self.lock:
            acq_status = self.acq_job.status() if self.acq_job is not None and not self.done.is_set() else None
            return {"stage": self.stage, "events": list(self.events), "acquisition": self.acquisition,
                    "acquisition_status": acq_status, "case_id": self.case_id, "run": self.run,
                    "export": self.export, "outcome": self.outcome, "message": self.message, "error": self.error,
                    "done": self.done.is_set(), "cancelling": self.cancel.is_set(), "params": self.params,
                    "started_at": self.started_at, "finished_at": self.finished_at}

    def request_cancel(self):
        self.cancel.set()
        if self.acq_job is not None:
            self.acq_job.cancel()


_guard = threading.Lock()
_current: QuickJob | None = None


def current_quick_job() -> QuickJob | None:
    return _current


def classify_outcome(run: dict, export: dict | None) -> tuple[str, str]:
    """Map measured results to a user-facing outcome. Success needs real, verified output."""
    status = run.get("status")
    if status == "blocked":
        return "blocked", run.get("error") or "Recovery was blocked by an evidence-integrity check."
    if status == "integrity_failed" or not run.get("source_unchanged"):
        return "failed", "The evidence image changed or could not be re-verified. Results are not verified evidence."
    if status == "cancelled":
        return "cancelled", "Recovery was cancelled. Partial engine output is preserved in the case folder."
    if status == "failed":
        return "failed", run.get("error") or "Recovery failed."
    ok = (export or {}).get("copied_ok", 0)
    if not ok:
        if status == "completed":
            return "no_files", "Recovery finished, but no recoverable deleted files were found."
        return "failed", "No files could be recovered; at least one engine did not complete."
    if status != "completed":
        return "partial", f"{ok} file(s) recovered, but at least one engine did not complete. Review the engine log."
    if (export or {}).get("copied_ok") != (export or {}).get("distinct_files"):
        return "partial", "Some recovered files could not be copied to the output folder."
    return "success", f"{ok} distinct file(s) recovered and copied with verified SHA-256."


def start_quick_job(**params) -> QuickJob:
    """params: source ('usb'|'image'|'case'), disk (DiskInfo) / image_path / case_id, method, output_dir,
    label, examiner, authorized, known_hashes, reread_source, confirmed_identity."""
    global _current
    if params.get("method") not in METHODS:
        raise ValueError("Unknown recovery method")
    if not params.get("output_dir"):
        raise ValueError("Choose an output folder")
    if params.get("source") in ("usb", "image") and not params.get("authorized"):
        raise ValueError("Authorization confirmation is required")
    gt = known_hashes_to_ground_truth(params.get("known_hashes") or "")
    with _guard:
        if _current and not _current.done.is_set():
            raise RecoverXError("A recovery is already running")
        public = {k: v for k, v in params.items() if k != "disk"}
        if params.get("disk") is not None:
            public["disk"] = params["disk"].to_dict()
        job = QuickJob(public)
        _current = job
    threading.Thread(target=_work, args=(job, params, gt), name="recoverx-quick", daemon=True).start()
    return job


def _acquire(job: QuickJob, params: dict) -> Path | None:
    from .usb.controller import AcquisitionJob
    from .usb import devices
    disk = params["disk"]
    job.log("acquire", detail=f"Re-checking Disk {disk.number} identity before imaging")
    live = devices.find_disk(disk.number, devices.list_devices())
    mismatch = devices.identity_mismatch(params.get("confirmed_identity") or disk.identity(), live)
    if mismatch:
        job.outcome, job.message = "blocked", mismatch
        return None
    image_dir = Path(params["output_dir"]) / "disk-images"
    acq = AcquisitionJob(live, image_dir, reread_source=bool(params.get("reread_source")),
                         confirmed_by=params.get("examiner") or "").start()
    job.acq_job = acq
    job.log("acquire", detail="Requesting administrator permission (UAC) to read the disk"
            if acq.mode == "uac_elevated_helper" else "Imaging with current administrator rights",
            mode=acq.mode, job_dir=str(acq.dir))
    while True:
        res = acq.result()
        if res is not None:
            break
        with job.lock:
            job.acquisition_progress = acq.status()
        if job.cancel.is_set():
            acq.cancel()
        time.sleep(0.3)
    job.acquisition = res
    job.log("acquire", detail=f"Acquisition {res.get('status')}", status=res.get("status"),
            bytes_copied=res.get("bytes_copied"), error=res.get("error"))
    if res.get("status") == "completed" and res.get("image_verified"):
        return Path(res["image_path"])
    if res.get("status") == "completed_with_errors":
        job.outcome = "acquired_with_errors"
        job.message = ("The image is complete in length but some sectors were unreadable and are zero-filled. "
                       "Recovery was not started automatically. Review the read errors, then start recovery "
                       "from the image explicitly if appropriate.")
    else:
        job.outcome = "blocked" if res.get("status") == "blocked" else (res.get("status") or "failed")
        job.message = res.get("error") or "Acquisition did not complete. No recovery was started."
    return None


def _work(job: QuickJob, params: dict, gt: dict | None):
    try:
        source = params.get("source")
        if source == "usb":
            image = _acquire(job, params)
            if image is None:
                return
        elif source == "image":
            image = Path(params["image_path"])
        else:
            image = None
        if job.cancel.is_set():
            job.outcome, job.message = "cancelled", "Cancelled before recovery started."
            return
        job.log("register", detail="Computing the evidence SHA-256 baseline for a new case" if image
                else "Opening the existing case")
        if image is not None:
            notes = "Created by Quick Recovery" + (" from direct USB acquisition" if source == "usb" else "")
            case, rec = create_case(image, label=params.get("label") or image.stem,
                                    examiner=params.get("examiner") or "", notes=notes)
            if job.acquisition:
                acq_hash = job.acquisition.get("image_sha256")
                rec["acquisition"] = job.acquisition
                case.save(rec)
                case.event("acquisition_recorded", record=job.acquisition.get("record_path"),
                           source_stream_sha256=job.acquisition.get("source_stream_sha256"),
                           image_sha256=acq_hash, disk=(job.acquisition.get("disk") or {}).get("number"))
                if acq_hash != rec["image_sha256_initial"]:
                    job.outcome = "failed"
                    job.message = "The image changed between acquisition and case registration. Recovery blocked."
                    case.event("acquisition_hash_mismatch", acquisition=acq_hash, case=rec["image_sha256_initial"])
                    job.case_id = case.id
                    return
        else:
            case = open_case(str(params["case_id"]))
        job.case_id = case.id
        method = params["method"]

        def progress(event):
            stage = {"hashing_source": "analyze", "analyzing": "analyze", "strategy_selected": "recover",
                     "engine_started": "recover", "engine_finished": "recover", "smart_fallback": "recover",
                     "verifying": "verify", "run_finished": "verify"}.get(event.get("stage"), None)
            job.log(stage or event.get("stage", "recover"), **{k: v for k, v in event.items() if k != "stage"},
                    event=event.get("stage"))

        run = run_recovery(case, method, ground_truth=gt, model_dir=latest_model_dir(get_settings().models_dir),
                           analyze=True, cancel_event=job.cancel, progress=progress,
                           conservative=method != "smart", label="quick")
        job.run = run
        export = None
        if any(e.get("files") for e in run.get("engine_runs", [])) and run.get("source_unchanged"):
            job.log("export", detail="Copying recovered files and reports to the output folder")
            from .reporting.pdf_report import generate_case_pdf
            try:
                export = export_run(case, run, params["output_dir"], pdf_bytes=generate_case_pdf(case))
                case.event("export_completed", output_dir=export["output_dir"], copied=export["copied_ok"],
                           distinct=export["distinct_files"])
                rec = case.load()
                for r in rec["runs"]:
                    if r["run_id"] == run["run_id"]:
                        r["export"] = {k: v for k, v in export.items() if k != "files"}
                case.save(rec)
            except OSError as exc:
                job.error = f"Export failed: {exc}"
                case.event("export_failed", error=str(exc))
        job.export = export
        job.outcome, job.message = classify_outcome(run, export)
        if job.error and job.outcome == "success":
            job.outcome = "partial"
    except (RecoverXError, OSError, ValueError) as exc:
        job.error = f"{type(exc).__name__}: {exc}"
        job.outcome, job.message = "failed", str(exc)
    except Exception as exc:  # never leave the UI waiting on a dead worker
        job.error = f"{type(exc).__name__}: {exc}"
        job.outcome, job.message = "failed", "Unexpected error: " + str(exc)
    finally:
        job.finished_at = utcnow()
        job.log("finished", outcome=job.outcome, message=job.message)
        job.done.set()
