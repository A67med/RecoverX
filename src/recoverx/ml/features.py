"""Pre-recovery feature extraction. Every feature comes from fsstat/fls/mmls output
(see FEATURE_DOCS); none uses ground truth, scenario labels or recovery outcomes."""
from __future__ import annotations

from ..forensic.filesystem_analyzer import FsAnalysis

FEATURE_SCHEMA_VERSION = "1"

FEATURE_DOCS = {
    "fs_detected": ("1 if fsstat identified a filesystem at some offset, else 0", "fsstat exit status"),
    "fs_fat": ("1 if fsstat type contains FAT", "fsstat 'File System Type'"),
    "fs_ext": ("1 if fsstat type contains Ext", "fsstat 'File System Type'"),
    "has_partition_table": ("1 if mmls parsed >=1 partition", "mmls"),
    "image_mb": ("image size in MiB", "os.stat"),
    "n_allocated": ("allocated regular files (excluding $-metafiles)", "fls -r -l -p"),
    "n_deleted": ("deleted regular-file entries", "fls -r -l -p ('*' flag)"),
    "n_deleted_named": ("deleted entries not under $OrphanFiles", "fls path"),
    "n_deleted_nonzero": ("deleted entries whose metadata still records size > 0", "fls -l size column"),
    "frac_deleted_nonzero": ("n_deleted_nonzero / n_deleted (0 when n_deleted = 0)", "derived"),
    "n_realloc": ("deleted entries flagged (realloc) by TSK", "fls"),
}
FEATURE_NAMES = list(FEATURE_DOCS)
# Missing-value policy: when no filesystem is detected, fs_* and all fls-derived
# counts are 0 and fs_detected = 0 distinguishes "none found" from "zero entries".


def extract_features(a: FsAnalysis) -> dict[str, float]:
    fs = (a.fs_type or "").lower()
    dels = a.deleted_entries
    nonzero = sum(1 for d in dels if (d.size or 0) > 0)
    f = {
        "fs_detected": float(a.fs_type is not None),
        "fs_fat": float("fat" in fs),
        "fs_ext": float("ext" in fs),
        "has_partition_table": float(bool(a.partitions)),
        "image_mb": round(a.image_size / 2**20, 3),
        "n_allocated": float(a.allocated_files),
        "n_deleted": float(len(dels)),
        "n_deleted_named": float(sum(1 for d in dels if "$OrphanFiles" not in d.path)),
        "n_deleted_nonzero": float(nonzero),
        "frac_deleted_nonzero": round(nonzero / len(dels), 4) if dels else 0.0,
        "n_realloc": float(sum(d.realloc for d in dels)),
    }
    assert list(f) == FEATURE_NAMES
    return f


def validate_features(f: dict) -> list[float]:
    missing = [k for k in FEATURE_NAMES if k not in f]
    if missing:
        raise ValueError(f"feature schema mismatch, missing: {missing}")
    return [float(f[k]) for k in FEATURE_NAMES]
