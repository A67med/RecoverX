"""Find official TSK/PhotoRec binaries installed by the Windows setup.

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

    aliases = {"photorec": "photorec_win.exe"}
    filename = aliases.get(command, command if command.lower().endswith('.exe') else command + '.exe')
    roots = ([PROJECT_ROOT / "tools" / "photorec"] if command == "photorec" else
             [PROJECT_ROOT / "tools" / "tsk"])
    # Prefer the release-managed copy; never execute something found in a case/output folder.
    for base in roots:
        if base.exists():
            for path in [base / filename, base / 'bin' / filename, *sorted(base.glob('*/' + filename))]:
                if path.is_file():
                    return str(path.resolve())
    return shutil.which(filename) or shutil.which(command)
