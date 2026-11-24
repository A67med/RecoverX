"""Find the native Windows TSK binaries installed by setup.

On Linux, use the same PATH-based lookup as the original RecoverX v0.3.
Keep third-party executables and their adjacent DLLs in their own directories.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import PROJECT_ROOT


def resolve_tool(command: str) -> str | None:
    if os.name != "nt":
        return shutil.which(command)

    if command.lower() in ("wsl", "wsl.exe"):
        system_wsl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
        return str(system_wsl) if system_wsl.is_file() else None
    if command.lower() in ("photorec", "photorec.exe", "photorec_win.exe"):
        # Native Windows PhotoRec (RC1 MinGW build or the official photorec_win.exe).
        base = PROJECT_ROOT / "tools" / "photorec"
        for name in ("photorec.exe", "photorec_win.exe"):
            if (base / name).is_file():
                return str((base / name).resolve())
        return None
    filename = command if command.lower().endswith(".exe") else command + ".exe"
    roots = [PROJECT_ROOT / "tools" / "tsk"]
    # Prefer the release-managed copy; never execute something found in a case/output folder.
    for base in roots:
        if base.exists():
            for path in [base / filename, base / 'bin' / filename, *sorted(base.glob('*/' + filename))]:
                if path.is_file():
                    return str(path.resolve())
    return shutil.which(filename) or shutil.which(command)
