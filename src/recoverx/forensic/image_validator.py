"""Evidence-image validation and output-path safety checks."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..exceptions import ImageValidationError, UnsafePathError

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
# Raw images were verified with TSK 4.12.1 and PhotoRec 7.1. Other formats are
# not claimed until tested (see docs/feasibility.md).
VERIFIED_EXTENSIONS = {".img", ".dd", ".raw", ".bin", ".001"}


def validate_image(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if "\x00" in str(path):
        raise ImageValidationError("path contains NUL byte")
    try:
        p = p.resolve(strict=True)
    except (FileNotFoundError, OSError) as e:
        raise ImageValidationError(f"image not found: {path}") from e
    if not p.is_file():
        raise ImageValidationError(f"not a regular file: {p}")
    if not os.access(p, os.R_OK):
        raise ImageValidationError(f"image not readable: {p}")
    if p.stat().st_size == 0:
        raise ImageValidationError("image is empty")
    return p


def is_verified_format(p: Path) -> bool:
    return p.suffix.lower() in VERIFIED_EXTENSIONS


def safe_identifier(value: str) -> str:
    if not SAFE_ID.match(value or "") or ".." in value:
        raise UnsafePathError(f"unsafe identifier: {value!r}")
    return value


def ensure_safe_output(output_dir: str | Path, evidence: str | Path) -> Path:
    """Refuse output locations equal to, inside, or containing the evidence file."""
    out = Path(output_dir).expanduser().resolve()
    ev = Path(evidence).expanduser().resolve()
    if out == ev or ev in out.parents:
        raise UnsafePathError("output path collides with the evidence image")
    if out.exists() and not out.is_dir():
        raise UnsafePathError(f"output path exists and is not a directory: {out}")
    return out


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join untrusted parts under base, rejecting traversal."""
    b = Path(base).resolve()
    target = b.joinpath(*parts).resolve()
    if target != b and b not in target.parents:
        raise UnsafePathError(f"path traversal rejected: {parts}")
    return target
