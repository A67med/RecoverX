"""Real TSK / PhotoRec runs on the generated FAT fixture. Skipped (reported as
BLOCKED) when tools are missing — never counted as passed."""
import json

import pytest

from recoverx.engines.photorec_engine import PhotoRecEngine
from recoverx.engines.sleuthkit_engine import SleuthKitEngine
from recoverx.forensic.case_store import build_manifest, create_case
from recoverx.forensic.filesystem_analyzer import analyze_image
from recoverx.ml.features import FEATURE_NAMES, extract_features
from recoverx.ml.selector import CartSelector
from recoverx.recovery.orchestrator import run_recovery
from tests.conftest import needs_tools

pytestmark = needs_tools


def _hashes(run):
    return {f.sha256 for f in run.files}


def test_analysis_finds_deleted_entries(fat_fixture):
    a = analyze_image(fat_fixture["image"])
    assert a.status == "analysis_completed" and "FAT16" in a.fs_type
    assert len(a.deleted_entries) == 2 and a.allocated_files == 2
    f = extract_features(a)
    assert f["n_deleted_nonzero"] == 2 and f["fs_fat"] == 1


def test_tsk_recovers_exact_files(fat_fixture, tmp_path):
    run = SleuthKitEngine().run(fat_fixture["image"], tmp_path / "tsk")
    assert run.status == "completed", run.error
    assert {d["sha256"] for d in fat_fixture["gt"]["deleted"]} <= _hashes(run)
    assert run.tool_version and run.commands[0]["returncode"] == 0


def test_photorec_recovers_exact_files_and_logs_in_output(fat_fixture, tmp_path):
    out = tmp_path / "pr"
    run = PhotoRecEngine().run(fat_fixture["image"], out)
    assert run.status == "completed", run.error
    assert {d["sha256"] for d in fat_fixture["gt"]["deleted"]} <= _hashes(run)
    assert (out / "photorec.log").exists()
    assert all(f.original_name is None for f in run.files)  # PhotoRec does not restore names
    assert any("carved_byte_runs" in f.original_metadata for f in run.files)


@pytest.mark.parametrize("method", ["tsk", "photorec", "combined", "rule", "manual:photorec"])
def test_orchestrator_methods(fat_fixture, method):
    case, _ = create_case(fat_fixture["image"])
    run = run_recovery(case, method, ground_truth=fat_fixture["gt"])
    assert run["source_unchanged"] is True
    assert run["metrics"]["recall"] == 1.0
    assert run["timing"]["total_s"] >= sum(v for k, v in run["timing"].items() if k.startswith("engine_"))
    if method == "combined":
        assert run["metrics"]["duplicate_outputs"] >= 2
        assert len(run["engine_runs"]) == 2
    if method.startswith("manual:"):
        assert run["selection"]["rationale"].startswith("manual") and run["selection"]["recommended"] == "tsk"


def test_cart_without_model_falls_back_transparently(fat_fixture):
    case, _ = create_case(fat_fixture["image"])
    run = run_recovery(case, "cart", ground_truth=fat_fixture["gt"])
    assert run["selection"]["fallback"] and "rule-v1" in run["selection"]["fallback"]
    assert run["selection"]["model_version"] == "rule-v1"


def test_cart_with_trained_model(fat_fixture, tmp_path):
    X = [[1.0] * len(FEATURE_NAMES), [0.0] * len(FEATURE_NAMES)]
    m = CartSelector.train(X, ["photorec", "tsk"], max_depth=2, min_samples_leaf=1)
    d = m.save(tmp_path / "models", "cart-test")
    case, _ = create_case(fat_fixture["image"])
    run = run_recovery(case, "cart", ground_truth=fat_fixture["gt"], model_dir=d)
    assert run["selection"]["model_version"] == "cart-test" and run["selection"]["fallback"] is None
    assert run["timing"]["analysis_s"] > 0 and "features_s" in run["timing"]


def test_manifest_and_events(fat_fixture):
    case, rec = create_case(fat_fixture["image"])
    run_recovery(case, "combined", ground_truth=fat_fixture["gt"])
    man = build_manifest(case)
    assert man["source"]["sha256_initial"] == rec["image_sha256_initial"]
    assert man["runs"][0]["source_unchanged"] and len(man["runs"][0]["engines"]) == 2
    assert all(c["args"] for e in man["runs"][0]["engines"] for c in e["commands"])
    kinds = [e["event"] for e in case.events()]
    assert kinds[0] == "case_created" and "run_finished" in kinds
    json.dumps(man)  # serialisable
