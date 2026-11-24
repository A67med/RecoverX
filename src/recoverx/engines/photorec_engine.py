"""PhotoRec adapter. Verified against PhotoRec 7.1 (testdisk 7.1).

Verified behaviour (docs/feasibility.md):
  * Unattended mode: `photorec /log /d <dir>/recup /cmd <image> <script>` where
    `/cmd` is its own argument and the script is a single comma-separated arg.
  * photorec.log is written to the *current working directory*, so cwd is the
    run's output directory.
  * Output goes to <dir>/recup.1/, plus report.xml listing carved byte ranges.
  * `freespace` restricts carving to unallocated space when the filesystem is
    recognised (log shows e.g. fat16_remove_used_space / ext2_remove_used_space).
On Windows a release-managed native binary in tools/photorec (the RC1 MinGW build of
TestDisk 7.2, or the official photorec_win.exe) is used when present; otherwise the
Ubuntu PhotoRec is driven through unprivileged WSL.
PhotoRec does not restore original names, paths or timestamps."""
from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from ..tool_paths import resolve_tool
from ..models import EngineRun
from .base_engine import BaseEngine, run_cmd

DEFAULT_SCRIPT = "partition_none,fileopt,everything,enable,freespace,search"


class PhotoRecEngine(BaseEngine):
    name = "photorec"
    executables = ("photorec",)

    def __init__(self, script: str = DEFAULT_SCRIPT):
        if not re.fullmatch(r"[a-z0-9_,]+", script):
            raise ValueError("PhotoRec script must contain only [a-z0-9_,]")
        self.script = script

    @staticmethod
    def _native() -> str | None:
        """Path of a native PhotoRec binary (always the PATH lookup off Windows)."""
        return resolve_tool("photorec")

    @staticmethod
    def _invoker_env() -> dict[str, str] | None:
        # The official photorec_win.exe manifest requests administrator rights, which
        # an unelevated worker cannot grant (WinError 740). Reading an image file needs
        # no elevation, so ask Windows to start it with the caller's own token.
        return {"__COMPAT_LAYER": "RunAsInvoker"} if os.name == "nt" else None

    def capabilities(self) -> dict:
        if os.name != "nt" or self._native():
            return super().capabilities()
        wsl = resolve_tool("wsl")
        version = self.version() if wsl else None
        return {"engine": self.name, "available": bool(version), "executables": {"wsl.exe / photorec": wsl if version else None},
                "version": version}

    def _windows(self, args, *, cwd=None, timeout=15, cancel_event=None):
        # The fixed shell program only checks privileges, sets TERM and execs argv.
        runner = 'test "$(id -u)" -ne 0 || exit 77; export TERM=xterm; exec "$@"'
        command = [resolve_tool("wsl") or "wsl.exe"]
        if cwd is not None:
            command += ["--cd", str(cwd)]
        return run_cmd(command + ["--exec", "/bin/sh", "-c", runner, "recoverx", *args],
                       cwd=cwd, timeout=timeout, cancel_event=cancel_event)

    def version(self) -> str | None:
        native = self._native()
        r = (self._windows(["/usr/bin/photorec", "/version"]) if os.name == "nt" and not native
             else run_cmd([native or "photorec", "/version"], timeout=15, env_extra=self._invoker_env()))
        m = re.search(r"Version:\s*([\w.]+)", r.stdout + r.stderr) or re.search(r"PhotoRec\s+([\d.]+)", r.stdout)
        return m.group(1) if m else None

    def _execute(self, image: Path, output_dir: Path, run: EngineRun, *, sector_offset: int,
                 timeout: float, cancel_event: threading.Event | None) -> None:
        if sector_offset:
            raise ValueError("PhotoRec partition offsets are unsupported; use whole-image carving at offset 0")
        args = ["photorec", "/log", "/d", str(output_dir / "recup"), "/cmd", str(image), self.script]
        native = self._native() if os.name == "nt" else None
        if native:
            # Native Windows build: relative paths inside the case keep the command short.
            args = [native, "/log", "/d", "recup", "/cmd", os.path.relpath(image, output_dir), self.script]
            res = run_cmd(args, cwd=output_dir, timeout=timeout, cancel_event=cancel_event,
                          env_extra=self._invoker_env())
        elif os.name == "nt":
            translated = self._windows(["wslpath", "-a", "-u", str(image)], cancel_event=cancel_event)
            linux_image = translated.stdout.strip()
            if not translated.ok or not linux_image.startswith("/"):
                run.commands.append(translated.to_dict(800))
                run.status = "cancelled" if translated.cancelled else "failed"
                run.error = "Cannot translate the image path through unprivileged WSL"
                return
            args[0], args[3], args[5] = "/usr/bin/photorec", "recup", linux_image
            # Wait for the Linux deadline even after GUI cancellation so the case
            # stays locked until the scanner stops writing its output.
            res = self._windows(["/usr/bin/timeout", "--kill-after=5s", str(timeout), *args],
                                cwd=output_dir, timeout=timeout + 10)
        else:
            res = run_cmd(args, cwd=output_dir, timeout=timeout, cancel_event=cancel_event)
        d = res.to_dict(800)  # stdout is ncurses screen output; keep only the tail
        run.commands.append(d)
        log = output_dir / "photorec.log"
        log_text = ""
        if log.exists() and not log.is_symlink():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 65536))
                log_text = stream.read(65536).decode("utf-8", errors="replace")
        if res.timed_out or (os.name == "nt" and res.returncode in (124, 137)):
            run.status, run.error = "timed_out", f"photorec exceeded {timeout}s"
        elif res.cancelled:
            run.status, run.error = "cancelled", "cancelled by user"
        elif res.returncode != 0 or "PhotoRec exited normally" not in log_text:
            run.status = "failed"
            msg = re.findall(r"Unable to open[^\n]*", res.stdout)
            run.error = (msg[0] if msg else f"exit {res.returncode}; {res.stderr.strip() or 'log missing completion marker'}")[:500]
        else:
            run.status = "completed"
        offsets = self._report_offsets(output_dir)
        files = []
        for sub in sorted(output_dir.glob("recup.*")):
            for f in self.inventory(sub, run, exclude={"report.xml"}):
                f.relative_path = f"{sub.name}/{f.relative_path}"
                if f.recovered_name in offsets:
                    f.original_metadata["carved_byte_runs"] = offsets[f.recovered_name]
                files.append(f)
        for i, f in enumerate(files):
            f.recovery_id = f"{run.run_id}-{i:05d}"
        run.files = files

    @staticmethod
    def _report_offsets(output_dir: Path) -> dict[str, list]:
        """Parse PhotoRec's DFXML-style report.xml for carved byte runs (provenance)."""
        out = {}
        for rep in output_dir.glob("recup.*/report.xml"):
            try:
                if rep.is_symlink() or rep.parent.is_symlink() or rep.stat().st_size > 8 * 1024 * 1024:
                    continue
                root = ET.parse(rep).getroot()
            except (ET.ParseError, OSError):
                continue
            for fo in root.iter():
                if not fo.tag.endswith("fileobject"):
                    continue
                name = runs = None
                for ch in fo:
                    if ch.tag.endswith("filename"):
                        name = Path(ch.text or "").name
                    elif ch.tag.endswith("byte_runs"):
                        runs = [{k: v for k, v in br.attrib.items()} for br in ch]
                if name:
                    out[name] = runs or []
        return out
