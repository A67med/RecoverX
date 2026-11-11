"""Deduplication, ground-truth matching and recovery metrics (spec §8, §12, §13).

Counting rules (fixed before evaluation):
  * A ground-truth (GT) file is recovered *exactly* iff some output has the same
    SHA-256. Names are never used for matching.
  * Each GT file counts once, however many outputs/engines produced it.
  * Identical-content GT files share one hash; they are counted by distinct hash
    (the generator avoids duplicate GT content, and the manifest validator checks it).
  * Outputs matching a still-allocated file are `known_allocated_file`: neither a
    hit nor a false candidate.
  * All other outputs are `unverified` and count as false candidates.
    false_candidate_rate = unverified / total outputs.
  * No partial/near-match metric is defined, so none is reported."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..models import RecoveredFile


def assign_duplicate_groups(files: list[RecoveredFile]) -> dict[str, list[RecoveredFile]]:
    by_hash: dict[str, list[RecoveredFile]] = defaultdict(list)
    for f in files:
        f.duplicate_group = None
        by_hash[f.sha256].append(f)
    for sha, group in by_hash.items():
        if len(group) > 1:
            for f in group:
                f.duplicate_group = f"dg-{sha[:12]}"
    return by_hash


def canonical_view(files: list[RecoveredFile]) -> list[dict]:
    """One row per distinct content, keeping every engine/output that produced it."""
    rows = []
    for sha, group in assign_duplicate_groups(files).items():
        first = group[0]
        rows.append({
            "sha256": sha, "size": first.size, "detected_type": first.detected_type,
            "engines": sorted({f.engine for f in group}),
            "outputs": [f.recovery_id for f in group],
            "original_name": next((f.original_name for f in group if f.original_name), None),
            "integrity_state": first.integrity_state, "ground_truth_id": first.ground_truth_id,
        })
    return rows


def apply_ground_truth(files: Iterable[RecoveredFile], gt: dict | None) -> None:
    files = list(files)
    for f in files:
        f.ground_truth_id = None
    if not gt:
        for f in files:
            f.integrity_state = "invalid_or_unreadable" if f.detected_type == "unreadable" else "ground_truth_unavailable"
        return
    deleted = {d["sha256"]: d["id"] for d in gt.get("deleted", [])}
    allocated = {a["sha256"] for a in gt.get("allocated", [])}
    for f in files:
        if f.detected_type == "unreadable":
            f.integrity_state = "invalid_or_unreadable"
        elif f.sha256 in deleted:
            f.integrity_state, f.ground_truth_id = "verified_exact_match", deleted[f.sha256]
        elif f.sha256 in allocated:
            f.integrity_state = "known_allocated_file"
        else:
            f.integrity_state = "unverified"


def recovery_metrics(files: list[RecoveredFile], gt: dict | None) -> dict:
    n_out = len(files)
    distinct = len({f.sha256 for f in files})
    m = {"outputs": n_out, "distinct_contents": distinct, "duplicate_outputs": n_out - distinct}
    if not gt:
        m.update({"ground_truth": False})
        return m
    gt_hashes = {d["sha256"] for d in gt.get("deleted", [])}
    hit = {f.sha256 for f in files if f.integrity_state == "verified_exact_match"}
    unverified = sum(f.integrity_state == "unverified" for f in files)
    m.update({
        "ground_truth": True,
        "gt_files": len(gt_hashes),
        "exact_recovered": len(hit),
        "unrecovered": len(gt_hashes - hit),
        "recall": (len(hit) / len(gt_hashes)) if gt_hashes else None,
        "known_allocated_outputs": sum(f.integrity_state == "known_allocated_file" for f in files),
        "unverified_outputs": unverified,
        "false_candidate_rate": (unverified / n_out) if n_out else 0.0,
        "recovered_gt_ids": sorted({f.ground_truth_id for f in files if f.ground_truth_id}),
    })
    return m
