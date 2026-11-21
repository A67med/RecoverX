#!/usr/bin/env python3
"""Windows launcher: start the loopback-only RecoverX server and open it as a desktop window.

* Binds to 127.0.0.1 only; usage telemetry disabled.
* Opens Microsoft Edge (or Chrome) in --app mode for a desktop-style window,
  falling back to the default browser.
* Runs as the current user. It never elevates; USB imaging asks for UAC
  separately, at the moment an acquisition is confirmed.
* Keeps serving until this console window is closed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError):
        return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def choose_port() -> int:
    for port in range(8501, 8521):
        if port_free(port):
            return port
    raise RuntimeError("Ports 8501-8520 are all busy. Close other local web apps and try again.")


def app_browser() -> list[str] | None:
    bases = [os.environ.get(env) for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    candidates = [Path(b) / "Microsoft/Edge/Application/msedge.exe" for b in bases if b]
    candidates += [Path(b) / "Google/Chrome/Application/chrome.exe" for b in bases if b]
    for exe in candidates:
        if exe.is_file():
            return [str(exe)]
    found = shutil.which("msedge") or shutil.which("chrome")
    return [found] if found else None


def server_command(port: int) -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", str(APP), "--server.address=127.0.0.1",
            f"--server.port={port}", "--server.headless=true", "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none", "--global.developmentMode=false"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Start RecoverX")
    ap.add_argument("--dry-run", action="store_true", help="Print the commands without starting anything")
    ap.add_argument("--no-window", action="store_true", help="Do not open a browser window")
    args = ap.parse_args()
    os.environ.setdefault("RECOVERX_HOME", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RecoverX"))
    port = choose_port()
    url = f"http://127.0.0.1:{port}"
    browser = app_browser()
    window = (browser + [f"--app={url}", "--window-size=1360,920", "--new-window"]) if browser else None
    if args.dry_run:
        print(json.dumps({"server": server_command(port), "window": window, "url": url, "cwd": str(ROOT)}, indent=2))
        return 0
    print(f"Starting RecoverX on {url} (local only). Keep this window open while you use RecoverX.")
    proc = subprocess.Popen(server_command(port), cwd=ROOT)
    for _ in range(120):
        if healthy(port):
            break
        if proc.poll() is not None:
            print("RecoverX stopped during startup. Read the messages above, then run SETUP_WINDOWS.cmd again.")
            return 1
        time.sleep(0.5)
    else:
        print("RecoverX did not respond within 60 seconds.")
        proc.terminate()
        return 1
    if not args.no_window:
        try:
            if window:
                subprocess.Popen(window, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(url, new=1)
        except OSError:
            webbrowser.open(url, new=1)
    print(f"RecoverX is running: {url}")
    print("Close this window (or press Ctrl+C) to stop RecoverX.")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
