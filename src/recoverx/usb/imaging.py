"""Bounded-buffer raw imaging with streamed SHA-256 and destination verification.

The algorithm is source-agnostic: ``acquire`` reads through a ``BlockSource``
(the real Windows physical disk in production; a regular file in automated
tests) and writes ONE new destination file created with exclusive-create.

Result states — only ``completed`` + ``verified`` may start recovery:
  completed            every byte read without error; destination re-read hash
                       equals the source-stream hash
  completed_with_errors every byte position accounted for, but some sectors were
                       unreadable and are zero-filled in the image (listed)
  cancelled / disconnected / failed
                       incomplete; the file is renamed *.img.partial so it can
                       never be registered as evidence by mistake

Hash terms used everywhere:
  source_stream_sha256   SHA-256 of the bytes as they were read from the source
                         during this acquisition (zero-fill included, if any)
  image_sha256           SHA-256 re-computed by reading the finished image file
                         back from the destination disk
  source_reread_sha256   optional second full read of the source device
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .. import __version__
from ..models import utcnow
from . import win32

CHUNK = 1024 * 1024
SAFETY_MARGIN = 64 * 1024 * 1024
MAX_ERROR_RANGES = 4096
# Stop (as failed) when more than this many bytes, or 5% of the device, are unreadable.
MAX_UNREADABLE_BYTES = 256 * 2**20

LIMITATIONS = [
    "The source was opened with GENERIC_READ only; RecoverX issued no write, format, initialise, lock or dismount request.",
    "Opening a disk read-only does not prevent Windows, Explorer, antivirus or other processes from modifying "
    "mounted volumes during imaging. Use a hardware write blocker or the media's write-protect switch when "
    "enforceable protection is required.",
    "This record supports auditability; it is not by itself a legal chain-of-custody certification.",
]


class DisconnectedError(OSError):
    pass


class BlockSource(Protocol):
    size: int
    sector_size: int
    description: dict

    def read_at(self, offset: int, length: int) -> bytes: ...

    def close(self) -> None: ...


class FileSource:
    """A regular file or an already-acquired image used as a source (tests, re-imaging)."""

    def __init__(self, path: str | Path, sector_size: int = 512):
        self.path = Path(path)
        self._f = open(self.path, "rb", buffering=0)
        self.size = os.fstat(self._f.fileno()).st_size
        self.sector_size = sector_size
        self.description = {"kind": "file", "path": str(self.path)}

    def read_at(self, offset, length):
        self._f.seek(offset)
        return self._f.read(length)

    def close(self):
        self._f.close()


class WindowsDiskSource:
    """\\\\.\\PhysicalDriveN opened with GENERIC_READ only (needs administrator)."""

    def __init__(self, number: int, expected_size: int, expected_sector: int):
        self.number = number
        self._h = win32.open_physical_disk_read_only(number)
        try:
            if win32.device_number(self._h) != number:
                raise OSError("Opened device reports a different disk number")
            self.size = win32.disk_length(self._h)
            if self.size != expected_size:
                raise OSError(f"Disk length {self.size} differs from confirmed size {expected_size}")
        except Exception:
            self._h.close()
            raise
        self.sector_size = expected_sector or 512
        self.description = {"kind": "windows_physical_disk", "path": win32.physical_drive_path(number),
                            "access": "GENERIC_READ", "share": "FILE_SHARE_READ|FILE_SHARE_WRITE"}

    def read_at(self, offset, length):
        try:
            return self._h.read_at(offset, length)
        except win32.Win32Error as exc:
            if exc.code in win32.DISCONNECT_ERRORS:
                raise DisconnectedError(exc.code, str(exc)) from exc
            raise

    def close(self):
        self._h.close()


@dataclass
class AcquisitionResult:
    status: str
    image_path: str
    size: int
    bytes_copied: int = 0
    sector_size: int = 512
    source_stream_sha256: str | None = None
    image_sha256: str | None = None
    image_verified: bool = False
    source_reread_sha256: str | None = None
    source_reread_matches: bool | None = None
    unreadable_bytes: int = 0
    unreadable_ranges: list[dict] = field(default_factory=list)
    unreadable_ranges_truncated: bool = False
    error: str | None = None
    started_at: str = field(default_factory=utcnow)
    finished_at: str | None = None
    elapsed_s: float = 0.0
    throughput_mib_s: float = 0.0
    source: dict = field(default_factory=dict)
    destination: dict = field(default_factory=dict)
    partition_layout: dict | None = None
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))
    recoverx_version: str = __version__

    @property
    def successful(self) -> bool:
        return self.status == "completed" and self.image_verified and self.bytes_copied == self.size

    def to_dict(self) -> dict:
        d = asdict(self)
        d["successful"] = self.successful
        return d


ProgressFn = Callable[[dict], None]


def _read_with_recovery(source: BlockSource, offset: int, length: int, result: AcquisitionResult,
                        cancel: threading.Event | None) -> bytes:
    """Read one chunk. On a media error, retry sector by sector and zero-fill failures."""
    try:
        data = source.read_at(offset, length)
        if len(data) == length:
            return data
        if not data:
            raise DisconnectedError(0, f"Source returned no data at offset {offset}")
    except DisconnectedError:
        raise
    except OSError:
        pass
    ss = source.sector_size
    parts = []
    for pos in range(offset, offset + length, ss):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("cancelled")
        n = min(ss, offset + length - pos)
        try:
            piece = source.read_at(pos, n)
            if len(piece) != n:
                raise OSError(f"short read ({len(piece)} of {n} bytes)")
        except DisconnectedError:
            raise
        except OSError as exc:
            piece = b"\x00" * n
            result.unreadable_bytes += n
            code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
            last = result.unreadable_ranges[-1] if result.unreadable_ranges else None
            if last and last["offset"] + last["length"] == pos:
                last["length"] += n
            elif len(result.unreadable_ranges) < MAX_ERROR_RANGES:
                result.unreadable_ranges.append({"offset": pos, "length": n, "error": str(code or exc)[:120]})
            else:
                result.unreadable_ranges_truncated = True
        parts.append(piece)
    return b"".join(parts)


def hash_file(path: Path, cancel: threading.Event | None = None, progress: ProgressFn | None = None,
              stage: str = "verifying_image") -> str:
    h = hashlib.sha256()
    total = path.stat().st_size
    done, last = 0, 0.0
    with open(path, "rb", buffering=0) as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            chunk = f.read(CHUNK * 4)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress and time.monotonic() - last > 0.4:
                last = time.monotonic()
                progress({"stage": stage, "bytes_done": done, "bytes_total": total})
    return h.hexdigest()


def acquire(source: BlockSource, dest: str | Path, *, cancel: threading.Event | None = None,
            progress: ProgressFn | None = None, chunk_size: int = CHUNK, reread_source: bool = False) -> AcquisitionResult:
    """Stream source → new file. Never overwrites an existing file."""
    dest = Path(dest)
    if dest.suffix.lower() != ".img":
        raise ValueError("Destination image must use the .img extension")
    ss = max(512, int(source.sector_size or 512))
    if chunk_size % ss:
        chunk_size = max(ss, (chunk_size // ss) * ss)
    result = AcquisitionResult(status="running", image_path=str(dest), size=int(source.size), sector_size=ss,
                               source=dict(source.description))
    t0 = time.perf_counter()
    stream = hashlib.sha256()
    last_emit = 0.0

    def emit(stage, **extra):
        if progress:
            elapsed = max(time.perf_counter() - t0, 1e-6)
            progress({"stage": stage, "bytes_done": result.bytes_copied, "bytes_total": result.size,
                      "rate_bps": result.bytes_copied / elapsed, "unreadable_bytes": result.unreadable_bytes,
                      **extra})

    out = None
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        out = os.fdopen(fd, "wb", buffering=0)
        emit("imaging")
        offset = 0
        while offset < result.size:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            n = min(chunk_size, result.size - offset)
            data = _read_with_recovery(source, offset, n, result, cancel)
            out.write(data)
            stream.update(data)
            offset += len(data)
            result.bytes_copied = offset
            if result.unreadable_bytes > max(MAX_UNREADABLE_BYTES, result.size // 20):
                raise OSError("Too many unreadable sectors; the device may be failing. Imaging stopped.")
            if time.perf_counter() - last_emit > 0.4:
                last_emit = time.perf_counter()
                emit("imaging")
        out.flush()
        os.fsync(out.fileno())
        out.close()
        out = None
        result.source_stream_sha256 = stream.hexdigest()
        emit("verifying_image")
        result.image_sha256 = hash_file(dest, cancel, progress)
        on_disk = dest.stat().st_size
        result.image_verified = (result.image_sha256 == result.source_stream_sha256 and on_disk == result.size)
        if reread_source:
            emit("rereading_source")
            h = hashlib.sha256()
            pos = 0
            while pos < result.size:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("cancelled")
                n = min(chunk_size, result.size - pos)
                scratch = AcquisitionResult(status="reread", image_path="", size=0, sector_size=ss)
                h.update(_read_with_recovery(source, pos, n, scratch, cancel))
                pos += n
                if progress and time.perf_counter() - last_emit > 0.4:
                    last_emit = time.perf_counter()
                    progress({"stage": "rereading_source", "bytes_done": pos, "bytes_total": result.size})
            result.source_reread_sha256 = h.hexdigest()
            result.source_reread_matches = result.source_reread_sha256 == result.source_stream_sha256
        if not result.image_verified:
            result.status, result.error = "failed", "Destination image hash or size does not match the source stream"
        elif result.source_reread_matches is False:
            result.status = "failed"
            result.error = "Source changed between the imaging pass and the verification re-read"
        elif result.unreadable_bytes:
            result.status = "completed_with_errors"
            result.error = f"{result.unreadable_bytes} bytes were unreadable and are zero-filled in the image"
        else:
            result.status = "completed"
    except InterruptedError:
        result.status, result.error = "cancelled", "Acquisition cancelled by the examiner"
    except DisconnectedError as exc:
        result.status, result.error = "disconnected", f"Source device disconnected or stopped responding: {exc}"
    except FileExistsError:
        result.status, result.error = "failed", f"Refusing to overwrite existing file {dest}"
        dest = None
    except OSError as exc:
        result.status, result.error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        if out is not None:
            try:
                out.close()
            except OSError:
                pass
        result.elapsed_s = round(time.perf_counter() - t0, 3)
        result.throughput_mib_s = round(result.bytes_copied / max(result.elapsed_s, 1e-6) / 2**20, 2)
        result.finished_at = utcnow()
    if dest is not None and result.status in ("cancelled", "disconnected", "failed") and dest.exists():
        partial = dest.with_name(dest.name + ".partial")
        try:
            os.replace(dest, partial)
            result.image_path = str(partial)
        except OSError as exc:
            result.error = f"{result.error}; could not mark partial image: {exc}"
    if result.status in ("completed", "completed_with_errors"):
        try:
            from .partitions import layout_of_image
            result.partition_layout = layout_of_image(dest, ss)
        except (OSError, ValueError) as exc:
            result.partition_layout = {"scheme": "unknown", "partitions": [], "warnings": [str(exc)]}
    emit("finished", status=result.status)
    return result


def validate_destination(dest_dir: str | Path, *, required_bytes: int, source_disk: int | None,
                         disks_for_path: Callable[[str], set[int]] | None = None) -> list[str]:
    """Return blocking problems (empty list = safe). Creates nothing except a probe file."""
    problems: list[str] = []
    d = Path(dest_dir).expanduser()
    if not d.is_absolute():
        problems.append("Choose an absolute output folder path")
        return problems
    s = str(d)
    if s.startswith("\\\\") and not s.startswith("\\\\?\\"):
        problems.append("Network shares are not supported: their physical disk cannot be verified")
        return problems
    probe_dir = d
    while not probe_dir.exists() and probe_dir.parent != probe_dir:
        probe_dir = probe_dir.parent
    if not probe_dir.exists():
        problems.append("The output folder's drive does not exist")
        return problems
    if source_disk is not None:
        lookup = disks_for_path or (win32.disks_for_path if win32.IS_WINDOWS else None)
        if lookup is None:
            problems.append("Cannot map the output folder to a physical disk on this platform")
        else:
            try:
                disks = lookup(str(probe_dir))
                if source_disk in disks:
                    problems.append(f"The output folder is on the source disk (Disk {source_disk}). "
                                    "Choose a folder on a different physical disk.")
            except OSError as exc:
                problems.append(f"Cannot verify which physical disk holds the output folder: {exc}")
    free = shutil.disk_usage(probe_dir).free
    if free < required_bytes + SAFETY_MARGIN:
        problems.append(f"Not enough free space: {free:,} bytes free, {required_bytes + SAFETY_MARGIN:,} needed "
                        "(image size plus a 64 MiB safety margin)")
    if d.exists() and not d.is_dir():
        problems.append("The output path exists and is not a folder")
        return problems
    try:
        # Probe the folder itself if it exists, otherwise its nearest existing parent
        # (nothing is created until a job actually starts).
        probe = probe_dir / f".recoverx-write-probe-{os.getpid()}-{threading.get_ident()}"
        with open(probe, "xb") as f:
            f.write(b"ok")
        probe.unlink()
    except OSError as exc:
        problems.append(f"The output folder is not writable: {exc}")
    return problems
