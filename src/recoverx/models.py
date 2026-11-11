"""Shared data records. Everything persisted is plain JSON via to_dict()."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# Case / analysis states (spec §6)
CASE_STATES = (
    "validated", "analysis_completed", "partially_analyzed", "unsupported_format",
    "filesystem_not_detected", "tool_unavailable", "analysis_failed",
)

# Integrity states (spec §13)
INTEGRITY_STATES = (
    "verified_exact_match",      # SHA-256 equals a deleted ground-truth file
    "known_allocated_file",      # SHA-256 equals a file still allocated in the image (not a target)
    "unverified",                # ground truth exists, no hash match
    "invalid_or_unreadable",
    "ground_truth_unavailable",
)


@dataclass
class CommandResult:
    args: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_s: float
    started_at: str
    timed_out: bool = False
    cancelled: bool = False
    cwd: str | None = None
    output_truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled

    def to_dict(self, max_text: int = 4000) -> dict[str, Any]:
        d = asdict(self)
        d["stdout"] = self.stdout[-max_text:]
        d["stderr"] = self.stderr[-max_text:]
        return d


@dataclass
class RecoveredFile:
    recovery_id: str
    engine: str
    run_id: str
    recovered_name: str
    relative_path: str           # relative to the run output directory
    size: int
    sha256: str
    extension: str
    detected_type: str
    original_name: str | None = None
    original_metadata: dict[str, Any] = field(default_factory=dict)
    integrity_state: str = "ground_truth_unavailable"
    ground_truth_id: str | None = None
    duplicate_group: str | None = None
    notes: str = ""
    recovered_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineRun:
    engine: str
    run_id: str
    status: str                  # completed | failed | timed_out | blocked
    output_dir: str
    elapsed_s: float
    commands: list[dict[str, Any]] = field(default_factory=list)
    files: list[RecoveredFile] = field(default_factory=list)
    error: str | None = None
    tool_version: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["files"] = [f.to_dict() for f in self.files]
        return d
