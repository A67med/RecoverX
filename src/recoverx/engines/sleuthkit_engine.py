"""TSK adapter. Verified against The Sleuth Kit 4.12.1.

tsk_recover without -a/-e recovers unallocated (deleted) files only, keeping the
names/paths that remain in filesystem metadata. Names are therefore *metadata
claims*; a file only counts as recovered when its hash matches ground truth."""
from __future__ import annotations

import re
import threading
from pathlib import Path

from ..models import EngineRun
from .base_engine import BaseEngine, run_cmd


class SleuthKitEngine(BaseEngine):
    name = "tsk"
    executables = ("tsk_recover", "fls", "fsstat", "mmls")

    def version(self) -> str | None:
        r = run_cmd(["tsk_recover", "-V"], timeout=15)
        m = re.search(r"ver\s+([\w.]+)", r.stdout + r.stderr)
        return m.group(1) if m else None

    def _execute(self, image: Path, output_dir: Path, run: EngineRun, *, sector_offset: int,
                 timeout: float, cancel_event: threading.Event | None) -> None:
        files_dir = output_dir / "files"
        files_dir.mkdir()
        args = ["tsk_recover"]
        if sector_offset:
            args += ["-o", str(sector_offset)]
        args += [str(image), str(files_dir)]
        res = run_cmd(args, cwd=output_dir, timeout=timeout, cancel_event=cancel_event)
        run.commands.append(res.to_dict())
        if res.timed_out:
            run.status, run.error = "timed_out", f"tsk_recover exceeded {timeout}s"
        elif res.cancelled:
            run.status, run.error = "cancelled", "cancelled by user"
        elif res.returncode != 0:
            run.status = "failed"
            run.error = (res.stderr.strip() or f"exit code {res.returncode}")[:500]
        else:
            run.status = "completed"
        # inventory even after failure: partial output is still evidence of what ran
        run.files = self.inventory(files_dir, run, original_name_from_path=True)
        for f in run.files:
            f.relative_path = f"files/{f.relative_path}"
