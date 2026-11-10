"""Pre-recovery inspection with TSK (mmls / fsstat / fls). Read-only.

Everything this module returns is available BEFORE any recovery runs, so it is
legitimate input for strategy selection. Its elapsed time is charged to the
selector-based methods (spec §9)."""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..process import run_command

FLS_LINE = re.compile(r"^(?P<type>\S+)\s+(?P<deleted>\*\s+)?(?P<inode>[\d-]+)(?P<realloc>\(realloc\))?:\t(?P<rest>.*)$")


@dataclass
class Partition:
    slot: str
    start_sector: int
    length: int
    description: str


@dataclass
class DeletedEntry:
    inode: str
    path: str
    size: int | None
    realloc: bool
    entry_type: str


@dataclass
class FsAnalysis:
    status: str
    image_size: int
    sector_offset: int = 0
    partitions: list[Partition] = field(default_factory=list)
    fs_type: str | None = None
    fsstat_excerpt: str = ""
    allocated_files: int = 0
    deleted_entries: list[DeletedEntry] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_mmls(stdout: str) -> list[Partition]:
    parts = []
    for line in stdout.splitlines():
        m = re.match(r"^\s*(\d+):\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)$", line)
        if m and not m.group(2).startswith("Meta") and "Unallocated" not in m.group(6):
            parts.append(Partition(m.group(2), int(m.group(3)), int(m.group(5)), m.group(6).strip()))
    return parts


def _parse_fls(stdout: str) -> tuple[list[DeletedEntry], int]:
    deleted, allocated = [], 0
    for line in stdout.splitlines():
        m = FLS_LINE.match(line)
        if not m:
            continue
        typ = m.group("type")
        fields = m.group("rest").split("\t")
        path = fields[0]
        size = None
        if len(fields) >= 6:
            try:
                size = int(fields[5])
            except ValueError:
                size = None
        is_file = typ.startswith("r/") or typ.startswith("-/r")
        if m.group("deleted"):
            if is_file:
                deleted.append(DeletedEntry(m.group("inode"), path, size, bool(m.group("realloc")), typ))
        elif is_file and not path.startswith("$"):
            allocated += 1
    return deleted, allocated


def analyze_image(image: str | Path, timeout: float = 300) -> FsAnalysis:
    image = str(image)
    t0 = time.perf_counter()
    res = FsAnalysis(status="analysis_failed", image_size=Path(image).stat().st_size)

    mm = run_command(["mmls", image], timeout=timeout)
    res.commands.append(mm.to_dict(1500))
    if mm.returncode is None:
        res.status = "tool_unavailable"
        res.errors.append(mm.stderr)
        res.elapsed_s = time.perf_counter() - t0
        return res
    res.partitions = _parse_mmls(mm.stdout) if mm.ok else []
    offsets = [p.start_sector for p in res.partitions] or [0]
    if 0 not in offsets:
        offsets.append(0)

    for off in offsets:
        fs = run_command(["fsstat", "-o", str(off), image], timeout=timeout)
        res.commands.append(fs.to_dict(1500))
        if fs.ok:
            m = re.search(r"File System Type:\s*(.+)", fs.stdout)
            res.fs_type = m.group(1).strip() if m else "unknown"
            res.fsstat_excerpt = "\n".join(fs.stdout.splitlines()[:25])
            res.sector_offset = off
            break
    if res.fs_type is None:
        res.status = "filesystem_not_detected"
        res.elapsed_s = time.perf_counter() - t0
        return res

    fl = run_command(["fls", "-r", "-l", "-p", "-o", str(res.sector_offset), image], timeout=timeout)
    res.commands.append(fl.to_dict(1500))
    if fl.ok:
        res.deleted_entries, res.allocated_files = _parse_fls(fl.stdout)
        res.status = "analysis_completed"
    else:
        res.status = "partially_analyzed"
        res.errors.append(fl.stderr.strip()[:500])
    res.elapsed_s = round(time.perf_counter() - t0, 6)
    return res
