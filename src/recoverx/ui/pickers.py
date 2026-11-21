"""Native file/folder pickers for the local desktop session (Windows or Linux)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

IMAGE_PATTERNS = "*.img *.dd *.raw *.bin *.001"


def _tk(kind: str, title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if kind == "dir":
                chosen = filedialog.askdirectory(parent=root, title=title, mustexist=False)
            else:
                chosen = filedialog.askopenfilename(parent=root, title=title,
                                                    filetypes=[("Disk images", IMAGE_PATTERNS), ("All files", "*.*")])
            return chosen or None
        finally:
            root.destroy()
    except Exception:
        return None


def _linux(kind: str, title: str) -> str | None:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return None
    zenity, kdialog = shutil.which("zenity"), shutil.which("kdialog")
    if zenity:
        cmd = [zenity, "--file-selection", f"--title={title}"]
        cmd += ["--directory"] if kind == "dir" else [f"--file-filter=Disk images | {IMAGE_PATTERNS}",
                                                       "--file-filter=All files | *"]
    elif kdialog:
        cmd = [kdialog, "--getexistingdirectory" if kind == "dir" else "--getopenfilename", str(Path.home())]
        if kind != "dir":
            cmd.append(f"Disk images ({IMAGE_PATTERNS})")
    else:
        return _tk(kind, title)
    try:
        r = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def pick_image_file() -> str | None:
    return _tk("file", "Select a RecoverX disk image") if os.name == "nt" else _linux("file", "Choose a disk image")


def pick_folder() -> str | None:
    return _tk("dir", "Choose the RecoverX output folder") if os.name == "nt" else _linux("dir", "Choose output folder")


def open_folder(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_dir():
        return False
    try:
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False
            subprocess.Popen([opener, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
