"""Start and monitor one acquisition job from the (unelevated) application.

If RecoverX already runs with administrator rights the worker runs in a thread.
Otherwise the worker is launched through the UAC consent prompt — never
silently — and communicates through JSON files in a private job directory.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ..config import PROJECT_ROOT, get_settings
from ..forensic.storage import atomic_json
from ..models import utcnow
from . import helper, win32
from .devices import DiskInfo

HELPER_SCRIPT = PROJECT_ROOT / "scripts" / "usb_acquire_helper.py"


def image_filename(disk: DiskInfo) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in (disk.product or disk.name))[:40].strip("-") or "usb"
    return f"Disk{disk.number}-{safe}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.img"


class AcquisitionJob:
    def __init__(self, disk: DiskInfo, image_dir: Path, *, reread_source: bool = False, confirmed_by: str = ""):
        self.id = time.strftime("A%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = get_settings().ensure().home / "acquisitions" / self.id
        self.dir.mkdir(parents=True, exist_ok=False)
        image_dir.mkdir(parents=True, exist_ok=True)
        self.image_path = image_dir / image_filename(disk)
        self.request = {"disk_number": disk.number, "identity": disk.identity(), "image_path": str(self.image_path),
                        "reread_source": reread_source, "requested_at": utcnow(), "confirmed_by": confirmed_by,
                        "disk_label": disk.label()}
        atomic_json(self.dir / "request.json", self.request)
        self.mode = None
        self._thread: threading.Thread | None = None
        self._event = threading.Event()
        self._proc = None
        self.launch_error: str | None = None

    def start(self, *, in_process: bool | None = None, **run_kwargs) -> "AcquisitionJob":
        elevated = win32.is_admin()
        if in_process or (in_process is None and elevated):
            self.mode = "in_process_elevated" if elevated else "in_process"
            self._thread = threading.Thread(target=helper.run_request, args=(self.request, self.dir),
                                            kwargs={"cancel": self._event, **run_kwargs},
                                            name=f"recoverx-{self.id}", daemon=True)
            self._thread.start()
            return self
        if not win32.IS_WINDOWS:
            raise OSError("Elevated USB acquisition is only available on Windows")
        exe = Path(sys.executable)
        if exe.name.lower() == "pythonw.exe":
            exe = exe.with_name("python.exe")
        params = subprocess.list2cmdline(["-I", str(HELPER_SCRIPT), "--job", str(self.dir)])
        self.mode = "uac_elevated_helper"
        try:
            self._proc = win32.run_elevated(str(exe), params, str(PROJECT_ROOT))
        except win32.Win32Error as exc:
            self.launch_error = ("Administrator permission was declined. USB imaging needs it to read the "
                                 "physical disk; nothing was read or written." if exc.code == win32.ERROR_CANCELLED
                                 else f"Could not start the elevated imaging worker: {exc}")
            atomic_json(self.dir / "result.json", {"status": "blocked", "error": self.launch_error})
        return self

    def cancel(self) -> None:
        self._event.set()
        try:
            (self.dir / "cancel").write_text(utcnow())
        except OSError:
            pass

    def _read(self, name: str) -> dict | None:
        p = self.dir / name
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def result(self) -> dict | None:
        res = self._read("result.json")
        if res is not None:
            return res
        if self._proc is not None:
            code = self._proc.poll()
            if code is not None:
                time.sleep(0.2)
                res = self._read("result.json")
                if res is None:
                    res = {"status": "failed", "error": f"Imaging worker exited (code {code}) without a result. "
                                                         "Any partial image was not marked successful."}
                    atomic_json(self.dir / "result.json", res)
                return res
        if self._thread is not None and not self._thread.is_alive():
            return self._read("result.json") or {"status": "failed", "error": "Imaging thread ended without a result"}
        return None

    def status(self) -> dict:
        return self._read("status.json") or {"stage": "waiting_for_permission" if self.mode == "uac_elevated_helper"
                                             else "starting"}

    @property
    def done(self) -> bool:
        return self.result() is not None
