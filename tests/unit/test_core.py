import json
import random

import pytest

from recoverx.datasets.generator import make_content, merge_ranges, overlap_bytes
from recoverx.forensic.filesystem_analyzer import FsAnalysis, _parse_fls, _parse_mmls
from recoverx.forensic.hashing import sha256_bytes, sha256_file
from recoverx.ml.features import FEATURE_NAMES, extract_features, validate_features
from recoverx.ml.labeling import derive_label, load_objective
from recoverx.ml.selector import CartSelector, rule_select
from recoverx.models import RecoveredFile
from recoverx.recovery.integrity import (apply_ground_truth, assign_duplicate_groups, canonical_view,
                                         recovery_metrics)


def test_sha256_known_vector(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    assert sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_bytes(b"abc") == sha256_file(p)


def _rf(sha, engine="tsk", i=0, typ="png"):
    return RecoveredFile(recovery_id=f"{engine}-{i}", engine=engine, run_id="r", recovered_name=f"f{i}",
                         relative_path=f"f{i}", size=1, sha256=sha, extension="png", detected_type=typ)


GT = {"deleted": [{"id": "g1", "sha256": "h1"}, {"id": "g2", "sha256": "h2"}, {"id": "g3", "sha256": "h3"}],
      "allocated": [{"sha256": "a1"}]}


def test_ground_truth_matching_is_hash_based_and_counts_once():
    files = [_rf("h1", "tsk", 0), _rf("h1", "photorec", 1), _rf("a1", "photorec", 2), _rf("zz", "photorec", 3)]
    apply_ground_truth(files, GT)
    assert [f.integrity_state for f in files] == ["verified_exact_match", "verified_exact_match",
                                                   "known_allocated_file", "unverified"]
    m = recovery_metrics(files, GT)
    assert m["exact_recovered"] == 1 and m["gt_files"] == 3 and m["unrecovered"] == 2
    assert m["recall"] == pytest.approx(1 / 3)
    assert m["duplicate_outputs"] == 1 and m["unverified_outputs"] == 1
    assert m["false_candidate_rate"] == pytest.approx(0.25)


def test_name_match_with_wrong_hash_is_not_recovery():
    f = _rf("different")
    f.original_name = "g1"
    apply_ground_truth([f], GT)
    assert f.integrity_state == "unverified"


def test_dedup_preserves_provenance():
    files = [_rf("h1", "tsk", 0), _rf("h1", "photorec", 1)]
    apply_ground_truth(files, GT)
    rows = canonical_view(files)
    assert len(rows) == 1 and rows[0]["engines"] == ["photorec", "tsk"] and len(rows[0]["outputs"]) == 2
    assert all(f.duplicate_group for f in files)


def test_no_ground_truth_state():
    files = [_rf("h1")]
    apply_ground_truth(files, None)
    assert files[0].integrity_state == "ground_truth_unavailable"
    assert recovery_metrics(files, None)["ground_truth"] is False


FLS_SAMPLE = (
    "r/r * 3:\t_oc0.txt\t2026\t2026\t0000\t2026\t13200\t0\t0\n"
    "r/r 4:\tdoc1.txt\t2026\t2026\t0000\t2026\t13200\t0\t0\n"
    "r/r * 9(realloc):\tx.png\t2026\t2026\t0000\t2026\t500\t0\t0\n"
    "-/r * 12:\t$OrphanFiles/OrphanFile-12\t0\t0\t0\t0\t0\t0\t0\n"
    "d/d 11:\tlost+found\t0\t0\t0\t0\t16384\t0\t0\n"
    "V/V 4097:\t$OrphanFiles\t0\t0\t0\t0\t0\t0\t0\n"
)


def test_parse_fls_and_features():
    deleted, allocated = _parse_fls(FLS_SAMPLE)
    assert allocated == 1 and len(deleted) == 3
    a = FsAnalysis(status="analysis_completed", image_size=2**20 * 64, fs_type="FAT16",
                   allocated_files=allocated, deleted_entries=deleted)
    f = extract_features(a)
    assert list(f) == FEATURE_NAMES
    assert f["n_deleted"] == 3 and f["n_deleted_nonzero"] == 2 and f["n_deleted_named"] == 2
    assert f["n_realloc"] == 1 and f["fs_fat"] == 1 and f["image_mb"] == 64


def test_features_when_no_filesystem():
    f = extract_features(FsAnalysis(status="filesystem_not_detected", image_size=1024))
    assert f["fs_detected"] == 0 and f["n_deleted"] == 0 and f["frac_deleted_nonzero"] == 0
    assert rule_select(f)[0] == "photorec"


def test_feature_schema_validation():
    with pytest.raises(ValueError):
        validate_features({"fs_detected": 1})


def test_parse_mmls():
    out = ("     Slot      Start        End          Length       Description\n"
           "000:  Meta      0000000000   0000000000   0000000001   Primary Table (#0)\n"
           "001:  -------   0000000000   0000002047   0000002048   Unallocated\n"
           "002:  000:000   0000002048   0000204799   0000202752   Linux (0x83)\n")
    p = _parse_mmls(out)
    assert len(p) == 1 and p[0].start_sector == 2048


def test_label_objective():
    per = {"tsk": {"recall": 1.0, "times": [0.2, 0.3, 0.25]},
           "photorec": {"recall": 1.0, "times": [0.4, 0.5, 0.45]},
           "combined": {"recall": 1.0, "times": [0.6, 0.7, 0.65]}}
    assert derive_label(per)["label"] == "tsk"
    per["tsk"]["recall"] = 0.5
    assert derive_label(per)["label"] == "photorec"
    per["photorec"]["recall"] = 0.97  # within tolerance 0.05 of combined (1.0)
    assert derive_label(per)["label"] == "photorec"
    per["photorec"]["recall"] = 0.90
    assert derive_label(per)["label"] == "combined"
    zero = {s: {"recall": 0.0, "times": [t]} for s, t in [("tsk", 0.3), ("photorec", 0.2), ("combined", 0.5)]}
    r = derive_label(zero)
    assert r["label"] == "photorec" and r["fallback_nothing_recoverable"]


def test_label_tie_break_order():
    per = {s: {"recall": 1.0, "times": [0.5]} for s in ("combined", "photorec", "tsk")}
    assert derive_label(per)["label"] == "tsk"


def test_rule_policy():
    base = {k: 0.0 for k in FEATURE_NAMES}
    assert rule_select({**base, "fs_detected": 1, "n_deleted_nonzero": 3, "frac_deleted_nonzero": 1.0})[0] == "tsk"
    assert rule_select({**base, "fs_detected": 1, "n_deleted_nonzero": 3, "frac_deleted_nonzero": 0.5})[0] == "combined"
    assert rule_select({**base, "fs_detected": 1, "n_deleted_nonzero": 0})[0] == "photorec"


def test_cart_train_save_load_predict(tmp_path):
    rng = random.Random(0)
    X, y = [], []
    for _ in range(40):
        nz = rng.randint(0, 5)
        row = {k: 0.0 for k in FEATURE_NAMES} | {"fs_detected": 1.0, "n_deleted_nonzero": float(nz),
                                                  "n_deleted": 5.0, "image_mb": 48.0}
        X.append(validate_features(row))
        y.append("tsk" if nz > 2 else "photorec")
    m = CartSelector.train(X, y, max_depth=3, min_samples_leaf=1, seed=0)
    d = m.save(tmp_path, "v-test")
    m2 = CartSelector.load(d)
    f = {k: 0.0 for k in FEATURE_NAMES} | {"fs_detected": 1.0, "n_deleted_nonzero": 5.0, "n_deleted": 5.0, "image_mb": 48.0}
    p = m2.predict(f)
    assert p["strategy"] == "tsk" and p["decision_path"]
    assert m2.predict({**f, "image_mb": 9999})["out_of_training_range"] == ["image_mb"]
    meta = json.loads((d / "meta.json").read_text())
    assert meta["model_type"].startswith("sklearn.tree.DecisionTreeClassifier")
    assert abs(sum(meta["feature_importance"].values()) - 1) < 1e-6


def test_model_schema_mismatch_rejected(tmp_path):
    from recoverx.exceptions import ModelError
    m = CartSelector.train([[0.0] * len(FEATURE_NAMES)] * 2, ["tsk", "tsk"], max_depth=1, min_samples_leaf=1)
    d = m.save(tmp_path, "v")
    meta = json.loads((d / "meta.json").read_text())
    meta["feature_names"] = ["other"]
    (d / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(ModelError):
        CartSelector.load(d)


# ---------------- reproducibility
def test_content_generation_is_deterministic():
    for t in ("png", "jpg", "pdf", "txt", "zip", "bin"):
        a = make_content(t, 30000, random.Random("seed"))
        b = make_content(t, 30000, random.Random("seed"))
        assert a == b, t


def test_extent_helpers():
    assert merge_ranges([(0, 512), (512, 512), (2048, 512)]) == [(0, 1024), (2048, 512)]
    assert overlap_bytes([(0, 1000)], [(500, 1000)]) == 500


def test_objective_config_frozen_values():
    from recoverx.benchmarking.experiment import OBJECTIVE_PATH
    obj = load_objective(OBJECTIVE_PATH)
    assert obj["tolerance"] == 0.05 and obj["tie_break_order"] == ["tsk", "photorec", "combined"]


def test_feature_schema_stable():
    assert FEATURE_NAMES == ["fs_detected", "fs_fat", "fs_ext", "has_partition_table", "image_mb", "n_allocated",
                             "n_deleted", "n_deleted_named", "n_deleted_nonzero", "frac_deleted_nonzero", "n_realloc"]
