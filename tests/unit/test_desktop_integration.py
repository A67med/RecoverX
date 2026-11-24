"""Tests for the components merged from the Windows Recovery Studio (RC1):
shared rule policy, portable CART tree, partition layout reader, TSK arguments and
the desktop scan worker on a synthetic MBR/FAT32 fixture (never a real device)."""
from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for sub in ("desktop", "validation"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

MODEL = ROOT / "research/results/exp1/models/cart-20261030-193546"


def test_rule_policy_has_a_single_source():
    from recoverx.ml import policy, selector
    assert selector.rule_select is policy.rule_select
    assert selector.RULE_POLICY_TEXT == policy.RULE_POLICY_TEXT
    assert policy.rule_select({"fs_detected": 0, "n_deleted_nonzero": 0, "frac_deleted_nonzero": 0,
                               "n_realloc": 0})[0] == "photorec"


def test_portable_tree_matches_archived_model_metadata():
    tree = json.loads((MODEL / "portable-tree.json").read_text())
    meta = json.loads((MODEL / "meta.json").read_text())
    assert tree["names"] == meta["feature_names"]
    # The archived model is the depth-1 stump reported in the paper.
    assert "n_deleted_named <= 4.50" in meta["tree_text"]
    from scan import cart_predict
    base = {k: 0.0 for k in meta["feature_names"]}
    assert cart_predict({**base, "n_deleted_named": 4.0}) == "photorec"
    assert cart_predict({**base, "n_deleted_named": 5.0}) == "tsk"


@pytest.fixture()
def fixture_image(tmp_path):
    from make_fixture import fat32_fixture
    fat32_fixture(tmp_path / "sample", ROOT / "validation/originals")
    return tmp_path / "sample"


def test_layout_finds_the_mbr_partition(fixture_image):
    from partitions import layout
    spans = layout(fixture_image / "three-deleted.img", 512)
    assert len(spans) == 1 and spans[0].start == 2048 * 512


def test_tsk_engine_passes_image_type_and_sector_size(tmp_path, monkeypatch):
    from recoverx.engines import sleuthkit_engine
    from recoverx.models import CommandResult
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return CommandResult(args=args, returncode=0, stdout="", stderr="", elapsed_s=0.0, started_at="")
    monkeypatch.setattr(sleuthkit_engine, "run_cmd", fake_run)
    eng = sleuthkit_engine.SleuthKitEngine()
    eng.sector_size = 4096
    out = tmp_path / "out"
    out.mkdir()
    from recoverx.models import EngineRun
    run = EngineRun(engine="tsk", run_id="t", status="failed", output_dir=str(out), elapsed_s=0.0)
    eng._execute(tmp_path / "img.raw", out, run, sector_offset=8, timeout=5, cancel_event=None)
    assert seen["args"][:5] == ["tsk_recover", "-i", "raw", "-b", "4096"]
    assert seen["args"][5:7] == ["-o", "8"]


@pytest.mark.skipif(not (shutil.which("tsk_recover") and shutil.which("photorec")),
                    reason="BLOCKED: tsk_recover/photorec not installed")
@pytest.mark.parametrize("method", ["tsk", "photorec", "combined"])
def test_desktop_worker_recovers_the_three_deleted_files(fixture_image, tmp_path, method):
    from scan import scan
    case = tmp_path / f"case-{method}"
    case.mkdir()
    shutil.copy(fixture_image / "three-deleted.img", case / "evidence.img")
    known = json.loads((fixture_image / "original-hashes.json").read_text())
    report = scan(case, method, 512, known, threading.Event(), lambda row: None)
    assert report["status"] == "completed", report["warnings"]
    assert report["metrics"]["exact_recovered"] == 3
    assert (case / "report.json").is_file()
