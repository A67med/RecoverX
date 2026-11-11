"""Atomic JSON persistence and POSIX advisory locks (Linux / WSL runtime)."""
from __future__ import annotations
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from ..exceptions import RecoverXError


def atomic_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".recoverx-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, default=str, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def operation_lock(directory: Path, name: str = ".recovery.lock"):
    if os.name != "posix":
        raise RecoverXError("Recovery locking requires Linux / WSL; native Windows is unsupported")
    import fcntl
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoverXError("An operation is already active here; wait or cancel it first") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
