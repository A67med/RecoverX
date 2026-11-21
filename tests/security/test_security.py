import shutil
import sys
import threading
import time

import pytest

from recoverx.engines.photorec_engine import PhotoRecEngine
from recoverx.engines.sleuthkit_engine import SleuthKitEngine
from recoverx.exceptions import ImageValidationError, UnsafePathError
from recoverx.forensic.case_store import create_case, open_case
from recoverx.forensic.image_validator import ensure_safe_output, safe_identifier, safe_join, validate_image
from recoverx.process import run_command
from recoverx.recovery.orchestrator import run_recovery
from tests.conftest import needs_tools


def test_invalid_and_empty_paths(tmp_path):
    with pytest.raises(ImageValidationError):
        validate_image(tmp_path / "missing.img")
    (tmp_path / "empty.img").write_bytes(b"")
    with pytest.raises(ImageValidationError):
        validate_image(tmp_path / "empty.img")
    with pytest.raises(ImageValidationError):
        validate_image(tmp_path)  # directory


def test_output_cannot_be_evidence(tmp_path):
    img = tmp_path / "e.img"
    img.write_bytes(b"x" * 10)
    with pytest.raises(UnsafePathError):
        ensure_safe_output(img, img)
    with pytest.raises(UnsafePathError):
        ensure_safe_output(img / "sub", img)


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "..", "etc", "passwd")
    assert safe_join(tmp_path, "a", "b") == (tmp_path / "a" / "b").resolve()
    for bad in ["../x", "a/b", "", ".hidden", "x" * 300]:
        with pytest.raises(UnsafePathError):
            safe_identifier(bad)
    with pytest.raises(FileNotFoundError):
        open_case("C1-does-not-exist")


def test_photorec_script_injection_rejected():
    with pytest.raises(ValueError):
        PhotoRecEngine(script="search;rm -rf /")


def test_subprocess_timeout_kills_process():
    t0 = time.perf_counter()
    r = run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert r.timed_out and not r.ok and time.perf_counter() - t0 < 5


def test_subprocess_cancellation():
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    r = run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60, cancel_event=ev)
    assert r.cancelled and not r.ok


def test_missing_executable_reported():
    r = run_command(["definitely-not-a-real-tool-xyz"], timeout=5)
    assert r.returncode is None and "not found" in r.stderr


def test_missing_engine_is_blocked_not_faked(tmp_path, monkeypatch):
    img = tmp_path / "e.img"
    img.write_bytes(b"\0" * 4096)
    monkeypatch.setattr("recoverx.engines.base_engine.resolve_tool", lambda *_a, **_k: None)
    run = SleuthKitEngine().run(img, tmp_path / "out")
    assert run.status == "blocked" and "missing executables" in run.error and run.files == []


def test_shell_metacharacters_are_not_interpreted(tmp_path):
    marker = tmp_path / "pwned"
    r = run_command([sys.executable, "-c", "import sys; print(sys.argv[1])", f"; touch {marker}"], timeout=5)
    assert r.ok and not marker.exists()


@needs_tools
def test_non_empty_output_refused(fat_fixture, tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    (out / "existing").write_text("x")
    run = SleuthKitEngine().run(fat_fixture["image"], out)
    assert run.status == "blocked" and "not empty" in run.error


@needs_tools
def test_unwritable_output_is_reported(fat_fixture, tmp_path):
    out = tmp_path / "ro"
    out.mkdir()
    out.chmod(0o500)
    try:
        run = SleuthKitEngine().run(fat_fixture["image"], out / "x")
        # root bypasses permission bits; either it works or it fails visibly — never silently
        assert run.status in ("completed", "failed", "blocked")
        if run.status != "completed":
            assert run.error
    finally:
        out.chmod(0o700)


@needs_tools
def test_hash_mismatch_detected(fat_fixture, tmp_path):
    copy = tmp_path / "copy.img"
    shutil.copy(fat_fixture["image"], copy)
    case, rec = create_case(copy)
    with open(copy, "r+b") as f:  # simulate tampering after acquisition
        f.seek(100)
        f.write(b"\xff")
    run = run_recovery(case, "tsk", ground_truth=fat_fixture["gt"])
    assert run["status"] == "blocked" and not run["engine_runs"]
    assert "does not match" in run["error"]
    assert case.load()["status"] == "evidence_changed"
    assert case.load()['runs'][-1]['status'] == 'blocked'


@needs_tools
def test_engines_never_modify_source(fat_fixture, tmp_path):
    from recoverx.forensic.hashing import sha256_file
    before = sha256_file(fat_fixture["image"])
    SleuthKitEngine().run(fat_fixture["image"], tmp_path / "a")
    PhotoRecEngine().run(fat_fixture["image"], tmp_path / "b")
    assert sha256_file(fat_fixture["image"]) == before
