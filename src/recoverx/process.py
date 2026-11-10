"""Safe subprocess execution: argument lists only (never a shell), timeouts,
process-group kill, optional cancellation event."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .models import CommandResult, utcnow


def run_command(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 600,
    env_extra: dict[str, str] | None = None,
    cancel_event: threading.Event | None = None,
) -> CommandResult:
    if not args or not all(isinstance(a, str) for a in args):
        raise ValueError("args must be a non-empty list of strings")
    env = os.environ.copy()
    env.setdefault("TERM", "xterm")  # PhotoRec's ncurses UI needs a terminal type
    if env_extra:
        env.update(env_extra)
    started = utcnow()
    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(
            args, cwd=str(cwd) if cwd else None, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, text=True, errors="replace",
        )
    except FileNotFoundError as e:
        return CommandResult(args, None, "", f"executable not found: {e}", 0.0, started, cwd=str(cwd) if cwd else None)

    timed_out = cancelled = False
    deadline = t0 + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
            elif time.perf_counter() > deadline:
                timed_out = True
            if timed_out or cancelled:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                out, err = proc.communicate()
                break
    elapsed = time.perf_counter() - t0
    return CommandResult(
        args=list(args), returncode=proc.returncode, stdout=out or "", stderr=err or "",
        elapsed_s=round(elapsed, 6), started_at=started, timed_out=timed_out,
        cancelled=cancelled, cwd=str(cwd) if cwd else None,
    )
