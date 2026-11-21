#!/usr/bin/env python3
"""Kali/Linux launcher for the local RecoverX Streamlit app.

Uses the repository's existing virtual environment; never runs the app as root.
Starts a server on loopback only, checks health, then opens the browser.
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
VENV = ROOT / '.venv'
PYTHON = VENV / 'bin' / 'python'
CACHE = Path.home() / '.cache' / 'recoverx'
STATE = CACHE / 'server.json'
LOG = CACHE / 'launcher.log'


def inform(message: str, *, error: bool = False) -> None:
    print(message, file=sys.stderr if error else sys.stdout)
    zenity = shutil.which('zenity')
    if os.environ.get('DISPLAY') and zenity:
        try:
            subprocess.Popen([zenity, '--error' if error else '--info', '--title=RecoverX',
                              '--width=420', f'--text={message}'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/_stcore/health', timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) == 0


def installed() -> bool:
    if not PYTHON.is_file():
        return False
    check = subprocess.run([str(PYTHON), '-c',
        'import streamlit, pandas, plotly, sklearn, reportlab, joblib, scipy, PIL, numpy'],
        cwd=ROOT, capture_output=True, text=True)
    return check.returncode == 0


def setup() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    if not PYTHON.is_file():
        inform('First launch: creating a private Python environment. This is a one-time step.')
        with LOG.open('a') as log:
            subprocess.run(['python3', '-m', 'venv', str(VENV)], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    if not installed():
        inform('First launch: installing Python requirements. Internet may be needed once.')
        with LOG.open('a') as log:
            subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    # The trusted bundled model is only installed if missing. The install script
    # validates metadata and compatibility before loading the trusted joblib.
    model_script = ROOT / 'scripts' / 'install_bundled_model.py'
    if model_script.exists():
        with LOG.open('a') as log:
            subprocess.run([str(PYTHON), str(model_script)], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=False)


def previous_port() -> int | None:
    try:
        state = json.loads(STATE.read_text())
        pid = int(state['pid'])
        port = int(state['port'])
        # Never reuse unrelated services on the same port.
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        if str(ROOT / 'app.py') in cmdline and healthy(port):
            return port
    except (FileNotFoundError, OSError, ValueError, KeyError, json.JSONDecodeError):
        pass
    return None


def free_port() -> int:
    for port in range(8501, 8512):
        if not port_open(port):
            return port
    raise RuntimeError('Ports 8501–8511 are busy; close another Streamlit service first.')


def launch(*, dry_run: bool = False) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    running = previous_port()
    if running is not None:
        return f'http://127.0.0.1:{running}'
    port = free_port()
    command = [str(PYTHON), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
               '--server.address=127.0.0.1', f'--server.port={port}',
               '--server.headless=true', '--browser.gatherUsageStats=false',
               '--server.fileWatcherType=none']
    if dry_run:
        return json.dumps({'command': command, 'cwd': str(ROOT), 'port': port})
    with LOG.open('a') as log:
        log.write(f'\nLaunching RecoverX on port {port}\n')
        log.flush()
        proc = subprocess.Popen(command, cwd=ROOT, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    STATE.write_text(json.dumps({'pid': proc.pid, 'port': port, 'root': str(ROOT)}))
    for _ in range(60):
        if healthy(port):
            return f'http://127.0.0.1:{port}'
        if proc.poll() is not None:
            raise RuntimeError(f'Streamlit exited. See {LOG} for details.')
        time.sleep(.5)
    raise RuntimeError(f'Streamlit did not respond. See {LOG} for details.')


def main() -> int:
    parser = argparse.ArgumentParser(description='Start RecoverX in the browser')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if not args.dry_run:
            setup()
        url = launch(dry_run=args.dry_run)
        if args.dry_run:
            print(url)
        else:
            webbrowser.open(url, new=2)
            print(f'RecoverX is running at {url}')
        return 0
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        inform(f'Could not start RecoverX: {exc}\nSee log: {LOG}', error=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
