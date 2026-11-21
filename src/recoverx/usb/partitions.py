"""Read-only MBR / GPT / superfloppy detection for raw images.

Independent of The Sleuth Kit; used to record the partition layout in the
acquisition record and to cross-check mmls offsets. Offsets are reported in
bytes and in 512-byte sectors (TSK's default unit). Only parsing — nothing is
mounted or modified.
"""
from __future__ import annotations

import struct
import uuid
from pathlib import Path

MBR_TYPES = {
    0x01: "FAT12", 0x04: "FAT16 <32M", 0x06: "FAT16", 0x07: "NTFS/exFAT", 0x0B: "FAT32 (CHS)",
    0x0C: "FAT32 (LBA)", 0x0E: "FAT16 (LBA)", 0x0F: "Extended (LBA)", 0x05: "Extended",
    0x83: "Linux", 0x82: "Linux swap", 0xEE: "GPT protective", 0xEF: "EFI system",
}
GPT_TYPES = {
    "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": "Microsoft basic data",
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": "EFI system",
    "e3c9e316-0b5c-4db8-817d-f92df00215ae": "Microsoft reserved",
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac": "Windows recovery",
    "0fc63daf-8483-4772-8e79-3d69d8477de4": "Linux filesystem",
}


def detect_filesystem(boot: bytes) -> str | None:
    """Identify a volume boot record by its documented signatures."""
    if len(boot) < 512:
        return None
    if boot[3:11] == b"NTFS    ":
        return "NTFS"
    if boot[3:11] == b"EXFAT   ":
        return "exFAT"
    if boot[510:512] == b"\x55\xaa" and boot[0] in (0xEB, 0xE9):
        if boot[82:87] == b"FAT32":
            return "FAT32"
        if boot[54:59] in (b"FAT12", b"FAT16", b"FAT  "):
            return boot[54:59].decode("ascii").strip() or "FAT"
        bps = struct.unpack_from("<H", boot, 11)[0]
        if bps in (512, 1024, 2048, 4096) and boot[13] in (1, 2, 4, 8, 16, 32, 64, 128):
            return "FAT"
    return None


def _entry(index, start_lba, sectors, sector_size, kind, name):
    return {"index": index, "start_lba": start_lba, "sectors": sectors, "offset_bytes": start_lba * sector_size,
            "size_bytes": sectors * sector_size, "tsk_sector_offset": (start_lba * sector_size) // 512,
            "type": kind, "description": name}


def parse_layout(read, size: int, sector_size: int = 512) -> dict:
    """read(offset, length) -> bytes. Returns {'scheme', 'partitions', 'warnings'}."""
    warnings: list[str] = []
    lba0 = read(0, sector_size)
    if len(lba0) < 512:
        return {"scheme": "unreadable", "partitions": [], "warnings": ["Image shorter than one sector"]}
    fs0 = detect_filesystem(lba0)
    if fs0:
        return {"scheme": "superfloppy", "partitions": [_entry(0, 0, size // sector_size, sector_size, fs0,
                                                               f"{fs0} volume without a partition table")],
                "warnings": warnings}
    if lba0[510:512] != b"\x55\xaa":
        return {"scheme": "none", "partitions": [], "warnings": ["No MBR signature: no partition table found"]}
    entries = []
    for i in range(4):
        e = lba0[446 + i * 16: 462 + i * 16]
        ptype = e[4]
        start, count = struct.unpack_from("<II", e, 8)
        if ptype and count:
            entries.append((i + 1, ptype, start, count))
    if any(t == 0xEE for _, t, _, _ in entries):
        return _parse_gpt(read, size, sector_size, warnings)
    parts = []
    for idx, ptype, start, count in entries:
        if start * sector_size >= size:
            warnings.append(f"MBR entry {idx} starts beyond the end of the image")
            continue
        if (start + count) * sector_size > size:
            warnings.append(f"MBR entry {idx} extends beyond the end of the image (truncated media?)")
        if ptype in (0x05, 0x0F, 0x85):
            parts.extend(_parse_ebr(read, size, sector_size, start, warnings))
            continue
        fs = detect_filesystem(read(start * sector_size, 512))
        parts.append(_entry(idx, start, count, sector_size, fs or MBR_TYPES.get(ptype, f"type 0x{ptype:02X}"),
                            MBR_TYPES.get(ptype, f"MBR type 0x{ptype:02X}")))
    return {"scheme": "MBR", "partitions": parts, "warnings": warnings}


def _parse_ebr(read, size, sector_size, ext_start, warnings, limit=64):
    out, next_ebr, n = [], ext_start, 5
    seen = set()
    while next_ebr and len(out) < limit and next_ebr not in seen:
        seen.add(next_ebr)
        ebr = read(next_ebr * sector_size, 512)
        if len(ebr) < 512 or ebr[510:512] != b"\x55\xaa":
            warnings.append("Damaged extended partition chain")
            break
        t1, s1, c1 = ebr[446 + 4], *struct.unpack_from("<II", ebr, 446 + 8)
        if t1 and c1:
            start = next_ebr + s1
            fs = detect_filesystem(read(start * sector_size, 512))
            out.append(_entry(n, start, c1, sector_size, fs or MBR_TYPES.get(t1, f"type 0x{t1:02X}"), "Logical"))
            n += 1
        t2, s2, _ = ebr[462 + 4], *struct.unpack_from("<II", ebr, 462 + 8)
        next_ebr = ext_start + s2 if t2 and s2 else 0
    return out


def _parse_gpt(read, size, sector_size, warnings):
    hdr = read(sector_size, 92)
    if hdr[:8] != b"EFI PART":
        warnings.append("Protective MBR present but GPT header missing")
        return {"scheme": "GPT (damaged)", "partitions": [], "warnings": warnings}
    entries_lba, count, entry_size = struct.unpack_from("<QII", hdr, 72)
    if entry_size < 128 or count > 1024:
        warnings.append("Implausible GPT entry table")
        return {"scheme": "GPT (damaged)", "partitions": [], "warnings": warnings}
    table = read(entries_lba * sector_size, count * entry_size)
    parts = []
    for i in range(count):
        e = table[i * entry_size:(i + 1) * entry_size]
        if len(e) < 128 or e[:16] == b"\x00" * 16:
            continue
        type_guid = str(uuid.UUID(bytes_le=e[:16]))
        first, last = struct.unpack_from("<QQ", e, 32)
        name = e[56:128].decode("utf-16-le", errors="replace").rstrip("\x00")
        if first * sector_size >= size:
            warnings.append(f"GPT entry {i + 1} starts beyond the end of the image")
            continue
        fs = detect_filesystem(read(first * sector_size, 512))
        parts.append(_entry(i + 1, first, last - first + 1, sector_size,
                            fs or GPT_TYPES.get(type_guid, "unknown"), name or GPT_TYPES.get(type_guid, type_guid)))
    return {"scheme": "GPT", "partitions": parts, "warnings": warnings}


def layout_of_image(path: str | Path, sector_size: int = 512) -> dict:
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        def read(offset, length):
            f.seek(offset)
            return f.read(length)
        result = parse_layout(read, size, sector_size)
    if sector_size != 512:
        result["warnings"].append(f"Logical sector size is {sector_size} bytes; TSK offsets are given in 512-byte units")
    return result
