"""Shell-free commands, bounded output capture and process-group cancellation."""
from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .tool_paths import resolve_tool
from .models import CommandResult, utcnow


def run_command(args: list[str], *, cwd: str | Path | None = None,
                timeout: float = 600, env_extra: dict[str, str] | None = None,
                cancel_event: threading.Event | None = None,
                max_output_bytes: int = 8 * 1024 * 1024) -> CommandResult:
    if not args or not all(isinstance(a, str) and "\x00" not in a for a in args):
        raise ValueError("args must be a non-empty list of NUL-free strings")
    if not math.isfinite(timeout) or timeout <= 0 or max_output_bytes < 1:
        raise ValueError("timeout and output limit must be positive and finite")
    if os.name == "nt" and (resolved := resolve_tool(args[0])):
        args = [resolved, *args[1:]]
    started, t0 = utcnow(), time.perf_counter()
    result = CommandResult(list(args), None, "", "", 0.0, started,
                           cwd=str(cwd) if cwd else None)
    if cancel_event is not None and cancel_event.is_set():
        result.cancelled = True
        return result
    env = os.environ.copy()
    env.setdefault("TERM", "xterm")
    env.update({"LC_ALL": "C", **(env_extra or {})})
    try:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=os.name != "nt")
    except OSError as exc:
        prefix = "executable not found" if isinstance(exc, FileNotFoundError) else "unable to start command"
        result.stderr = f"{prefix}: {exc}"
        return result

    captures = [deque(), deque()]
    sizes, truncated = [0, 0], [False, False]

    def drain(stream, index):
        with stream:
            while chunk := stream.read(65536):
                captures[index].append(chunk)
                sizes[index] += len(chunk)
                while sizes[index] > max_output_bytes:
                    excess = sizes[index] - max_output_bytes
                    front = captures[index].popleft()
                    if len(front) > excess:
                        captures[index].appendleft(front[excess:])
                        sizes[index] -= excess
                    else:
                        sizes[index] -= len(front)
                    truncated[index] = True

    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((proc.stdout, proc.stderr))]
    for reader in readers:
        reader.start()

    def stop():
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass

    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                result.cancelled = True
                stop()
                break
            if time.perf_counter() - t0 >= timeout:
                result.timed_out = True
                stop()
                break
            time.sleep(0.05)
        proc.wait()
    except BaseException:
        stop()
        proc.wait()
        raise
    finally:
        # A grandchild may keep a pipe open after its parent exits.
        for reader in readers:
            reader.join(0.2)
        if any(reader.is_alive() for reader in readers):
            stop()
        for reader in readers:
            reader.join(1)
    result.returncode = proc.returncode
    result.stdout, result.stderr = [b"".join(q).decode("utf-8", errors="replace") for q in captures]
    result.output_truncated = any(truncated)
    result.elapsed_s = round(time.perf_counter() - t0, 6)
    return result
