"""Common engine interface (spec §7)."""
from __future__ import annotations

import mimetypes
import os
import shutil
import stat
import math
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from ..forensic.hashing import sha256_file
from ..forensic.image_validator import ensure_safe_output, validate_image
from ..exceptions import RecoverXError
from ..models import EngineRun, RecoveredFile
from ..process import run_command
from ..tool_paths import resolve_tool

MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"%PDF-", "pdf"),
    (b"PK\x03\x04", "zip"), (b"GIF8", "gif"),
]


def detect_type(path: Path) -> str:
    """Lightweight signature check. Never executes or renders content."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "unreadable"
    for sig, name in MAGIC:
        if head.startswith(sig):
            return name
    if head and all(32 <= b < 127 or b in (9, 10, 13) for b in head):
        return "text"
    return mimetypes.guess_type(path.name)[0] or "unknown"


class BaseEngine(ABC):
    name: str = "base"
    executables: tuple[str, ...] = ()

    def capabilities(self) -> dict:
        found = {exe: resolve_tool(exe) for exe in self.executables}
        return {"engine": self.name, "available": all(found.values()), "executables": found,
                "version": self.version() if all(found.values()) else None}

    def preflight(self, image: Path, output_dir: Path) -> str | None:
        caps = self.capabilities()
        if not caps["available"]:
            missing = [k for k, v in caps["executables"].items() if not v]
            return f"missing executables: {', '.join(missing)}"
        ensure_safe_output(output_dir, image)
        probe = output_dir
        while not probe.exists():
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        if free < getattr(self, "required_free_bytes", image.stat().st_size):
            return f"insufficient free space for output ({free} bytes free)"
        return None

    @abstractmethod
    def version(self) -> str | None: ...

    @abstractmethod
    def _execute(self, image: Path, output_dir: Path, run: EngineRun, *, sector_offset: int,
                 timeout: float, cancel_event: threading.Event | None) -> None: ...

    def run(self, image: str | Path, output_dir: str | Path, *, sector_offset: int = 0,
            timeout: float = 600, cancel_event: threading.Event | None = None,
            run_id: str | None = None) -> EngineRun:
        image, output_dir = Path(image).expanduser(), Path(output_dir).expanduser()
        run = EngineRun(engine=self.name, run_id=run_id or uuid.uuid4().hex[:12], status="failed",
                        output_dir=str(output_dir), elapsed_s=0.0)
        t0 = time.perf_counter()
        try:
            image = validate_image(image)
            if not isinstance(sector_offset, int) or sector_offset < 0 or sector_offset * 512 >= image.stat().st_size:
                raise ValueError("sector offset must address a sector inside the image")
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("timeout must be positive and finite")
            output_dir = ensure_safe_output(output_dir, image)
            run.output_dir = str(output_dir)
            if cancel_event is not None and cancel_event.is_set():
                run.status, run.error = "cancelled", "cancelled before execution"
                return run
            problem = self.preflight(image, output_dir)
            if problem:
                run.status, run.error = "blocked", problem
                return run
            if output_dir.exists() and any(output_dir.iterdir()):
                run.status, run.error = "blocked", "output directory not empty (refusing to mix runs)"
                return run
            output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            run.tool_version = self.version()
            self._execute(image, output_dir, run, sector_offset=sector_offset,
                          timeout=timeout, cancel_event=cancel_event)
        except (OSError, RecoverXError, ValueError) as exc:
            run.status = "failed" if run.commands else "blocked"
            run.error = f"{type(exc).__name__}: {exc}"
        finally:
            run.elapsed_s = round(time.perf_counter() - t0, 6)
        return run

    # shared inventory
    def inventory(self, root: Path, run: EngineRun, exclude: set[str] = frozenset(),
                  original_name_from_path: bool = False) -> list[RecoveredFile]:
        files = []
        if root.is_symlink() or not root.is_dir():
            run.warnings.append(f"Skipped unsafe inventory root: {root.name}")
            return files
        def onerror(error):
            run.warnings.append(f"Inventory incomplete: {error}")
        for dirpath, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = sorted(d for d in dirs if not (Path(dirpath) / d).is_symlink())
            for n in sorted(names):
                p = Path(dirpath) / n
                if n in exclude:
                    continue
                try:
                    st = p.lstat()
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                        run.warnings.append(f"Skipped non-regular or linked output: {p.relative_to(root)}")
                        continue
                    rel = str(p.relative_to(root))
                    files.append(RecoveredFile(
                        recovery_id=f"{run.run_id}-{len(files):05d}", engine=self.name, run_id=run.run_id,
                        recovered_name=n, relative_path=rel, size=st.st_size,
                        sha256=sha256_file(p), extension=p.suffix.lower().lstrip("."),
                        detected_type=detect_type(p), original_name=rel if original_name_from_path else None,
                        notes="Type is a signature/extension hint, not validation of complete contents.",
                        original_metadata={"output_mtime_ns": st.st_mtime_ns},
                    ))
                except OSError as exc:
                    run.warnings.append(f"Could not inventory {p.relative_to(root)}: {exc}")
        if run.warnings and run.status == "completed":
            run.status = "incomplete"
        return files


def run_cmd(*a, **k):
    return run_command(*a, **k)
