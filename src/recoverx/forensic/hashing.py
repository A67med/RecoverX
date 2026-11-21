from __future__ import annotations
import hashlib
import os
import stat
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    if Path(path).is_symlink():
        raise OSError("Hashing requires a non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise OSError("Hashing requires a regular file")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise OSError("File changed while computing SHA-256")
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
