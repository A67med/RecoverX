"""Structural validation of recovered files. Parses bytes only; never renders or executes.

Returns one of: ``valid`` (structure markers present), ``invalid`` (markers missing
or inconsistent with the extension) or ``not_checked`` (no validator for this
format). ``valid`` means *structurally plausible*, not proof of an exact
reconstruction; only a hash match with a known original proves that.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

MAX_TAIL = 1024 * 1024


def _tail(f, n=MAX_TAIL) -> bytes:
    f.seek(0, 2)
    size = f.tell()
    f.seek(max(0, size - n))
    return f.read(n)


def validate_file(path: str | Path) -> dict:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    try:
        size = p.stat().st_size
        if size == 0:
            return {"state": "invalid", "format": ext or "unknown", "reason": "empty file"}
        with open(p, "rb") as f:
            head = f.read(16)
            if head.startswith(b"\xff\xd8\xff"):
                tail = _tail(f)
                ok = b"\xff\xd9" in tail[-4096:]
                return {"state": "valid" if ok else "invalid", "format": "jpeg",
                        "reason": "JPEG start and end markers present" if ok else "JPEG end marker (FFD9) missing — likely truncated"}
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                tail = _tail(f, 4096)
                ok = b"IEND" in tail
                return {"state": "valid" if ok else "invalid", "format": "png",
                        "reason": "PNG signature and IEND chunk present" if ok else "PNG IEND chunk missing — likely truncated"}
            if head.startswith(b"%PDF-"):
                tail = _tail(f, 4096)
                ok = b"%%EOF" in tail
                return {"state": "valid" if ok else "invalid", "format": "pdf",
                        "reason": "PDF header and %%EOF trailer present" if ok else "PDF %%EOF trailer missing — likely truncated"}
            if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
                ok = _tail(f, 16).rstrip(b"\x00").endswith(b"\x3b")
                return {"state": "valid" if ok else "invalid", "format": "gif",
                        "reason": "GIF header and trailer present" if ok else "GIF trailer missing"}
            if head.startswith(b"PK\x03\x04"):
                return _validate_zip(p, ext)
    except OSError as exc:
        return {"state": "invalid", "format": ext or "unknown", "reason": f"unreadable: {exc}"}
    if ext in ("jpg", "jpeg", "png", "pdf", "gif", "docx", "xlsx", "pptx", "zip"):
        return {"state": "invalid", "format": ext, "reason": f"content signature does not match .{ext}"}
    return {"state": "not_checked", "format": ext or "unknown", "reason": "no structural validator for this type"}


def _validate_zip(p: Path, ext: str) -> dict:
    try:
        with zipfile.ZipFile(p) as z:
            infos = z.infolist()
            names = {i.filename for i in infos[:5000]}
            # Bound decompression work (zip bombs): CRC-check only modest archives.
            bad = z.testzip() if len(infos) <= 5000 and sum(i.file_size for i in infos) <= 512 * 2**20 else None
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, NotImplementedError) as exc:
        return {"state": "invalid", "format": ext or "zip", "reason": f"ZIP container damaged: {str(exc)[:120]}"}
    office = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
    fmt = next((k for k, v in office.items() if v in names), "zip")
    if bad:
        return {"state": "invalid", "format": fmt, "reason": f"CRC error in member {bad[:80]}"}
    if fmt != "zip" and "[Content_Types].xml" not in names:
        return {"state": "invalid", "format": fmt, "reason": "Office package missing [Content_Types].xml"}
    if ext in office and fmt != ext:
        return {"state": "invalid", "format": fmt, "reason": f"ZIP content does not look like .{ext}"}
    return {"state": "valid", "format": fmt, "reason": "ZIP central directory and CRCs verified"
            + (f"; {fmt.upper()} package structure present" if fmt != "zip" else "")}
