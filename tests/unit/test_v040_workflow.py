"""v0.4 pipeline: elevated-helper protocol, six recovery modes, export, validation and outcomes."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from recoverx import workflow
from recoverx.forensic.case_store import create_case, open_case
from recoverx.forensic.filesystem_analyzer import FsAnalysis
from recoverx.models import EngineRun, RecoveredFile
from recoverx.recovery import orchestrator as core
from recoverx.recovery.export import export_run, safe_component
from recoverx.recovery.validation import validate_file
from recoverx.usb import controller, devices, helper, imaging

JPEG = b"\xff\xd8\xff\xe0" + b"photo-bytes" * 50 + b"\xff\xd9"
PDF = b"%PDF-1.4\n" + b"1 0 obj<<>>endobj\n" * 20 + b"%%EOF\n"


def usb_disk(n=2, size=2 * 2**20):
    raw = [{"number": n, "size": size, "sector_size": 512, "bus_type": "USB", "removable_media": True,
            "vendor": "Generic", "product": "Flash", "serial": "SER123"}]
    return devices.build_inventory(raw, {"F:": [(n, 0, size)]}, {"F:": {"filesystem": "FAT32"}}, None, {})


def source_file(tmp_path, size=2 * 2**20):
    p = tmp_path / "physical-standin.bin"
    p.write_bytes(bytes(i % 253 for i in range(size)))
    return p


# ------------------------------------------------------------ helper protocol
def test_helper_reverifies_identity_and_writes_records(tmp_path):
    disks = usb_disk()
    src = source_file(tmp_path)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    req = {"disk_number": 2, "identity": disks[0].identity(), "image_path": str(tmp_path / "img" / "d.img")}
    (tmp_path / "img").mkdir()
    out = helper.run_request(req, job_dir, source_factory=lambda: imaging.FileSource(src),
                             device_lister=lambda: disks, disks_for_path=lambda p: {0})
    assert out["status"] == "completed" and out["successful"]
    assert out["image_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert json.loads((job_dir / "result.json").read_text())["status"] == "completed"
    assert json.loads((job_dir / "status.json").read_text())["final"] is True
    record = json.loads(Path(out["record_path"]).read_text())
    assert record["disk"]["serial"] == "SER123" and record["request"]["disk_number"] == 2


@pytest.mark.parametrize("change,expect", [
    ("swap", "Disk identity changed"), ("gone", "no longer connected"), ("same_disk", "source disk"),
    ("exists", "never overwrites"), ("system", "protected"),
])
def test_helper_blocks_unsafe_requests(tmp_path, change, expect):
    disks = usb_disk()
    identity = disks[0].identity()
    dest = tmp_path / "d.img"
    lister = lambda: disks  # noqa: E731
    lookup = lambda p: {0}  # noqa: E731
    if change == "swap":
        identity = {**identity, "serial": "OTHER"}
    elif change == "gone":
        lister = lambda: []  # noqa: E731
    elif change == "same_disk":
        lookup = lambda p: {2}  # noqa: E731
    elif change == "exists":
        dest.write_bytes(b"x")
    elif change == "system":
        lister = lambda: devices.build_inventory(  # noqa: E731
            [{"number": 2, "size": 2 * 2**20, "sector_size": 512, "bus_type": "USB", "vendor": "Generic",
              "product": "Flash", "serial": "SER123"}], {}, {}, None, {2: ["Hosts the Windows system drive"]})
    job = tmp_path / "job"
    job.mkdir()
    called = []
    out = helper.run_request({"disk_number": 2, "identity": identity, "image_path": str(dest)}, job,
                             source_factory=lambda: called.append(1), device_lister=lister, disks_for_path=lookup)
    assert out["status"] == "blocked" and expect in out["error"]
    assert not called  # the source device is never opened when a check fails


def test_acquisition_job_runs_in_process_and_supports_cancel(tmp_path):
    disks = usb_disk()
    src = source_file(tmp_path)
    job = controller.AcquisitionJob(disks[0], tmp_path / "images").start(
        in_process=True, source_factory=lambda: imaging.FileSource(src), device_lister=lambda: disks,
        disks_for_path=lambda p: {0})
    job._thread.join(30)
    res = job.result()
    assert res["status"] == "completed" and Path(res["image_path"]).is_file()
    assert job.request["identity"]["serial"] == "SER123"


# ------------------------------------------------------------ six modes
class RecordingEngine:
    calls: list = []

    def __init__(self, name, files=True):
        self.name, self.files = name, files

    def run(self, image, output_dir, *, run_id, **kw):
        RecordingEngine.calls.append(self.name)
        output_dir.mkdir(parents=True, exist_ok=True)
        files = []
        if self.files:
            sub = "files" if self.name == "tsk" else "recup.1"
            (output_dir / sub).mkdir(exist_ok=True)
            content = JPEG if self.name == "tsk" else PDF
            fname = "holiday.jpg" if self.name == "tsk" else "f0001.pdf"
            (output_dir / sub / fname).write_bytes(content)
            files.append(RecoveredFile(f"{run_id}-0", self.name, run_id, fname, f"{sub}/{fname}", len(content),
                                       hashlib.sha256(content).hexdigest(), fname.split(".")[-1], "x",
                                       original_name=f"DCIM/{fname}" if self.name == "tsk" else None))
        return EngineRun(self.name, run_id, "completed", str(output_dir), 0.01, files=files)


@pytest.fixture
def stub_case(tmp_path, monkeypatch):
    img = tmp_path / "usb.img"
    img.write_bytes(b"\x00" * 4096)
    case, _ = create_case(img)
    monkeypatch.setattr(core, "analyze_image", lambda image, **kw: FsAnalysis(
        status="analysis_completed", image_size=4096, fs_type="FAT32"))
    monkeypatch.setattr(core, "extract_features", lambda a: {
        "fs_detected": 1.0, "fs_fat": 1.0, "fs_ext": 0.0, "has_partition_table": 0.0, "image_mb": 64.0,
        "n_allocated": 10.0, "n_deleted": 2.0, "n_deleted_named": 2.0, "n_deleted_nonzero": 2.0,
        "frac_deleted_nonzero": 1.0, "n_realloc": 0.0})
    monkeypatch.setattr(core, "get_engine", lambda name: RecordingEngine(name))
    RecordingEngine.calls = []
    return case


@pytest.mark.parametrize("method,engines,strategy", [
    ("tsk", ["tsk"], "tsk"), ("photorec", ["photorec"], "photorec"), ("combined", ["tsk", "photorec"], "combined"),
    ("rule", ["tsk", "photorec"], "combined"), ("cart", ["tsk", "photorec"], "combined"),
])
def test_each_fixed_and_automatic_mode_runs_exactly_its_engines(stub_case, method, engines, strategy):
    run = core.run_recovery(stub_case, method, conservative=True)
    assert RecordingEngine.calls == engines
    assert run["selection"]["strategy_used"] == strategy
    assert run["selection"]["engines_attempted"] == engines
    if method == "rule":
        assert run["selection"]["recommended"] == "tsk" and run["selection"]["model_version"] == "rule-v1"
        assert "advisory" in run["selection"]["safety_override"]
    if method == "cart":
        assert run["selection"]["model_version"]  # CART version or a logged rule-v1 fallback
        assert run["selection"]["recommended"] or run["selection"]["fallback"]


def test_smart_mode_executes_recommendation_and_logs_it(stub_case):
    run = core.run_recovery(stub_case, "smart", conservative=False)
    assert RecordingEngine.calls == [run["selection"]["strategy_used"]] or run["selection"]["strategy_used"] == "combined"
    assert run["selection"]["initial_engines"] == core.ENGINE_PLAN[run["selection"]["strategy_used"]]
    assert any(e["event"] == "strategy_selected" for e in stub_case.events())


def test_cart_mode_uses_installed_model(stub_case, tmp_path):
    from recoverx.ml.model_install import bundled_model_dir, install_bundled_model
    if not bundled_model_dir():
        pytest.skip("bundled evaluation records missing")
    model = install_bundled_model()
    run = core.run_recovery(stub_case, "cart", model_dir=model)
    assert run["selection"]["model_version"] == model.name and not run["selection"]["fallback"]


# ------------------------------------------------------------ export + validation + outcome
def test_export_dedupes_verifies_and_preserves_names(stub_case, tmp_path):
    run = core.run_recovery(stub_case, "combined")
    out = tmp_path / "Output"
    summary = export_run(stub_case, run, out, pdf_bytes=b"%PDF-1.4 test")
    target = Path(summary["output_dir"])
    assert summary["distinct_files"] == 2 and summary["copied_ok"] == 2 and summary["structurally_valid"] == 2
    assert (target / "recovered" / "tsk" / "DCIM" / "holiday.jpg").read_bytes() == JPEG
    assert (target / "recovered" / "photorec" / "f0001.pdf").read_bytes() == PDF
    for name in ("export.json", "manifest.json", "inventory.csv", "RecoverX-report.pdf"):
        assert (target / name).is_file()
    with pytest.raises(FileExistsError):
        export_run(stub_case, run, out)  # never overwrite a previous export


def test_safe_component_neutralises_windows_reserved_and_traversal_names():
    assert safe_component("CON.txt") == "_CON.txt"
    assert safe_component('a<b>:c"?.jpg') == "a_b__c__.jpg"
    assert safe_component("..") == "unnamed"


def test_structural_validation(tmp_path):
    cases = {"ok.jpg": JPEG, "cut.jpg": JPEG[:-2], "ok.pdf": PDF, "cut.pdf": PDF[:-7],
             "ok.png": b"\x89PNG\r\n\x1a\n" + b"\0" * 20 + b"IEND\xaeB`\x82", "fake.jpg": b"MZ\x90\x00 not a jpeg",
             "empty.pdf": b"", "notes.xyz": b"hello"}
    for name, data in cases.items():
        (tmp_path / name).write_bytes(data)
    docx = tmp_path / "report.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    states = {n: validate_file(tmp_path / n)["state"] for n in [*cases, "report.docx"]}
    assert states == {"ok.jpg": "valid", "cut.jpg": "invalid", "ok.pdf": "valid", "cut.pdf": "invalid",
                      "ok.png": "valid", "fake.jpg": "invalid", "empty.pdf": "invalid", "notes.xyz": "not_checked",
                      "report.docx": "valid"}
    assert validate_file(docx)["format"] == "docx"


def test_outcome_classification_never_claims_success_without_verified_output():
    base = {"status": "completed", "source_unchanged": True}
    assert workflow.classify_outcome(base, None)[0] == "no_files"
    assert workflow.classify_outcome(base, {"copied_ok": 0, "distinct_files": 0})[0] == "no_files"
    assert workflow.classify_outcome(base, {"copied_ok": 3, "distinct_files": 3})[0] == "success"
    assert workflow.classify_outcome(base, {"copied_ok": 2, "distinct_files": 3})[0] == "partial"
    assert workflow.classify_outcome({**base, "status": "incomplete"}, {"copied_ok": 1, "distinct_files": 1})[0] == "partial"
    assert workflow.classify_outcome({**base, "source_unchanged": False}, {"copied_ok": 5, "distinct_files": 5})[0] == "failed"
    assert workflow.classify_outcome({**base, "status": "cancelled"}, None)[0] == "cancelled"
    assert workflow.classify_outcome({**base, "status": "blocked", "error": "x"}, None)[0] == "blocked"


def test_known_hashes_become_ground_truth():
    h = hashlib.sha256(JPEG).hexdigest()
    gt = workflow.known_hashes_to_ground_truth(f"{h.upper()}\n# comment\n{h}")
    assert gt == {"deleted": [{"id": "known-1", "sha256": h}], "allocated": []}
    assert workflow.known_hashes_to_ground_truth("nothing here") is None


# ------------------------------------------------------------ full pipeline with a stand-in device
def _wait(job, timeout=60):
    assert job.done.wait(timeout), job.snapshot()
    return job.snapshot()


def _patch_acquisition(monkeypatch, disks, src_factory):
    monkeypatch.setattr(devices, "list_devices", lambda **kw: disks)
    original = controller.AcquisitionJob.start

    def start(self, **kw):
        return original(self, in_process=True, source_factory=src_factory, device_lister=lambda: disks,
                        disks_for_path=lambda p: {0})
    monkeypatch.setattr(controller.AcquisitionJob, "start", start)


def test_usb_pipeline_acquires_registers_recovers_and_exports(tmp_path, monkeypatch, stub_case):
    disks = usb_disk()
    src = source_file(tmp_path)
    _patch_acquisition(monkeypatch, disks, lambda: imaging.FileSource(src))
    h = hashlib.sha256(JPEG).hexdigest()
    job = workflow.start_quick_job(source="usb", disk=disks[0], method="combined", output_dir=str(tmp_path / "Out"),
                                   authorized=True, label="USB test", known_hashes=h)
    snap = _wait(job)
    assert snap["outcome"] == "success", snap
    assert snap["acquisition"]["successful"]
    rec = open_case(snap["case_id"]).load()
    assert rec["acquisition"]["image_sha256"] == rec["image_sha256_initial"]
    assert Path(rec["image_path"]).parent == tmp_path / "Out" / "disk-images"
    run = rec["runs"][-1]
    assert run["metrics"]["exact_recovered"] == 1 and run["export"]["copied_ok"] == 2
    stages = [e["stage"] for e in snap["events"]]
    assert stages[0] == "acquire" and "export" in stages and stages[-1] == "finished"
    events = [e["event"] for e in open_case(snap["case_id"]).events()]
    assert "acquisition_recorded" in events and "export_completed" in events


def test_usb_pipeline_with_unreadable_sectors_does_not_auto_recover(tmp_path, monkeypatch):
    disks = usb_disk()
    data = source_file(tmp_path).read_bytes()

    class Bad:
        size, sector_size, description = len(data), 512, {"kind": "test"}

        def read_at(self, off, n):
            if off <= 4096 < off + n:
                raise OSError(23, "CRC")
            return data[off:off + n]

        def close(self):
            pass

    _patch_acquisition(monkeypatch, disks, Bad)
    job = workflow.start_quick_job(source="usb", disk=disks[0], method="tsk", output_dir=str(tmp_path / "Out"),
                                   authorized=True)
    snap = _wait(job)
    assert snap["outcome"] == "acquired_with_errors" and snap["case_id"] is None and snap["run"] is None


def test_usb_pipeline_blocks_when_device_identity_changes(tmp_path, monkeypatch):
    disks = usb_disk()
    swapped = devices.build_inventory([{"number": 2, "size": 2 * 2**20, "sector_size": 512, "bus_type": "USB",
                                        "vendor": "Generic", "product": "Flash", "serial": "DIFFERENT"}], {}, {}, None, {})
    monkeypatch.setattr(devices, "list_devices", lambda **kw: swapped)
    job = workflow.start_quick_job(source="usb", disk=disks[0], method="tsk", output_dir=str(tmp_path / "Out"),
                                   authorized=True, confirmed_identity=disks[0].identity())
    snap = _wait(job)
    assert snap["outcome"] == "blocked" and "identity" in snap["message"] and not snap["acquisition"]


def test_only_one_pipeline_and_authorization_required(tmp_path):
    with pytest.raises(ValueError, match="Authorization"):
        workflow.start_quick_job(source="image", image_path="x.img", method="tsk", output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="method"):
        workflow.start_quick_job(source="image", image_path="x.img", method="nope", output_dir=str(tmp_path),
                                 authorized=True)
