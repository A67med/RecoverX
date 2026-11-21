"""Acquisition worker. Runs in-process (already elevated) or as an elevated child.

The child is started only through the Windows UAC consent prompt, so the user
explicitly approves the privilege. It receives a JSON request, re-verifies the
disk identity and destination safety itself, streams the image, and writes
status/result JSON files. A ``cancel`` file in the job directory stops it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from ..forensic.storage import atomic_json
from . import devices, imaging, win32

FINAL_STATES = ("completed", "completed_with_errors", "cancelled", "disconnected", "failed", "blocked")
_FORBIDDEN_ROOTS = [os.environ.get("SystemRoot", r"C:\Windows"), os.environ.get("ProgramFiles", r"C:\Program Files"),
                    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]


class _FileCancel(threading.Event):
    """Event that is also set when <job>/cancel appears (cross-process cancellation)."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._last = 0.0

    def is_set(self) -> bool:
        if super().is_set():
            return True
        now = time.monotonic()
        if now - self._last > 0.25:
            self._last = now
            if self.path.exists():
                self.set()
        return super().is_set()


def check_request(req: dict) -> list[str]:
    problems = []
    dest = Path(str(req.get("image_path", "")))
    if not dest.is_absolute() or dest.suffix.lower() != ".img":
        problems.append("Destination must be an absolute .img path")
    if dest.exists():
        problems.append("Destination image already exists; RecoverX never overwrites files")
    low = str(dest).lower()
    if any(root and low.startswith(root.lower().rstrip("\\") + "\\") for root in _FORBIDDEN_ROOTS):
        problems.append("Destination is inside a protected Windows program folder")
    if not isinstance(req.get("disk_number"), int):
        problems.append("Missing disk number")
    if not isinstance(req.get("identity"), dict):
        problems.append("Missing confirmed disk identity")
    return problems


def run_request(req: dict, job_dir: Path, *, cancel: threading.Event | None = None,
                source_factory=None, device_lister=None, disks_for_path=None) -> dict:
    """Execute one acquisition request, writing status.json/result.json in job_dir."""
    status_path, result_path = job_dir / "status.json", job_dir / "result.json"
    cancel = cancel or _FileCancel(job_dir / "cancel")
    started = time.time()

    def status(stage, **extra):
        atomic_json(status_path, {"stage": stage, "updated": time.time(), "started": started,
                                  "pid": os.getpid(), "elevated": win32.is_admin(), **extra})

    def finish(payload: dict) -> dict:
        atomic_json(result_path, payload)
        status(payload.get("status", "failed"), final=True, error=payload.get("error"))
        return payload

    status("verifying_identity")
    problems = check_request(req)
    if problems:
        return finish({"status": "blocked", "error": "; ".join(problems)})
    number = req["disk_number"]
    try:
        live = (device_lister or devices.list_devices)()
    except OSError as exc:
        return finish({"status": "blocked", "error": f"Device discovery failed: {exc}"})
    disk = devices.find_disk(number, live)
    mismatch = devices.identity_mismatch(req["identity"], disk)
    if mismatch:
        return finish({"status": "blocked", "error": mismatch})
    dest = Path(req["image_path"])
    problems = imaging.validate_destination(dest.parent, required_bytes=disk.size, source_disk=number,
                                            disks_for_path=disks_for_path)
    if problems:
        return finish({"status": "blocked", "error": "; ".join(problems)})
    try:
        source = (source_factory or (lambda: imaging.WindowsDiskSource(number, disk.size, disk.sector_size)))()
    except OSError as exc:
        code = getattr(exc, "code", None)
        hint = " Administrator approval is required to read a physical disk." if code == win32.ERROR_ACCESS_DENIED else ""
        return finish({"status": "blocked", "error": f"Cannot open Disk {number} read-only: {exc}.{hint}"})
    try:
        def progress(event):
            status(event.get("stage", "imaging"), **{k: v for k, v in event.items() if k != "stage"})
        result = imaging.acquire(source, dest, cancel=cancel, progress=progress,
                                 reread_source=bool(req.get("reread_source")))
    finally:
        source.close()
    payload = result.to_dict()
    payload["disk"] = disk.to_dict()
    payload["request"] = {k: req.get(k) for k in ("disk_number", "identity", "image_path", "reread_source",
                                                   "requested_at", "confirmed_by")}
    payload["elevated"] = win32.is_admin()
    record = dest.with_name(dest.name + ".acquisition.json") if result.status in ("completed", "completed_with_errors") \
        else Path(result.image_path).with_name(Path(result.image_path).name + ".acquisition.json")
    try:
        record.write_text(json.dumps(payload, indent=2, default=str))
        payload["record_path"] = str(record)
    except OSError as exc:
        payload.setdefault("warnings", []).append(f"Could not write acquisition record beside the image: {exc}")
    return finish(payload)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RecoverX read-only USB acquisition worker")
    ap.add_argument("--job", required=True, help="Job directory containing request.json")
    args = ap.parse_args(argv)
    job_dir = Path(args.job).resolve()
    try:
        req = json.loads((job_dir / "request.json").read_text())
        payload = run_request(req, job_dir)
        return 0 if payload.get("status") in ("completed", "completed_with_errors") else 2
    except Exception as exc:  # last-resort record; never silently fail
        try:
            atomic_json(job_dir / "result.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                                                  "traceback": traceback.format_exc()[-4000:]})
            atomic_json(job_dir / "status.json", {"stage": "failed", "final": True, "error": str(exc)})
        except OSError:
            pass
        return 3


if __name__ == "__main__":
    sys.exit(main())
